"""Authentication utilities for OTP rate limiting"""
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta


def check_otp_rate_limit(email, ip_address=None, limit_minutes=1):
    """
    Check if OTP request is rate limited.
    Returns (is_allowed, remaining_seconds)
    """
    cache_key = f"otp_rate_limit_{email}"
    if ip_address:
        cache_key_ip = f"otp_rate_limit_ip_{ip_address}"
        last_request_ip = cache.get(cache_key_ip)
        if last_request_ip:
            time_passed = (timezone.now() - last_request_ip).total_seconds()
            if time_passed < limit_minutes * 60:
                remaining = int((limit_minutes * 60) - time_passed)
                return False, remaining
    
    last_request = cache.get(cache_key)
    if last_request:
        time_passed = (timezone.now() - last_request).total_seconds()
        if time_passed < limit_minutes * 60:
            remaining = int((limit_minutes * 60) - time_passed)
            return False, remaining
    
    return True, 0


def set_otp_rate_limit(email, ip_address=None, limit_minutes=1):
    """Set rate limit for OTP requests"""
    cache_key = f"otp_rate_limit_{email}"
    cache.set(cache_key, timezone.now(), timeout=limit_minutes * 60)
    
    if ip_address:
        cache_key_ip = f"otp_rate_limit_ip_{ip_address}"
        cache.set(cache_key_ip, timezone.now(), timeout=limit_minutes * 60)


def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

