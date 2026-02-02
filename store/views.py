from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.contrib.auth import login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from .models import Product, Combo, Order, OrderItem, SiteConfig, ProductVariant, OTP, Address, Cart, CartItem, Category
from .auth_utils import check_otp_rate_limit, set_otp_rate_limit, get_client_ip
import json
from datetime import timedelta
import logging
import razorpay
import hmac
import hashlib

logger = logging.getLogger(__name__)

# Initialize Razorpay client
razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

def _user_has_field(user_or_model, field_name):
    model = user_or_model if isinstance(user_or_model, type) else user_or_model.__class__
    return any(field.name == field_name for field in model._meta.get_fields())


def _get_user_display_name(user):
    if _user_has_field(user, "name") and user.name:
        return user.name
    if _user_has_field(user, "first_name") and user.first_name:
        return user.first_name
    if hasattr(user, "get_full_name") and user.get_full_name():
        return user.get_full_name()
    if getattr(user, "email", None):
        return user.email.split("@")[0]
    return "User"


def _set_user_name(user, name):
    if not name:
        return
    if _user_has_field(user, "name"):
        user.name = name
    elif _user_has_field(user, "first_name"):
        user.first_name = name


def _set_user_phone(user, phone):
    if not phone:
        return
    if _user_has_field(user, "phone"):
        user.phone = phone


def get_site_config():
    """Helper to get site configuration"""
    config, _ = SiteConfig.objects.get_or_create(
        id=1,
        defaults={
            'site_name': 'Sulthan Fragrance',
            'phone': '9746 124 520',
            'email': 'sulthanfragrance@gmail.com',
            'instagram_url': 'https://www.instagram.com/sulthanfragrance_official',
            'location': 'Kasaragod'
        }
    )
    return config


def send_admin_order_notification(order):
    """Send email notification to admin when new order is created"""
    try:
        site_config = get_site_config()
        admin_email = site_config.email
        
        # Get domain for the email links
        domain = settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'localhost:8000'
        
        # Prepare context for email template
        context = {
            'order': order,
            'domain': domain,
            'site_config': site_config,
        }
        
        # Render email templates
        subject = f'New Order #{order.order_number} - Sulthan Fragrance'
        text_content = render_to_string('store/emails/admin_new_order.txt', context)
        html_content = render_to_string('store/emails/admin_new_order.html', context)
        
        # Create email message
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[admin_email]
        )
        email.attach_alternative(html_content, "text/html")
        
        # Send email
        email.send(fail_silently=False)
        logger.info(f"Admin notification email sent for order {order.order_number}")
        
        return True
    except Exception as e:
        logger.error(f"Failed to send admin notification for order {order.order_number}: {str(e)}")
        # Don't fail the order creation if email fails
        return False


def home(request):
    """Landing page with products and combos"""
    # Get all categories with active products
    categories = Category.objects.filter(is_active=True).prefetch_related('products')
    
    # Filter by category if specified
    category_slug = request.GET.get('category')
    category_filter = None
    if category_slug:
        category_filter = get_object_or_404(Category, slug=category_slug, is_active=True)
        products = Product.objects.filter(is_active=True, category=category_filter).prefetch_related('variants')
    else:
        products = Product.objects.filter(is_active=True).prefetch_related('variants')
    
    combos = Combo.objects.filter(is_active=True).prefetch_related(
        'combo_products__product__variants',
        'combo_products__variant'
    )
    featured_product = products.filter(is_featured=True).first() or products.first()
    site_config = get_site_config()
    
    # Check if user was redirected here for login
    show_login_modal = request.GET.get('next') is not None and not request.user.is_authenticated
    
    context = {
        'featured_product': featured_product,
        'products': products,
        'combos': combos,
        'categories': categories,
        'current_category': category_filter,
        'site_config': site_config,
        'show_login_modal': show_login_modal,
        'next_url': request.GET.get('next', '/'),
    }
    return render(request, 'store/home.html', context)


