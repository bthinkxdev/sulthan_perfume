from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.core.paginator import Paginator
from .models import Product, ProductVariant, Combo, Order, OrderItem, Category
from .forms import (
    ProductForm,
    ProductVariantForm,
    ProductVariantFormSet,
    ComboForm,
    ComboProductFormSet,
    OrderStatusForm
)


# @staff_member_required
def admin_dashboard(request):
    """Main admin dashboard with statistics"""
    context = {
        'total_products': Product.objects.filter(is_active=True).count(),
        'total_combos': Combo.objects.filter(is_active=True).count(),
        'total_orders': Order.objects.count(),
        'total_categories': Category.objects.filter(is_active=True).count(),
        'new_orders': Order.objects.filter(status='new').count(),
        'processing_orders': Order.objects.filter(status='processing').count(),
        'recent_orders': Order.objects.all()[:5],
        'featured_products': Product.objects.filter(is_featured=True, is_active=True)[:5],
    }
    return render(request, 'admin_dashboard/dashboard.html', context)


# ============= CATEGORY MANAGEMENT =============

# @staff_member_required
def category_list(request):
    """List all categories with search and filter"""
    categories = Category.objects.annotate(
        products_count=Count('products')
    )
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        categories = categories.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        categories = categories.filter(is_active=True)
    elif status_filter == 'inactive':
        categories = categories.filter(is_active=False)
    
    # Pagination
    paginator = Paginator(categories, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
    }
    return render(request, 'admin_dashboard/category_list.html', context)


# @staff_member_required
def category_create(request):
    """Create a new category"""
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        display_order = request.POST.get('display_order', 0)
        is_active = request.POST.get('is_active') == 'on'
        image = request.FILES.get('image')
        
        category = Category(
            name=name,
            description=description,
            display_order=display_order,
            is_active=is_active,
        )
        if image:
            category.image = image
        
        category.save()
        messages.success(request, f'Category "{category.name}" created successfully!')
        return redirect('admin_category_detail', pk=category.pk)
    
    return render(request, 'admin_dashboard/category_form.html', {
        'action': 'Create'
    })


# @staff_member_required
def category_edit(request, pk):
    """Edit an existing category"""
    category = get_object_or_404(Category, pk=pk)
    
    if request.method == 'POST':
        category.name = request.POST.get('name')
        category.description = request.POST.get('description', '')
        category.display_order = request.POST.get('display_order', 0)
        category.is_active = request.POST.get('is_active') == 'on'
        
        image = request.FILES.get('image')
        if image:
            category.image = image
        
        category.save()
        messages.success(request, f'Category "{category.name}" updated successfully!')
        return redirect('admin_category_detail', pk=category.pk)
    
    return render(request, 'admin_dashboard/category_form.html', {
        'category': category,
        'action': 'Edit'
    })


# @staff_member_required
def category_detail(request, pk):
    """View category details with products"""
    category = get_object_or_404(Category, pk=pk)
    products = category.products.all()[:10]
    total_products = category.products.count()
    
    return render(request, 'admin_dashboard/category_detail.html', {
        'category': category,
        'products': products,
        'total_products': total_products,
    })


# @staff_member_required
def category_delete(request, pk):
    """Delete a category"""
    category = get_object_or_404(Category, pk=pk)
    
    if request.method == 'POST':
        category_name = category.name
        category.delete()
        messages.success(request, f'Category "{category_name}" deleted successfully!')
        return redirect('admin_category_list')
    
    return render(request, 'admin_dashboard/category_confirm_delete.html', {
        'category': category
    })


# ============= PRODUCT MANAGEMENT =============

# @staff_member_required
def product_list(request):
    """List all products with search and filter"""
    products = Product.objects.all()
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(short_description__icontains=search_query)
        )
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        products = products.filter(is_active=True)
    elif status_filter == 'inactive':
        products = products.filter(is_active=False)
    elif status_filter == 'featured':
        products = products.filter(is_featured=True)
    
    # Pagination
    paginator = Paginator(products, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
    }
    return render(request, 'admin_dashboard/product_list.html', context)


# @staff_member_required
def product_create(request):
    """Create a new product"""
    base_product = Product()
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=base_product)
        variant_formset = ProductVariantFormSet(
            request.POST,
            prefix='variants',
            instance=base_product
        )
        if form.is_valid() and variant_formset.is_valid():
            with transaction.atomic():
                product = form.save()
                variant_formset.instance = product
                variant_formset.save()
            messages.success(request, f'Product "{product.name}" created successfully!')
            return redirect('admin_product_detail', pk=product.pk)
    else:
        form = ProductForm(instance=base_product)
        variant_formset = ProductVariantFormSet(prefix='variants', instance=base_product)
    
    return render(request, 'admin_dashboard/product_form.html', {
        'form': form,
        'variant_formset': variant_formset,
        'action': 'Create'
    })


