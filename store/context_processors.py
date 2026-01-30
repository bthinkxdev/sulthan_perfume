from .models import Category

def categories(request):
    """Make categories available in all templates"""
    return {
        'global_categories': Category.objects.filter(is_active=True).prefetch_related('products')
    }
