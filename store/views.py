from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from .models import Product, Combo, Order, OrderItem, SiteConfig, ProductVariant, Cart, CartItem, Category
from .utils import parse_uuid
import json
import logging
import razorpay
import hmac
import hashlib

logger = logging.getLogger(__name__)

# Initialize Razorpay client
razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

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
    
    # Group products by category for display
    if category_slug:
        category_filter = get_object_or_404(Category, slug=category_slug, is_active=True)
        # If filtering by specific category, show only that category
        products_by_category = [
            {
                'category': category_filter,
                'products': Product.objects.filter(
                    is_active=True, 
                    category=category_filter
                ).prefetch_related('variants')
            }
        ]
        products = Product.objects.filter(is_active=True, category=category_filter).prefetch_related('variants')
    else:
        # Group all products by their categories
        products_by_category = []
        for category in categories:
            category_products = Product.objects.filter(
                is_active=True,
                category=category
            ).prefetch_related('variants')
            if category_products.exists():
                products_by_category.append({
                    'category': category,
                    'products': category_products
                })
        
        # Also include products without a category (if any)
        uncategorized_products = Product.objects.filter(
            is_active=True,
            category__isnull=True
        ).prefetch_related('variants')
        if uncategorized_products.exists():
            products_by_category.append({
                'category': None,
                'products': uncategorized_products
            })
        
        products = Product.objects.filter(is_active=True).prefetch_related('variants')
    
    combos = Combo.objects.filter(is_active=True).prefetch_related(
        'combo_products__product__variants',
        'combo_products__variant'
    )
    featured_product = products.filter(is_featured=True).first() or products.first()
    site_config = get_site_config()
    
    context = {
        'featured_product': featured_product,
        'products': products,
        'products_by_category': products_by_category,
        'combos': combos,
        'categories': categories,
        'current_category': category_filter,
        'site_config': site_config,
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


def cart(request):
    """Cart page - guest or user"""
    site_config = get_site_config()
    cart_obj = get_or_create_cart(request)
    context = {
        'site_config': site_config,
        'cart': cart_obj,
    }
    return render(request, 'store/cart.html', context)


def checkout(request):
    """Checkout page - guest checkout, no login required"""
    site_config = get_site_config()
    
    # Get cart with items prefetched
    cart_obj = get_or_create_cart(request)
    
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
    
    context = {
        'site_config': site_config,
        'cart': cart_obj,
    }
    return render(request, 'store/checkout.html', context)


@require_http_methods(["POST"])
def create_razorpay_order(request):
    """Create Razorpay order before payment (guest checkout)"""
    try:
        data = json.loads(request.body)
        
        # Get guest's active cart
        cart = get_or_create_cart(request)
        if not cart or cart.items.count() == 0:
            return JsonResponse({'success': False, 'error': 'Cart is empty'}, status=400)
        
        # Validate required fields (phone-only, no email)
        required_fields = ['customer_name', 'phone', 'address_line', 'city', 'district', 'pincode']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'success': False, 'error': f'{field} is required'}, status=400)
        
        # Calculate total from cart items (Razorpay requires amount in paise/cents)
        total_amount = float(cart.get_total())
        amount_in_paise = int(total_amount * 100)  # Convert to paise
        
        guest_id = getattr(request, 'guest_id', None)
        
        # Create order in our database first (with pending status)
        with transaction.atomic():
            order = Order.objects.create(
                user=None,
                guest_id=guest_id,
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
                    variant_quantity_value=cart_item.variant_quantity_value,
                    variant_quantity_unit=cart_item.variant_quantity_unit,
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
            # Phone-only checkout; email is no longer collected from customer
            'customer_email': '',
            'customer_phone': order.phone
        })
        
    except Exception as e:
        logger.error(f"Error creating Razorpay order: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["POST"])
def create_cod_order(request):
    """Create Razorpay order for COD advance payment (₹50) - guest checkout"""
    try:
        data = json.loads(request.body)
        
        # Get guest's active cart
        cart = get_or_create_cart(request)
        if not cart or cart.items.count() == 0:
            return JsonResponse({'success': False, 'error': 'Cart is empty'}, status=400)
        
        # Validate required fields (phone-only, no email)
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
        
        guest_id = getattr(request, 'guest_id', None)
        
        # Create order in our database first (with pending status)
        with transaction.atomic():
            order = Order.objects.create(
                user=None,
                guest_id=guest_id,
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
                    variant_quantity_value=cart_item.variant_quantity_value,
                    variant_quantity_unit=cart_item.variant_quantity_unit,
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
            # Phone-only checkout; email is no longer collected from customer
            'customer_email': '',
            'customer_phone': order.phone,
            'advance_payment': advance_payment,
            'cod_balance': cod_balance,
            'total_amount': total_amount
        })
        
    except Exception as e:
        logger.error(f"Error creating COD order: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["POST"])
def verify_payment(request):
    """Verify Razorpay payment signature and update order status (guest-safe by guest_id)"""
    try:
        data = json.loads(request.body)
        
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_signature = data.get('razorpay_signature')
        
        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            return JsonResponse({'success': False, 'error': 'Missing payment parameters'}, status=400)
        
        guest_id = getattr(request, 'guest_id', None)
        order = Order.objects.filter(razorpay_order_id=razorpay_order_id).first()
        if not order:
            return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
        if order.guest_id and order.guest_id != guest_id:
            return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
        if order.user_id and request.user.is_authenticated and order.user_id != request.user.pk:
            return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
        
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
            
            # New active cart is created on next request via get_or_create_cart(guest_id)
        
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
        
    except Exception as e:
        logger.error(f"Error verifying payment: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["POST"])
def verify_cod_advance_payment(request):
    """Verify COD advance payment and finalize order (guest-safe by guest_id)"""
    try:
        data = json.loads(request.body)
        
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_signature = data.get('razorpay_signature')
        
        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            return JsonResponse({'success': False, 'error': 'Missing payment parameters'}, status=400)
        
        guest_id = getattr(request, 'guest_id', None)
        order = Order.objects.filter(razorpay_order_id=razorpay_order_id).first()
        if not order:
            return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
        if order.guest_id and order.guest_id != guest_id:
            return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
        if order.user_id and request.user.is_authenticated and order.user_id != request.user.pk:
            return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
        
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
        
    except Exception as e:
        logger.error(f"Error verifying COD advance payment: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["POST"])
def payment_failed(request):
    """Handle payment failure - mark order as failed (guest-safe by guest_id)"""
    try:
        data = json.loads(request.body)
        razorpay_order_id = data.get('razorpay_order_id')
        
        if not razorpay_order_id:
            return JsonResponse({'success': False, 'error': 'Order ID is required'}, status=400)
        
        guest_id = getattr(request, 'guest_id', None)
        order = Order.objects.filter(razorpay_order_id=razorpay_order_id).first()
        if not order:
            return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
        if order.guest_id and order.guest_id != guest_id:
            return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
        if order.user_id and request.user.is_authenticated and order.user_id != request.user.pk:
            return JsonResponse({'success': False, 'error': 'Order not found'}, status=404)
        
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


# ==================== CART UTILITIES ====================

def get_or_create_cart(request):
    """Get or create active cart for guest (guest_id from cookie) or user."""
    guest_id = getattr(request, 'guest_id', None)
    if guest_id:
        cart, _ = Cart.get_or_create_active_cart(guest_id=guest_id)
        return cart
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        cart, _ = Cart.get_or_create_active_cart(user=user)
        return cart
    return None


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
    """Get or add items to cart (guest or user)"""
    if request.method == 'GET':
        return get_cart(request)
    elif request.method == 'POST':
        return add_to_cart(request)


def get_cart(request):
    """Get guest's or user's cart"""
    try:
        cart = get_or_create_cart(request)
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
                variant_ml = None
                variant_quantity_value = None
                variant_quantity_unit = None
                
                if item.variant:
                    # Use new quantity system if available, fall back to legacy ml
                    if item.variant.quantity_value and item.variant.quantity_unit:
                        variant_quantity_value = float(item.variant.quantity_value)
                        variant_quantity_unit = item.variant.quantity_unit
                    elif item.variant.ml:
                        variant_ml = item.variant.ml
                
                item_data.update({
                    'product_id': str(item.product.id),
                    'product_name': item.product.name,
                    'product_image': item.product.image.url if item.product.image else '',
                    'variant_id': str(item.variant.id) if item.variant else None,
                    'variant_ml': variant_ml,  # Legacy support
                    'variant_quantity_value': variant_quantity_value,
                    'variant_quantity_unit': variant_quantity_unit,
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


@require_http_methods(["POST"])
def add_to_cart(request):
    """Add item to cart (guest or user)"""
    try:
        data = json.loads(request.body)
        item_type = data.get('type')  # 'product' or 'combo'
        item_id = data.get('id')
        quantity = int(data.get('quantity', 1))
        variant_id = data.get('variant_id')
        
        if not item_type or not item_id:
            return JsonResponse({'success': False, 'error': 'Type and ID are required'}, status=400)
        parsed_id = parse_uuid(item_id)
        if not parsed_id:
            return JsonResponse({'success': False, 'error': 'Invalid item ID'}, status=400)
        if variant_id is not None and parse_uuid(variant_id) is None:
            return JsonResponse({'success': False, 'error': 'Invalid variant ID'}, status=400)
        
        cart = get_or_create_cart(request)
        if not cart:
            return JsonResponse({'success': False, 'error': 'Unable to get cart. Please refresh and try again.'}, status=400)
        
        with transaction.atomic():
            if item_type == 'product':
                product = get_object_or_404(Product, id=parsed_id, is_active=True)
                if not variant_id:
                    variant = product.default_variant
                    if not variant:
                        return JsonResponse({'success': False, 'error': 'Product variant not found'}, status=404)
                else:
                    variant = get_object_or_404(ProductVariant, id=parse_uuid(variant_id), product=product, is_active=True)
                
                price = variant.price
                
                # Check if item already exists
                # Prepare quantity fields for cart item
                variant_ml = None
                variant_quantity_value = None
                variant_quantity_unit = None
                
                if variant:
                    if variant.quantity_value and variant.quantity_unit:
                        variant_quantity_value = variant.quantity_value
                        variant_quantity_unit = variant.quantity_unit
                    elif variant.ml:
                        variant_ml = variant.ml
                
                cart_item, created = CartItem.objects.get_or_create(
                    cart=cart,
                    item_type='product',
                    product=product,
                    variant=variant,
                    defaults={
                        'quantity': quantity,
                        'price_at_time': price,
                        'variant_ml': variant_ml,  # Legacy support
                        'variant_quantity_value': variant_quantity_value,
                        'variant_quantity_unit': variant_quantity_unit,
                    }
                )
                
                if not created:
                    cart_item.quantity += quantity
                    cart_item.save()
            
            elif item_type == 'combo':
                combo = get_object_or_404(Combo, id=parsed_id, is_active=True)
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


@require_http_methods(["POST"])
def update_cart_item(request, item_id):
    """Update cart item quantity"""
    try:
        parsed_id = parse_uuid(item_id)
        if not parsed_id:
            return JsonResponse({'success': False, 'error': 'Invalid item ID'}, status=400)
        data = json.loads(request.body)
        quantity = int(data.get('quantity', 1))
        
        if quantity < 1:
            return JsonResponse({'success': False, 'error': 'Quantity must be at least 1'}, status=400)
        
        cart = get_or_create_cart(request)
        if not cart:
            return JsonResponse({'success': False, 'error': 'Cart not found'}, status=400)
        cart_item = get_object_or_404(CartItem, id=parsed_id, cart=cart)
        
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


@require_http_methods(["POST"])
def remove_from_cart(request, item_id):
    """Remove item from cart"""
    try:
        parsed_id = parse_uuid(item_id)
        if not parsed_id:
            return JsonResponse({'success': False, 'error': 'Invalid item ID'}, status=400)
        cart = get_or_create_cart(request)
        if not cart:
            return JsonResponse({'success': False, 'error': 'Cart not found'}, status=400)
        cart_item = get_object_or_404(CartItem, id=parsed_id, cart=cart)
        cart_item.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Item removed from cart',
            'total': float(cart.get_total()),
            'item_count': cart.get_item_count()
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["POST"])
def merge_cart(request):
    """Merge session cart to database cart (guest cart)"""
    try:
        session_cart = get_session_cart_from_request(request)
        if not session_cart:
            return JsonResponse({'success': True, 'message': 'No items to merge'})
        
        cart = get_or_create_cart(request)
        if not cart:
            return JsonResponse({'success': False, 'error': 'Unable to get cart'}, status=400)
        
        with transaction.atomic():
            for item in session_cart:
                item_type = item.get('type')
                item_id = item.get('id')
                quantity = int(item.get('quantity', 1))
                variant_id = item.get('variant_id')
                parsed_item_id = parse_uuid(item_id)
                if not parsed_item_id:
                    continue
                
                if item_type == 'product':
                    try:
                        product = Product.objects.get(id=parsed_item_id, is_active=True)
                        if variant_id:
                            parsed_variant_id = parse_uuid(variant_id)
                            variant = ProductVariant.objects.get(id=parsed_variant_id, product=product, is_active=True) if parsed_variant_id else product.default_variant
                        else:
                            variant = product.default_variant
                        
                        if variant:
                            price = variant.price
                            # Prepare quantity fields for cart item
                            variant_ml = None
                            variant_quantity_value = None
                            variant_quantity_unit = None
                            
                            if variant.quantity_value and variant.quantity_unit:
                                variant_quantity_value = variant.quantity_value
                                variant_quantity_unit = variant.quantity_unit
                            elif variant.ml:
                                variant_ml = variant.ml
                            
                            cart_item, created = CartItem.objects.get_or_create(
                                cart=cart,
                                item_type='product',
                                product=product,
                                variant=variant,
                                defaults={
                                    'quantity': quantity,
                                    'price_at_time': price,
                                    'variant_ml': variant_ml,  # Legacy support
                                    'variant_quantity_value': variant_quantity_value,
                                    'variant_quantity_unit': variant_quantity_unit,
                                }
                            )
                            if not created:
                                cart_item.quantity += quantity
                                cart_item.save()
                    except (Product.DoesNotExist, ProductVariant.DoesNotExist):
                        continue
                
                elif item_type == 'combo':
                    try:
                        combo = Combo.objects.get(id=parsed_item_id, is_active=True)
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


# ==================== ORDER TRACKING (no login) ====================

def track_order(request):
    """Track order by order number + phone. No login required."""
    site_config = get_site_config()
    order_number = (request.GET.get('order_number') or request.POST.get('order_number') or '').strip()
    phone = (request.GET.get('phone') or request.POST.get('phone') or '').strip().replace(' ', '')
    
    order = None
    error = None
    if order_number and phone:
        phone_digits = ''.join(c for c in phone if c.isdigit())
        if len(phone_digits) >= 10:
            # Match order_number and phone (compare last 10 digits for flexibility)
            orders = Order.objects.filter(order_number=order_number).prefetch_related('items')
            for o in orders:
                o_phone_digits = ''.join(c for c in (o.phone or '') if c.isdigit())
                if o_phone_digits and o_phone_digits[-10:] == phone_digits[-10:]:
                    order = o
                    break
        if not order:
            error = 'No order found with this order number and phone number. Please check and try again.'
    
    context = {
        'site_config': site_config,
        'order': order,
        'order_number': order_number,
        'phone': phone,
        'error': error,
    }
    return render(request, 'store/track_order.html', context)


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