from django.urls import path
from . import admin_views as views

urlpatterns = [
    # Dashboard
    path('', views.admin_dashboard, name='admin_dashboard'),
    
    # Product URLs
    path('products/', views.product_list, name='admin_product_list'),
    path('products/create/', views.product_create, name='admin_product_create'),
    path('products/<uuid:pk>/', views.product_detail, name='admin_product_detail'),
    path('products/<uuid:pk>/edit/', views.product_edit, name='admin_product_edit'),
    path('products/<uuid:pk>/delete/', views.product_delete, name='admin_product_delete'),
    
    # Variant URLs
    path('products/<uuid:product_pk>/variants/create/', views.variant_create, name='admin_variant_create'),
    path('variants/<uuid:pk>/edit/', views.variant_edit, name='admin_variant_edit'),
    path('variants/<uuid:pk>/delete/', views.variant_delete, name='admin_variant_delete'),
    
    # Combo URLs
    path('combos/', views.combo_list, name='admin_combo_list'),
    path('combos/create/', views.combo_create, name='admin_combo_create'),
    path('combos/<uuid:pk>/', views.combo_detail, name='admin_combo_detail'),
    path('combos/<uuid:pk>/edit/', views.combo_edit, name='admin_combo_edit'),
    path('combos/<uuid:pk>/delete/', views.combo_delete, name='admin_combo_delete'),
    
    # Order URLs
    path('orders/', views.order_list, name='admin_order_list'),
    path('orders/<uuid:pk>/', views.order_detail, name='admin_order_detail'),
    path('orders/<uuid:pk>/delete/', views.order_delete, name='admin_order_delete'),
]