def product_detail(request, slug):
    """Product detail page"""
    product = get_object_or_404(
        Product.objects.prefetch_related('variants').select_related('category'),
        slug=slug,
        is_active=True
    )
    
    # Get related products from same category first, then others
    if product.category:
        related_products = Product.objects.filter(
            is_active=True,
            category=product.category
        ).exclude(id=product.id).prefetch_related('variants')[:3]
        
        # If not enough products in same category, add more from other categories
        if related_products.count() < 3:
            additional = Product.objects.filter(
                is_active=True
            ).exclude(id=product.id).exclude(
                id__in=[p.id for p in related_products]
            ).prefetch_related('variants')[:3 - related_products.count()]
            related_products = list(related_products) + list(additional)
    else:
        related_products = Product.objects.filter(
            is_active=True
        ).exclude(id=product.id).prefetch_related('variants')[:3]
    
    site_config = get_site_config()
    
    context = {
        'product': product,
        'related_products': related_products,
        'site_config': site_config,
    }
    return render(request, 'store/product_detail.html', context)


def combo_detail(request, slug):
    """Combo detail page"""
    combo = get_object_or_404(
        Combo.objects.prefetch_related(
            'combo_products__product__variants',
            'combo_products__variant'
        ),
        slug=slug,
        is_active=True
    )
    site_config = get_site_config()
    combo_items = combo.combo_products.select_related('product', 'variant')
    
    context = {
        'combo': combo,
        'combo_items': combo_items,
        'site_config': site_config,
    }
    return render(request, 'store/combo_detail.html', context)


@login_required
def cart(request):
    """Cart page - requires authentication"""
    site_config = get_site_config()
    cart_obj = get_or_create_cart(request.user)
    context = {
        'site_config': site_config,
        'cart': cart_obj,
    }
    return render(request, 'store/cart.html', context)


@login_required
def checkout(request):
    """Checkout page - requires authentication"""
    site_config = get_site_config()
    
    # Get cart with items prefetched
    cart_obj = get_or_create_cart(request.user)
    
    # Debug: Check if cart exists and has items
    if not cart_obj:
        messages.error(request, 'Unable to retrieve your cart. Please try again.')
        return redirect('store:cart')
    
    # Prefetch related items for better performance
    cart_obj = Cart.objects.prefetch_related(
        'items__product__variants',
        'items__variant',
        'items__combo'
    ).get(id=cart_obj.id)
    
    item_count = cart_obj.items.count()
    
    if item_count == 0:
        messages.warning(request, 'Your cart is empty. Please add items before checking out.')
        return redirect('store:cart')
    
    # Get user addresses
    addresses = Address.objects.filter(user=request.user).order_by('-is_default', '-created_at')
    
    context = {
        'site_config': site_config,
        'cart': cart_obj,
        'addresses': addresses,
    }
    return render(request, 'store/checkout.html', context)


