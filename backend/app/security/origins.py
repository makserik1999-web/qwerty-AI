"""Origin allowlist for the UI WebSocket upgrade."""

from typing import Optional

from app.config import CORS_ORIGINS


def _is_allowed_origin(origin: Optional[str]) -> bool:
    """UI WebSocket origin check (CORS does not apply to WS upgrades)."""
    if not origin:
        # Non-browser clients (tests) - allow. Browsers always send Origin.
        return True
    return origin in CORS_ORIGINS
