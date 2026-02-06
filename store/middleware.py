"""Guest session middleware: ensures every request has a guest_id (cookie-based)."""
import uuid
from django.utils.deprecation import MiddlewareMixin

GUEST_COOKIE_NAME = "guest_id"
GUEST_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year in seconds


class GuestSessionMiddleware(MiddlewareMixin):
    """
    Attach a persistent guest_id to the request.
    - Reads guest_id from cookie; if missing, generates a UUID and sets the cookie.
    - request.guest_id is always set (string UUID) for store views to use.
    """
    def process_request(self, request):
        guest_id = request.COOKIES.get(GUEST_COOKIE_NAME)
        if not guest_id or len(guest_id) != 36:
            try:
                uuid.UUID(guest_id)
            except (ValueError, TypeError):
                guest_id = None
        if not guest_id:
            guest_id = str(uuid.uuid4())
            request._guest_id_new = True  # so we can set cookie in response
        request.guest_id = guest_id

    def process_response(self, request, response):
        if getattr(request, "_guest_id_new", False) and getattr(request, "guest_id", None):
            response.set_cookie(
                GUEST_COOKIE_NAME,
                request.guest_id,
                max_age=GUEST_COOKIE_MAX_AGE,
                httponly=True,
                samesite="Lax",
            )
        return response
