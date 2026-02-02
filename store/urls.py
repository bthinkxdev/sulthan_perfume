from django.urls import path
from . import views

app_name = 'store'

urlpatterns = [
    # Public pages
    path('', views.home, name='home'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
    path('combo/<slug:slug>/', views.combo_detail, name='combo_detail'),
    path('order/<str:order_number>/', views.order_confirmation, name='order_confirmation'),
    
    # Authentication
    path('auth/send-otp/', views.send_otp, name='send_otp'),
    path('auth/verify-otp/', views.verify_otp, name='verify_otp'),
    path('auth/logout/', views.logout_view, name='logout'),
    
    # Cart (requires authentication)
    path('cart/', views.cart, name='cart'),
    path('api/cart/', views.cart_api, name='cart_api'),
    path('api/cart/merge/', views.merge_cart, name='merge_cart'),
    path('api/cart/item/<uuid:item_id>/update/', views.update_cart_item, name='update_cart_item'),
    path('api/cart/item/<uuid:item_id>/remove/', views.remove_from_cart, name='remove_from_cart'),
    
    # Checkout (requires authentication)
    path('checkout/', views.checkout, name='checkout'),
    path('api/create-razorpay-order/', views.create_razorpay_order, name='create_razorpay_order'),
    path('api/create-cod-order/', views.create_cod_order, name='create_cod_order'),
    path('api/verify-payment/', views.verify_payment, name='verify_payment'),
    path('api/payment-failed/', views.payment_failed, name='payment_failed'),
    path('api/razorpay-webhook/', views.razorpay_webhook, name='razorpay_webhook'),
    
    # Account management (requires authentication)
    path('account/orders/', views.my_orders, name='my_orders'),
    path('account/order/<str:order_number>/', views.order_detail, name='order_detail'),
    path('account/addresses/', views.my_addresses, name='my_addresses'),
    path('api/address/add/', views.add_address, name='add_address'),
    path('api/address/<uuid:address_id>/update/', views.update_address, name='update_address'),
    path('api/address/<uuid:address_id>/delete/', views.delete_address, name='delete_address'),
    path('account/profile/', views.my_profile, name='my_profile'),
    path('api/profile/update/', views.update_profile, name='update_profile'),
    
    # Legal & Information pages
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('cancellations-refunds/', views.cancellations_refunds, name='cancellations_refunds'),
    path('terms-conditions/', views.terms_conditions, name='terms_conditions'),
    path('contact-us/', views.contact_us, name='contact_us'),
]