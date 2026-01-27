from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from .models import Product, Combo, Order, OrderItem, SiteConfig, ProductVariant, User, OTP, Address, Cart, CartItem
from .auth_utils import check_otp_rate_limit, set_otp_rate_limit, get_client_ip
import json
from datetime import timedelta


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


def home(request):
    """Landing page with products and combos"""
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
        'site_config': site_config,
        'show_login_modal': show_login_modal,
        'next_url': request.GET.get('next', '/'),
    }
    return render(request, 'store/home.html', context)


def product_detail(request, slug):
    """Product detail page"""
    product = get_object_or_404(
        Product.objects.prefetch_related('variants'),
        slug=slug,
        is_active=True
    )
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
    cart_obj = get_or_create_cart(request.user)
    
    if not cart_obj or cart_obj.items.count() == 0:
        messages.warning(request, 'Your cart is empty')
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
def place_order(request):
    """Handle order placement - uses DB cart"""
    try:
        data = json.loads(request.body)
        
        # Get user's active cart
        cart = get_or_create_cart(request.user)
        if not cart or cart.items.count() == 0:
            return JsonResponse({'success': False, 'error': 'Cart is empty'}, status=400)
        
        # Validate required fields
        required_fields = ['customer_name', 'phone', 'address_line', 'city', 'pincode']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'success': False, 'error': f'{field} is required'}, status=400)
        
        # Calculate total from cart items
        total_amount = cart.get_total()
        
        # Create order
        with transaction.atomic():
            order = Order.objects.create(
                user=request.user,
                cart=cart,
                customer_name=data['customer_name'],
                phone=data['phone'],
                address_line=data['address_line'],
                city=data['city'],
                pincode=data['pincode'],
                total_amount=total_amount,
                payment_status='pending'
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
            
            # Mark cart as checked out
            cart.status = 'checked_out'
            cart.save()
        
        return JsonResponse({
            'success': True,
            'order_number': order.order_number,
            'order_id': str(order.id)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


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
        
        # Get or create user
        user, created = User.objects.get_or_create(
            email=email,
            defaults={'name': email.split('@')[0]}
        )
        
        # Login user
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        
        # Note: Cart merging will be handled by frontend via merge_cart API
        
        return JsonResponse({
            'success': True,
            'message': 'Login successful',
            'next': next_url,
            'user': {
                'email': user.email,
                'name': user.name or user.email.split('@')[0]
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
        
        required_fields = ['name', 'phone', 'address_line', 'city', 'pincode']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'success': False, 'error': f'{field} is required'}, status=400)
        
        address = Address.objects.create(
            user=request.user,
            name=data['name'],
            phone=data['phone'],
            address_line=data['address_line'],
            city=data['city'],
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
        user.name = data.get('name', user.name)
        user.phone = data.get('phone', user.phone)
        user.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Profile updated successfully',
            'user': {
                'email': user.email,
                'name': user.name,
                'phone': user.phone
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