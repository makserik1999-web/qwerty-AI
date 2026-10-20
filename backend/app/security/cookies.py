"""The session cookie: how it is written, cleared and read back."""

from typing import Optional

from fastapi import Request

from app.config import COOKIE_NAME, COOKIE_SECURE


def _session_cookie(token: str, max_age: int) -> str:
    secure = "; Secure" if COOKIE_SECURE else ""
    return (
        f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; "
        f"Max-Age={max_age}{secure}"
    )


def _expired_session_cookie() -> str:
    secure = "; Secure" if COOKIE_SECURE else ""
    return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}"


def _cookie_token(request: Request) -> Optional[str]:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    return raw.strip() or None