# @staff_member_required
def product_edit(request, pk):
    """Edit an existing product"""
    product = get_object_or_404(Product, pk=pk)
    
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        variant_formset = ProductVariantFormSet(
            request.POST,
            prefix='variants',
            instance=product
        )
        if form.is_valid() and variant_formset.is_valid():
            with transaction.atomic():
                product = form.save()
                variant_formset.save()
            messages.success(request, f'Product "{product.name}" updated successfully!')
            return redirect('admin_product_detail', pk=product.pk)
    else:
        form = ProductForm(instance=product)
        variant_formset = ProductVariantFormSet(prefix='variants', instance=product)
    
    return render(request, 'admin_dashboard/product_form.html', {
        'form': form,
        'product': product,
        'variant_formset': variant_formset,
        'action': 'Edit'
    })


# @staff_member_required
def product_detail(request, pk):
    """View product details with variants"""
    product = get_object_or_404(Product, pk=pk)
    variants = product.variants.all()
    
    return render(request, 'admin_dashboard/product_detail.html', {
        'product': product,
        'variants': variants,
    })


# @staff_member_required
def product_delete(request, pk):
    """Delete a product"""
    product = get_object_or_404(Product, pk=pk)
    
    if request.method == 'POST':
        product_name = product.name
        product.delete()
        messages.success(request, f'Product "{product_name}" deleted successfully!')
        return redirect('admin_product_list')
    
    return render(request, 'admin_dashboard/product_confirm_delete.html', {
        'product': product
    })


# ============= VARIANT MANAGEMENT =============

# @staff_member_required
def variant_create(request, product_pk):
    """Create a new variant for a product"""
    product = get_object_or_404(Product, pk=product_pk)
    
    if request.method == 'POST':
        form = ProductVariantForm(request.POST)
        if form.is_valid():
            variant = form.save(commit=False)
            variant.product = product
            variant.save()
            messages.success(request, f'Variant {variant.ml}ml created successfully!')
            return redirect('admin_product_detail', pk=product.pk)
    else:
        form = ProductVariantForm()
    
    return render(request, 'admin_dashboard/variant_form.html', {
        'form': form,
        'product': product,
        'action': 'Create'
    })


# @staff_member_required
def variant_edit(request, pk):
    """Edit a variant"""
    variant = get_object_or_404(ProductVariant, pk=pk)
    
    if request.method == 'POST':
        form = ProductVariantForm(request.POST, instance=variant)
        if form.is_valid():
            variant = form.save()
            messages.success(request, f'Variant {variant.ml}ml updated successfully!')
            return redirect('admin_product_detail', pk=variant.product.pk)
    else:
        form = ProductVariantForm(instance=variant)
    
    return render(request, 'admin_dashboard/variant_form.html', {
        'form': form,
        'variant': variant,
        'product': variant.product,
        'action': 'Edit'
    })


# @staff_member_required
def variant_delete(request, pk):
    """Delete a variant"""
    variant = get_object_or_404(ProductVariant, pk=pk)
    product = variant.product
    
    if request.method == 'POST':
        variant.delete()
        messages.success(request, f'Variant {variant.ml}ml deleted successfully!')
        return redirect('admin_product_detail', pk=product.pk)
    
    return render(request, 'admin_dashboard/variant_confirm_delete.html', {
        'variant': variant
    })


# ============= COMBO MANAGEMENT =============


def _product_variant_map():
    """Build a lightweight mapping of product -> its active variants for the UI."""
    products = Product.objects.filter(is_active=True).prefetch_related('variants')
    mapping = {}

    for product in products:
        mapping[str(product.id)] = [
            {
                'id': str(variant.id),
                'label': f"{variant.ml}ml - ₹{variant.price}"
            }
            for variant in product.variants.filter(is_active=True)
        ]

    return mapping

# @staff_member_required
def combo_list(request):
    """List all combos"""
    combos = Combo.objects.all()
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        combos = combos.filter(title__icontains=search_query)
    
    # Filter
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        combos = combos.filter(is_active=True)
    elif status_filter == 'inactive':
        combos = combos.filter(is_active=False)
    elif status_filter == 'featured':
        combos = combos.filter(is_featured=True)
    
    # Pagination
    paginator = Paginator(combos, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
    }
    return render(request, 'admin_dashboard/combo_list.html', context)