@login_required
@require_http_methods(["POST"])
def create_razorpay_order(request):
    """Create Razorpay order before payment"""
    try:
        data = json.loads(request.body)
        
        # Get user's active cart
        cart = get_or_create_cart(request.user)
        if not cart or cart.items.count() == 0:
            return JsonResponse({'success': False, 'error': 'Cart is empty'}, status=400)
        
        # Validate required fields
        required_fields = ['customer_name', 'phone', 'address_line', 'city', 'district', 'pincode']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'success': False, 'error': f'{field} is required'}, status=400)
        
        # Calculate total from cart items (Razorpay requires amount in paise/cents)
        total_amount = float(cart.get_total())
        amount_in_paise = int(total_amount * 100)  # Convert to paise
        
        # Create order in our database first (with pending status)
        with transaction.atomic():
            order = Order.objects.create(
                user=request.user,
                cart=cart,
                customer_name=data['customer_name'],
                phone=data['phone'],
                address_line=data['address_line'],
                city=data['city'],
                district=data['district'],
                pincode=data['pincode'],
                total_amount=total_amount,
                payment_method='online',
                payment_status='pending',
                status='new'
            )
            
            # Create order items from cart
            for cart_item in cart.items.select_related('product', 'variant', 'combo').all():
                OrderItem.objects.create(
                    order=order,
                    item_type=cart_item.item_type,
                    product=cart_item.product,
                    combo=cart_item.combo,
                    variant=cart_item.variant,
                    variant_ml=cart_item.variant_ml,
                    quantity=cart_item.quantity,
                    price_at_purchase=cart_item.price_at_time
                )
        
        # Create Razorpay order
        razorpay_order = razorpay_client.order.create({
            'amount': amount_in_paise,
            'currency': 'INR',
            'receipt': order.order_number,
            'notes': {
                'order_id': str(order.id),
                'customer_name': order.customer_name,
                'email': request.user.email
            }
        })
        
        # Update order with Razorpay order ID
        order.razorpay_order_id = razorpay_order['id']
        order.save()
        
        logger.info(f"Razorpay order created: {razorpay_order['id']} for order {order.order_number}")
        
        return JsonResponse({
            'success': True,
            'razorpay_order_id': razorpay_order['id'],
            'razorpay_key_id': settings.RAZORPAY_KEY_ID,
            'amount': amount_in_paise,
            'currency': 'INR',
            'order_id': str(order.id),
            'order_number': order.order_number,
            'customer_name': order.customer_name,
            'customer_email': request.user.email,
            'customer_phone': order.phone
        })
        
    except Exception as e:
        logger.error(f"Error creating Razorpay order: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def create_cod_order(request):
    """Create Razorpay order for COD advance payment (₹50)"""
    try:
        data = json.loads(request.body)
        
        # Get user's active cart
        cart = get_or_create_cart(request.user)
        if not cart or cart.items.count() == 0:
            return JsonResponse({'success': False, 'error': 'Cart is empty'}, status=400)
        
        # Validate required fields
        required_fields = ['customer_name', 'phone', 'address_line', 'city', 'district', 'pincode']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'success': False, 'error': f'{field} is required'}, status=400)
        
        # Calculate total and COD amounts
        total_amount = float(cart.get_total())
        advance_payment = float(settings.COD_ADVANCE_PAYMENT)
        cod_balance = total_amount - advance_payment
        
        # Validate that total is greater than advance payment
        if total_amount < advance_payment:
            return JsonResponse({
                'success': False, 
                'error': f'Order total must be at least ₹{advance_payment}'
            }, status=400)
        
        # Convert advance payment to paise for Razorpay
        amount_in_paise = int(advance_payment * 100)
        
        # Create order in our database first (with pending status)
        with transaction.atomic():
            order = Order.objects.create(
                user=request.user,
                cart=cart,
                customer_name=data['customer_name'],
                phone=data['phone'],
                address_line=data['address_line'],
                city=data['city'],
                district=data['district'],
                pincode=data['pincode'],
                total_amount=total_amount,
                advance_payment_amount=advance_payment,
                cod_balance_amount=cod_balance,
                payment_method='cod',
                payment_status='pending',
                status='new'
            )
            
            # Create order items from cart
            for cart_item in cart.items.select_related('product', 'variant', 'combo').all():
                OrderItem.objects.create(
                    order=order,
                    item_type=cart_item.item_type,
                    product=cart_item.product,
                    combo=cart_item.combo,
                    variant=cart_item.variant,
                    variant_ml=cart_item.variant_ml,
                    quantity=cart_item.quantity,
                    price_at_purchase=cart_item.price_at_time
                )
        
        # Create Razorpay order for advance payment
        razorpay_order = razorpay_client.order.create({
            'amount': amount_in_paise,
            'currency': 'INR',
            'receipt': f"{order.order_number}-ADV",
            'notes': {
                'order_id': str(order.id),
                'customer_name': order.customer_name,
                'email': request.user.email,
                'payment_type': 'COD Advance Payment',
                'balance_cod': cod_balance
            }
        })
        
        # Update order with Razorpay order ID
        order.razorpay_order_id = razorpay_order['id']
        order.save()
        
        logger.info(f"COD order created with advance payment: {order.order_number}")
        
        return JsonResponse({
            'success': True,
            'razorpay_order_id': razorpay_order['id'],
            'razorpay_key_id': settings.RAZORPAY_KEY_ID,
            'amount': amount_in_paise,
            'currency': 'INR',
            'order_id': str(order.id),
            'order_number': order.order_number,
            'customer_name': order.customer_name,
            'customer_email': request.user.email,
            'customer_phone': order.phone,
            'advance_payment': advance_payment,
            'cod_balance': cod_balance,
            'total_amount': total_amount
        })
        
    except Exception as e:
        logger.error(f"Error creating COD order: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def verify_payment(request):
    """Verify Razorpay payment signature and update order status"""
    try:
        data = json.loads(request.body)
        
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_signature = data.get('razorpay_signature')
        
        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            return JsonResponse({'success': False, 'error': 'Missing payment parameters'}, status=400)
        
        # Find the order
        order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user)
        
        # Verify signature
        generated_signature = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(),
            f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
            hashlib.sha256
        ).hexdigest()
        
        if generated_signature != razorpay_signature:
            logger.error(f"Payment signature verification failed for order {order.order_number}")
            order.payment_status = 'failed'
            order.save()
            return JsonResponse({'success': False, 'error': 'Payment verification failed'}, status=400)
        
        # Payment verified successfully
        with transaction.atomic():
            order.razorpay_payment_id = razorpay_payment_id
            order.razorpay_signature = razorpay_signature
            order.payment_status = 'completed'
            order.payment_reference = razorpay_payment_id
            order.save()
            
            # Mark cart as checked out
            if order.cart:
                order.cart.status = 'checked_out'
                order.cart.save()
            
            # Create a new active cart for the user
            Cart.objects.get_or_create(
                user=request.user,
                status='active'
            )
        
        # Send email notification to admin
        try:
            send_admin_order_notification(order)
        except Exception as e:
            logger.error(f"Failed to send admin notification: {str(e)}")
            # Continue even if email fails
        
        logger.info(f"Payment verified successfully for order {order.order_number}")
        
        return JsonResponse({
            'success': True,
            'order_number': order.order_number,
            'order_id': str(order.id),
            'message': 'Payment verified successfully'
        })
        
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
    except Exception as e:
        logger.error(f"Error verifying payment: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def verify_cod_advance_payment(request):
    """Verify COD advance payment and finalize order"""
    try:
        data = json.loads(request.body)
        
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_signature = data.get('razorpay_signature')
        
        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            return JsonResponse({'success': False, 'error': 'Missing payment parameters'}, status=400)
        
        # Find the order
        order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user)
        
        # Verify signature
        generated_signature = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(),
            f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
            hashlib.sha256
        ).hexdigest()
        
        if generated_signature != razorpay_signature:
            logger.error(f"COD advance payment verification failed for order {order.order_number}")
            order.payment_status = 'failed'
            order.status = 'cancelled'
            order.save()
            return JsonResponse({'success': False, 'error': 'Payment verification failed'}, status=400)
        
        # Payment verified successfully
        with transaction.atomic():
            order.razorpay_payment_id = razorpay_payment_id
            order.razorpay_signature = razorpay_signature
            order.payment_status = 'pending'  # Pending for COD balance payment
            order.payment_reference = razorpay_payment_id
            order.save()
            
            # Mark cart as checked out
            if order.cart:
                order.cart.status = 'checked_out'
                order.cart.save()
            
            # Create a new active cart for the user
            Cart.objects.get_or_create(
                user=request.user,
                status='active'
            )
        
        # Send email notification to admin
        try:
            send_admin_order_notification(order)
        except Exception as e:
            logger.error(f"Failed to send admin notification: {str(e)}")
            # Continue even if email fails
        
        logger.info(f"COD advance payment verified for order {order.order_number}")
        
        return JsonResponse({
            'success': True,
            'order_number': order.order_number,
            'order_id': str(order.id),
            'message': 'Advance payment verified successfully'
        })
        
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
    except Exception as e:
        logger.error(f"Error verifying COD advance payment: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def payment_failed(request):
    """Handle payment failure - mark order as failed"""
    try:
        data = json.loads(request.body)
        razorpay_order_id = data.get('razorpay_order_id')
        
        if not razorpay_order_id:
            return JsonResponse({'success': False, 'error': 'Order ID is required'}, status=400)
        
        order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user)
        
        # Mark order as failed
        order.payment_status = 'failed'
        order.status = 'cancelled'
        order.save()
        
        logger.info(f"Payment marked as failed for order {order.order_number}")
        
        return JsonResponse({
            'success': True,
            'message': 'Payment failed',
            'order_number': order.order_number
        })
        
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
    except Exception as e:
        logger.error(f"Error handling payment failure: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def razorpay_webhook(request):
    """Handle Razorpay webhook events"""
    try:
        # Verify webhook signature
        webhook_signature = request.headers.get('X-Razorpay-Signature')
        webhook_secret = settings.RAZORPAY_KEY_SECRET
        
        if not webhook_signature:
            logger.warning("Webhook received without signature")
            return JsonResponse({'status': 'error', 'message': 'No signature'}, status=400)
        
        # Verify signature
        expected_signature = hmac.new(
            webhook_secret.encode(),
            request.body,
            hashlib.sha256
        ).hexdigest()
        
        if webhook_signature != expected_signature:
            logger.warning("Webhook signature verification failed")
            return JsonResponse({'status': 'error', 'message': 'Invalid signature'}, status=400)
        
        # Parse webhook data
        data = json.loads(request.body)
        event = data.get('event')
        payload = data.get('payload', {}).get('payment', {}).get('entity', {})
        
        logger.info(f"Webhook received: {event}")
        
        # Handle payment events
        if event == 'payment.captured':
            razorpay_order_id = payload.get('order_id')
            razorpay_payment_id = payload.get('id')
            
            try:
                order = Order.objects.get(razorpay_order_id=razorpay_order_id)
                
                if order.payment_status != 'completed':
                    order.payment_status = 'completed'
                    order.razorpay_payment_id = razorpay_payment_id
                    order.save()
                    
                    logger.info(f"Payment captured via webhook for order {order.order_number}")
                    
                    # Send admin notification if not already sent
                    try:
                        send_admin_order_notification(order)
                    except Exception as e:
                        logger.error(f"Failed to send admin notification: {str(e)}")
                        
            except Order.DoesNotExist:
                logger.warning(f"Order not found for Razorpay order ID: {razorpay_order_id}")
        
        elif event == 'payment.failed':
            razorpay_order_id = payload.get('order_id')
            
            try:
                order = Order.objects.get(razorpay_order_id=razorpay_order_id)
                order.payment_status = 'failed'
                order.status = 'cancelled'
                order.save()
                
                logger.info(f"Payment failed via webhook for order {order.order_number}")
                
            except Order.DoesNotExist:
                logger.warning(f"Order not found for Razorpay order ID: {razorpay_order_id}")
        
        return JsonResponse({'status': 'ok'})
        
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def order_confirmation(request, order_number):
    """Order confirmation page"""
    order = get_object_or_404(Order, order_number=order_number)
    site_config = get_site_config()
    
    context = {
        'order': order,
        'site_config': site_config,
    }
    return render(request, 'store/order_confirmation.html', context)


# ==================== AUTHENTICATION VIEWS ====================

@require_http_methods(["POST"])
def send_otp(request):
    """Send OTP to email"""
    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()
        
        # Validate email
        if not email:
            return JsonResponse({'success': False, 'error': 'Email is required'}, status=400)
        
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({'success': False, 'error': 'Invalid email format'}, status=400)
        
        # Check rate limit
        ip_address = get_client_ip(request)
        is_allowed, remaining = check_otp_rate_limit(email, ip_address, limit_minutes=1)
        if not is_allowed:
            return JsonResponse({
                'success': False,
                'error': f'Please wait {remaining} seconds before requesting another OTP'
            }, status=429)
        
        # Create OTP
        otp, otp_code = OTP.create_otp(email, ip_address)
        
        # Set rate limit
        set_otp_rate_limit(email, ip_address, limit_minutes=1)
        
        # Send email
        site_config = get_site_config()
        subject = f'Your Login OTP - {site_config.site_name}'
        
        # HTML email template
        html_message = render_to_string('store/emails/otp_email.html', {
            'otp': otp_code,
            'site_config': site_config,
            'expiry_minutes': 10,
        })
        
        # Plain text email template
        plain_message = render_to_string('store/emails/otp_email.txt', {
            'otp': otp_code,
            'site_config': site_config,
            'expiry_minutes': 10,
        })
        
        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                html_message=html_message,
                fail_silently=False,
            )
        except Exception as e:
            # Log the actual error for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Failed to send OTP email to {email}: {str(e)}', exc_info=True)
            
            return JsonResponse({
                'success': False,
                'error': f'Failed to send email: {str(e)}. Please check your email configuration.'
            }, status=500)
        
        return JsonResponse({
            'success': True,
            'message': 'OTP sent to your email'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["POST"])
def verify_otp(request):
    """Verify OTP and login user"""
    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()
        otp_code = data.get('otp', '').strip()
        next_url = data.get('next', '/')
        
        if not email or not otp_code:
            return JsonResponse({'success': False, 'error': 'Email and OTP are required'}, status=400)
        
        # Find valid OTP
        otp = OTP.objects.filter(
            email=email,
            is_used=False
        ).order_by('-created_at').first()
        
        if not otp:
            return JsonResponse({'success': False, 'error': 'Invalid or expired OTP'}, status=400)
        
        # Verify OTP
        if not otp.verify(otp_code):
            return JsonResponse({'success': False, 'error': 'Invalid or expired OTP'}, status=400)
        
        # Get or create user (supports built-in or custom user models)
        UserModel = get_user_model()
        user = UserModel.objects.filter(email__iexact=email).first()
        if not user:
            create_kwargs = {}
            username_field = getattr(UserModel, "USERNAME_FIELD", None)
            if username_field:
                create_kwargs[username_field] = email
            # Only set email if the model has an email field
            if _user_has_field(UserModel, "email"):
                create_kwargs["email"] = email
            user = UserModel(**create_kwargs)
            if hasattr(user, "set_unusable_password"):
                user.set_unusable_password()
            _set_user_name(user, email.split("@")[0])
            user.save()
        
        # Login user
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        
        # Note: Cart merging will be handled by frontend via merge_cart API
        
        return JsonResponse({
            'success': True,
            'message': 'Login successful',
            'next': next_url,
            'user': {
                'email': user.email,
                'name': _get_user_display_name(user)
            }
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def logout_view(request):
    """Logout user"""
    logout(request)
    
    # Handle AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Logged out successfully'})
    
    # Handle regular requests - redirect to home
    messages.success(request, 'You have been logged out successfully.')
    return redirect('store:home')


# ==================== CART UTILITIES ====================

def get_or_create_cart(user):
    """Get or create active cart for user"""
    if not user or not user.is_authenticated:
        return None
    cart, _ = Cart.objects.get_or_create(
        user=user,
        status='active',
        defaults={}
    )
    return cart


def merge_session_cart_to_db(request, user):
    """Merge session cart items to database cart"""
    if not user or not user.is_authenticated:
        return
    
    # Get session cart (from session storage, we'll need to pass it from frontend)
    # For now, we'll handle this in the API endpoint
    pass


def get_session_cart_from_request(request):
    """Get cart items from request (sent from frontend)"""
    try:
        data = json.loads(request.body) if request.body else {}
        return data.get('session_cart', [])
    except:
        return []


# ==================== CART API VIEWS ====================

@require_http_methods(["GET", "POST"])
def cart_api(request):
    """Get or add items to cart"""
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': 'Authentication required',
            'requires_login': True
        }, status=401)
    
    if request.method == 'GET':
        return get_cart(request)
    elif request.method == 'POST':
        return add_to_cart(request)


@login_required
def get_cart(request):
    """Get user's cart"""
    try:
        cart = get_or_create_cart(request.user)
        if not cart:
            return JsonResponse({'success': True, 'cart': [], 'total': 0, 'item_count': 0})
        
        items = []
        for item in cart.items.select_related('product', 'variant', 'combo').all():
            item_data = {
                'id': str(item.id),
                'type': item.item_type,
                'quantity': item.quantity,
                'price': float(item.price_at_time),
                'subtotal': float(item.subtotal),
            }
            
            if item.item_type == 'product':
                item_data.update({
                    'product_id': str(item.product.id),
                    'product_name': item.product.name,
                    'product_image': item.product.image.url if item.product.image else '',
                    'variant_id': str(item.variant.id) if item.variant else None,
                    'variant_ml': item.variant.ml if item.variant else None,
                })
            elif item.item_type == 'combo':
                item_data.update({
                    'combo_id': str(item.combo.id),
                    'combo_title': item.combo.title,
                    'combo_image': item.combo.image.url if item.combo.image else '',
                })
            
            items.append(item_data)
        
        return JsonResponse({
            'success': True,
            'cart': items,
            'total': float(cart.get_total()),
            'item_count': cart.get_item_count()
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def add_to_cart(request):
    """Add item to cart"""
    try:
        data = json.loads(request.body)
        item_type = data.get('type')  # 'product' or 'combo'
        item_id = data.get('id')
        quantity = int(data.get('quantity', 1))
        variant_id = data.get('variant_id')
        
        if not item_type or not item_id:
            return JsonResponse({'success': False, 'error': 'Type and ID are required'}, status=400)
        
        cart = get_or_create_cart(request.user)
        if not cart:
            return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
        
        with transaction.atomic():
            if item_type == 'product':
                product = get_object_or_404(Product, id=item_id, is_active=True)
                if not variant_id:
                    variant = product.default_variant
                    if not variant:
                        return JsonResponse({'success': False, 'error': 'Product variant not found'}, status=404)
                else:
                    variant = get_object_or_404(ProductVariant, id=variant_id, product=product, is_active=True)
                
                price = variant.price
                
                # Check if item already exists
                cart_item, created = CartItem.objects.get_or_create(
                    cart=cart,
                    item_type='product',
                    product=product,
                    variant=variant,
                    defaults={
                        'quantity': quantity,
                        'price_at_time': price,
                        'variant_ml': variant.ml
                    }
                )
                
                if not created:
                    cart_item.quantity += quantity
                    cart_item.save()
            
            elif item_type == 'combo':
                combo = get_object_or_404(Combo, id=item_id, is_active=True)
                price = combo.discounted_price()
                
                # Check if item already exists
                cart_item, created = CartItem.objects.get_or_create(
                    cart=cart,
                    item_type='combo',
                    combo=combo,
                    defaults={
                        'quantity': quantity,
                        'price_at_time': price
                    }
                )
                
                if not created:
                    cart_item.quantity += quantity
                    cart_item.save()
            else:
                return JsonResponse({'success': False, 'error': 'Invalid item type'}, status=400)
        
        return JsonResponse({
            'success': True,
            'message': 'Item added to cart',
            'cart_count': cart.get_item_count()
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def update_cart_item(request, item_id):
    """Update cart item quantity"""
    try:
        data = json.loads(request.body)
        quantity = int(data.get('quantity', 1))
        
        if quantity < 1:
            return JsonResponse({'success': False, 'error': 'Quantity must be at least 1'}, status=400)
        
        cart = get_or_create_cart(request.user)
        cart_item = get_object_or_404(CartItem, id=item_id, cart=cart)
        
        cart_item.quantity = quantity
        cart_item.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Cart updated',
            'subtotal': float(cart_item.subtotal),
            'total': float(cart.get_total()),
            'item_count': cart.get_item_count()
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def remove_from_cart(request, item_id):
    """Remove item from cart"""
    try:
        cart = get_or_create_cart(request.user)
        cart_item = get_object_or_404(CartItem, id=item_id, cart=cart)
        cart_item.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Item removed from cart',
            'total': float(cart.get_total()),
            'item_count': cart.get_item_count()
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def merge_cart(request):
    """Merge session cart to database cart"""
    try:
        session_cart = get_session_cart_from_request(request)
        if not session_cart:
            return JsonResponse({'success': True, 'message': 'No items to merge'})
        
        cart = get_or_create_cart(request.user)
        
        with transaction.atomic():
            for item in session_cart:
                item_type = item.get('type')
                item_id = item.get('id')
                quantity = int(item.get('quantity', 1))
                variant_id = item.get('variant_id')
                
                if item_type == 'product':
                    try:
                        product = Product.objects.get(id=item_id, is_active=True)
                        if variant_id:
                            variant = ProductVariant.objects.get(id=variant_id, product=product, is_active=True)
                        else:
                            variant = product.default_variant
                        
                        if variant:
                            price = variant.price
                            cart_item, created = CartItem.objects.get_or_create(
                                cart=cart,
                                item_type='product',
                                product=product,
                                variant=variant,
                                defaults={
                                    'quantity': quantity,
                                    'price_at_time': price,
                                    'variant_ml': variant.ml
                                }
                            )
                            if not created:
                                cart_item.quantity += quantity
                                cart_item.save()
                    except (Product.DoesNotExist, ProductVariant.DoesNotExist):
                        continue
                
                elif item_type == 'combo':
                    try:
                        combo = Combo.objects.get(id=item_id, is_active=True)
                        price = combo.discounted_price()
                        cart_item, created = CartItem.objects.get_or_create(
                            cart=cart,
                            item_type='combo',
                            combo=combo,
                            defaults={
                                'quantity': quantity,
                                'price_at_time': price
                            }
                        )
                        if not created:
                            cart_item.quantity += quantity
                            cart_item.save()
                    except Combo.DoesNotExist:
                        continue
        
        return JsonResponse({
            'success': True,
            'message': 'Cart merged successfully',
            'cart_count': cart.get_item_count()
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== ACCOUNT MANAGEMENT VIEWS ====================

@login_required
def my_orders(request):
    """User's order history"""
    site_config = get_site_config()
    orders = Order.objects.filter(user=request.user).prefetch_related('items').order_by('-created_at')
    
    context = {
        'site_config': site_config,
        'orders': orders,
    }
    return render(request, 'store/account/my_orders.html', context)


@login_required
def order_detail(request, order_number):
    """Order detail page"""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    site_config = get_site_config()
    
    context = {
        'order': order,
        'site_config': site_config,
    }
    return render(request, 'store/account/order_detail.html', context)


@login_required
def my_addresses(request):
    """User's addresses management"""
    site_config = get_site_config()
    addresses = Address.objects.filter(user=request.user).order_by('-is_default', '-created_at')
    
    context = {
        'site_config': site_config,
        'addresses': addresses,
    }
    return render(request, 'store/account/my_addresses.html', context)


@login_required
@require_http_methods(["POST"])
def add_address(request):
    """Add new address"""
    try:
        data = json.loads(request.body)
        
        required_fields = ['name', 'phone', 'address_line', 'city', 'district', 'pincode']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'success': False, 'error': f'{field} is required'}, status=400)
        
        address = Address.objects.create(
            user=request.user,
            name=data['name'],
            phone=data['phone'],
            address_line=data['address_line'],
            city=data['city'],
            district=data['district'],
            pincode=data['pincode'],
            is_default=data.get('is_default', False)
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Address added successfully',
            'address': {
                'id': str(address.id),
                'name': address.name,
                'phone': address.phone,
                'address_line': address.address_line,
                'city': address.city,
                'district': address.district,
                'pincode': address.pincode,
                'is_default': address.is_default
            }
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def update_address(request, address_id):
    """Update address"""
    try:
        address = get_object_or_404(Address, id=address_id, user=request.user)
        data = json.loads(request.body)
        
        address.name = data.get('name', address.name)
        address.phone = data.get('phone', address.phone)
        address.address_line = data.get('address_line', address.address_line)
        address.city = data.get('city', address.city)
        address.district = data.get('district', address.district)
        address.pincode = data.get('pincode', address.pincode)
        address.is_default = data.get('is_default', address.is_default)
        address.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Address updated successfully'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def delete_address(request, address_id):
    """Delete address"""
    try:
        address = get_object_or_404(Address, id=address_id, user=request.user)
        address.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Address deleted successfully'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def my_profile(request):
    """User profile page"""
    site_config = get_site_config()
    
    context = {
        'site_config': site_config,
        'user': request.user,
    }
    return render(request, 'store/account/my_profile.html', context)


@login_required
@require_http_methods(["POST"])
def update_profile(request):
    """Update user profile"""
    try:
        data = json.loads(request.body)
        
        user = request.user
        _set_user_name(user, data.get('name'))
        _set_user_phone(user, data.get('phone'))
        user.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Profile updated successfully',
            'user': {
                'email': getattr(user, 'email', None),
                'name': _get_user_display_name(user),
                'phone': getattr(user, 'phone', None)
            }
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== LEGAL & INFORMATION PAGES ====================

def privacy_policy(request):
    """Privacy Policy page"""
    site_config = get_site_config()
    context = {
        'site_config': site_config,
    }
    return render(request, 'store/privacy_policy.html', context)


def cancellations_refunds(request):
    """Cancellations and Refunds page"""
    site_config = get_site_config()
    context = {
        'site_config': site_config,
    }
    return render(request, 'store/cancellations_refunds.html', context)


def terms_conditions(request):
    """Terms and Conditions page"""
    site_config = get_site_config()
    context = {
        'site_config': site_config,
    }
    return render(request, 'store/terms_conditions.html', context)


def contact_us(request):
    """Contact Us page"""
    site_config = get_site_config()
    context = {
        'site_config': site_config,
    }
    return render(request, 'store/contact_us.html', context)