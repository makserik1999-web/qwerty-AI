"""Who a teacher is - asked of the backend, never decided here.

The backend owns accounts and sessions. Rather than reading its tables, this
service forwards the session cookie to the backend's own `/api/auth/me` and
takes the answer: the account schema can change without this service
noticing, and the day this service gets its own database there is nothing to
untangle.

Answers are reused for IDENTITY_CACHE_SEC, keyed by a hash of the cookie, so
an editor saving every few seconds does not become a backend request every
few seconds. A refusal is reused for much less, so signing in and coming
straight back is not met with a stale "who are you".

`urllib` in a worker thread rather than an HTTP client library: this is one
small request, and the service carries no dependency the backend does not.
"""

import asyncio
import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from fastapi import Request, WebSocket

from quiz_service.config import IDENTITY_CACHE_SEC, IDENTITY_URL, SESSION_COOKIE
from quiz_service.errors import ApiError

User = Dict[str, Any]
Resolver = Callable[[str], Awaitable[Optional[User]]]

_REFUSAL_CACHE_SEC = 3.0
_cache: Dict[str, Tuple[float, Optional[User]]] = {}


class IdentityUnavailable(RuntimeError):
    """The backend could not be asked. Not the same as "not signed in"."""


def _ask_backend(token: str) -> Optional[User]:
    request = urllib.request.Request(
        IDENTITY_URL,
        headers={"Cookie": f"{SESSION_COOKIE}={token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return None
        raise IdentityUnavailable(f"identity answered {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise IdentityUnavailable(f"identity unreachable: {type(exc).__name__}") from exc
    user = body.get("user") if isinstance(body, dict) else None
    return user if isinstance(user, dict) and user.get("id") else None


async def _backend_resolver(token: str) -> Optional[User]:
    return await asyncio.to_thread(_ask_backend, token)


_resolver: Resolver = _backend_resolver


def use_resolver(resolver: Optional[Resolver]) -> None:
    """Swap how a cookie becomes an account. Tests use this; nothing else."""
    global _resolver
    _resolver = resolver or _backend_resolver
    _cache.clear()


async def resolve(token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    user = await _resolver(token)
    ttl = IDENTITY_CACHE_SEC if user else _REFUSAL_CACHE_SEC
    _cache[key] = (time.monotonic() + ttl, user)
    if len(_cache) > 5000:
        for stale in list(_cache)[:2500]:
            _cache.pop(stale, None)
    return user


async def _teacher(token: Optional[str]) -> User:
    try:
        user = await resolve(token)
    except IdentityUnavailable as exc:
        print(f"[identity] {exc}", flush=True)
        raise ApiError(503, "Sign-in could not be checked. Try again shortly.") from exc
    if not user:
        raise ApiError(401, "Not authenticated")
    if user.get("role") != "teacher":
        # 403, as on the backend: a student knows the teacher screens exist.
        raise ApiError(403, "This is available to teacher accounts")
    return user


async def require_teacher(request: Request) -> User:
    return await _teacher(request.cookies.get(SESSION_COOKIE))


async def teacher_for_socket(websocket: WebSocket) -> User:
    return await _teacher(websocket.cookies.get(SESSION_COOKIE))
