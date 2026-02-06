"""Store app utilities."""
import uuid


def parse_uuid(value):
    """
    Safely parse a string to UUID. Returns the UUID object if valid, None otherwise.
    Use for query params or request body values that should be UUIDs (e.g. category, item_id).
    """
    if value is None or value == '':
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