# @staff_member_required
def combo_create(request):
    """Create a new combo"""
    combo = Combo()
    if request.method == 'POST':
        form = ComboForm(request.POST, request.FILES, instance=combo)
        combo_items_formset = ComboProductFormSet(
            request.POST,
            prefix='combo_items',
            instance=combo
        )
        if form.is_valid() and combo_items_formset.is_valid():
            with transaction.atomic():
                combo = form.save()
                combo_items_formset.instance = combo
                combo_items_formset.save()
            messages.success(request, f'Combo "{combo.title}" created successfully!')
            return redirect('admin_combo_detail', pk=combo.pk)
    else:
        form = ComboForm(instance=combo)
        combo_items_formset = ComboProductFormSet(
            prefix='combo_items',
            instance=combo
        )
    
    return render(request, 'admin_dashboard/combo_form.html', {
        'form': form,
        'combo_items_formset': combo_items_formset,
        'product_variant_map': _product_variant_map(),
        'action': 'Create'
    })


# @staff_member_required
def combo_edit(request, pk):
    """Edit a combo"""
    combo = get_object_or_404(Combo, pk=pk)
    
    if request.method == 'POST':
        form = ComboForm(request.POST, request.FILES, instance=combo)
        combo_items_formset = ComboProductFormSet(
            request.POST,
            prefix='combo_items',
            instance=combo
        )
        if form.is_valid() and combo_items_formset.is_valid():
            with transaction.atomic():
                combo = form.save()
                combo_items_formset.save()
            messages.success(request, f'Combo "{combo.title}" updated successfully!')
            return redirect('admin_combo_detail', pk=combo.pk)
    else:
        form = ComboForm(instance=combo)
        combo_items_formset = ComboProductFormSet(
            prefix='combo_items',
            instance=combo
        )
    
    return render(request, 'admin_dashboard/combo_form.html', {
        'form': form,
        'combo': combo,
        'combo_items_formset': combo_items_formset,
        'product_variant_map': _product_variant_map(),
        'action': 'Edit'
    })


# @staff_member_required
def combo_detail(request, pk):
    """View combo details"""
    combo = get_object_or_404(
        Combo.objects.prefetch_related(
            'combo_products__product',
            'combo_products__variant'
        ),
        pk=pk
    )
    combo_products = combo.combo_products.select_related('product', 'variant')
    
    return render(request, 'admin_dashboard/combo_detail.html', {
        'combo': combo,
        'combo_products': combo_products,
    })


# @staff_member_required
def combo_delete(request, pk):
    """Delete a combo"""
    combo = get_object_or_404(Combo, pk=pk)
    
    if request.method == 'POST':
        combo_title = combo.title
        combo.delete()
        messages.success(request, f'Combo "{combo_title}" deleted successfully!')
        return redirect('admin_combo_list')
    
    return render(request, 'admin_dashboard/combo_confirm_delete.html', {
        'combo': combo
    })


# ============= ORDER MANAGEMENT =============

# @staff_member_required
def order_list(request):
    """List all orders"""
    orders = Order.objects.all().order_by('-created_at')
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        orders = orders.filter(
            Q(order_number__icontains=search_query) |
            Q(customer_name__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(razorpay_payment_id__icontains=search_query) |
            Q(razorpay_order_id__icontains=search_query)
        )
    
    # Filter by order status
    status_filter = request.GET.get('status', '')
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    # Filter by payment status
    payment_status_filter = request.GET.get('payment_status', '')
    if payment_status_filter:
        orders = orders.filter(payment_status=payment_status_filter)
    
    # Pagination
    paginator = Paginator(orders, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Payment status choices
    payment_status_choices = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'payment_status_filter': payment_status_filter,
        'status_choices': Order.ORDER_STATUS,
        'payment_status_choices': payment_status_choices,
    }
    return render(request, 'admin_dashboard/order_list.html', context)


# @staff_member_required
def order_detail(request, pk):
    """View order details"""
    order = get_object_or_404(Order, pk=pk)
    items = order.items.all()
    
    # Handle status update
    if request.method == 'POST':
        form = OrderStatusForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            messages.success(request, f'Order {order.order_number} status updated!')
            return redirect('admin_order_detail', pk=order.pk)
    else:
        form = OrderStatusForm(instance=order)
    
    return render(request, 'admin_dashboard/order_detail.html', {
        'order': order,
        'items': items,
        'form': form,
    })


# @staff_member_required
def order_delete(request, pk):
    """Delete an order"""
    order = get_object_or_404(Order, pk=pk)
    
    if request.method == 'POST':
        order_number = order.order_number
        order.delete()
        messages.success(request, f'Order {order_number} deleted successfully!')
        return redirect('admin_order_list')
    
    return render(request, 'admin_dashboard/order_confirm_delete.html', {
        'order': order
    })