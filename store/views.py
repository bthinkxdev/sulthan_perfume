from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from .models import Product, Combo, Order, OrderItem, SiteConfig, ProductVariant
import json


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
    
    context = {
        'featured_product': featured_product,
        'products': products,
        'combos': combos,
        'site_config': site_config,
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


def cart(request):
    """Cart page"""
    site_config = get_site_config()
    context = {
        'site_config': site_config,
    }
    return render(request, 'store/cart.html', context)


def checkout(request):
    """Checkout page"""
    site_config = get_site_config()
    context = {
        'site_config': site_config,
    }
    return render(request, 'store/checkout.html', context)


@require_http_methods(["POST"])
def place_order(request):
    """Handle order placement"""
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        required_fields = ['customer_name', 'phone', 'address_line', 'city', 'pincode', 'cart_items']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'success': False, 'error': f'{field} is required'}, status=400)
        
        cart_items = data.get('cart_items', [])
        if not cart_items:
            return JsonResponse({'success': False, 'error': 'Cart is empty'}, status=400)
        
        # Calculate total
        total_amount = 0
        order_items_data = []
        
        for item in cart_items:
            if item['type'] == 'product':
                product = Product.objects.get(id=item['id'])
                variant_id = item.get('variant_id')
                if not variant_id:
                    return JsonResponse({'success': False, 'error': 'Variant is required for product'}, status=400)

                variant = ProductVariant.objects.get(id=variant_id, product=product)
                price = variant.price
                order_items_data.append({
                    'type': 'product',
                    'product': product,
                    'variant': variant,
                    'quantity': item['quantity'],
                    'price': price
                })
            elif item['type'] == 'combo':
                combo = Combo.objects.get(id=item['id'])
                price = combo.discounted_price()
                order_items_data.append({
                    'type': 'combo',
                    'combo': combo,
                    'quantity': item['quantity'],
                    'price': price
                })
            
            total_amount += price * item['quantity']
        
        # Create order
        order = Order.objects.create(
            customer_name=data['customer_name'],
            phone=data['phone'],
            address_line=data['address_line'],
            city=data['city'],
            pincode=data['pincode'],
            total_amount=total_amount
        )
        
        # Create order items
        for item_data in order_items_data:
            OrderItem.objects.create(
                order=order,
                item_type=item_data['type'],
                product=item_data.get('product'),
                combo=item_data.get('combo'),
                variant=item_data.get('variant'),
                variant_ml=getattr(item_data.get('variant'), 'ml', None),
                quantity=item_data['quantity'],
                price_at_purchase=item_data['price']
            )
        
        return JsonResponse({
            'success': True,
            'order_number': order.order_number,
            'order_id': str(order.id)
        })
        
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)
    except ProductVariant.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product variant not found'}, status=404)
    except Combo.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Combo not found'}, status=404)
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