# # from django.contrib import admin
# # from .models import Product, Combo, Order, OrderItem, SiteConfig

# # admin.site.register(Product)
# # admin.site.register(Combo)
# # admin.site.register(Order)
# # admin.site.register(OrderItem)
# # admin.site.register(SiteConfig)


# from django.contrib import admin
# from .models import Product, Combo, Order, OrderItem, SiteConfig


# @admin.register(Product)
# class ProductAdmin(admin.ModelAdmin):
#     list_display = ['name', 'origin', 'price', 'is_featured', 'is_active', 'created_at']
#     list_filter = ['origin', 'is_featured', 'is_active']
#     search_fields = ['name', 'short_description']
#     prepopulated_fields = {'slug': ('name',)}
#     list_editable = ['is_featured', 'is_active', 'price']


# @admin.register(Combo)
# class ComboAdmin(admin.ModelAdmin):
#     list_display = ['title', 'discount_percentage', 'is_active', 'is_featured', 'created_at']
#     list_filter = ['is_active', 'is_featured']
#     search_fields = ['title']
#     prepopulated_fields = {'slug': ('title',)}
#     filter_horizontal = ['products']
#     list_editable = ['discount_percentage', 'is_active', 'is_featured']


# class OrderItemInline(admin.TabularInline):
#     model = OrderItem
#     extra = 0
#     readonly_fields = ['item_type', 'product', 'combo', 'quantity', 'price_at_purchase']


# @admin.register(Order)
# class OrderAdmin(admin.ModelAdmin):
#     list_display = ['order_number', 'customer_name', 'phone', 'status', 'total_amount', 'created_at']
#     list_filter = ['status', 'created_at']
#     search_fields = ['order_number', 'customer_name', 'phone']
#     readonly_fields = ['order_number', 'created_at']
#     inlines = [OrderItemInline]
#     list_editable = ['status']
    
#     fieldsets = (
#         ('Order Information', {
#             'fields': ('order_number', 'status', 'total_amount', 'created_at')
#         }),
#         ('Customer Details', {
#             'fields': ('customer_name', 'phone')
#         }),
#         ('Delivery Address', {
#             'fields': ('address_line', 'city', 'pincode')
#         }),
#     )


# @admin.register(SiteConfig)
# class SiteConfigAdmin(admin.ModelAdmin):
#     list_display = ['site_name', 'phone', 'email', 'location']
    
#     def has_add_permission(self, request):
#         # Only allow one site config
#         return not SiteConfig.objects.exists()
    
#     def has_delete_permission(self, request, obj=None):
#         # Don't allow deletion
#         return False