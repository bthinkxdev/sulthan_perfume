"""Custom authentication decorators"""
from functools import wraps
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods


def login_required_json(view_func):
    """
    Decorator that checks if user is authenticated.
    Returns JSON response if not authenticated (for AJAX requests).
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({
                'success': False,
                'error': 'Authentication required',
                'requires_login': True
            }, status=401)
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def login_required_or_redirect(view_func):
    """
    Decorator that redirects to login page if not authenticated.
    For non-AJAX requests, redirects to a login page.
    For AJAX requests, returns JSON with requires_login flag.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': 'Authentication required',
                    'requires_login': True
                }, status=401)
            # For regular page requests, we'll handle via JavaScript modal
            # But we can also create a dedicated login page
            from django.shortcuts import redirect
            return redirect('store:home')  # Will show modal via JS
        return view_func(request, *args, **kwargs)
    return _wrapped_view

