"""Cache statistics.

Gated behind an explicit allowlist rather than plain authentication: the top
questions are other people's questions, so any signed-up account must not be
able to read them.
"""

from fastapi import APIRouter, Request

from app.config import ADMIN_USERS
from app.errors import HTTPExceptionJson
from app.repositories.library import cache_stats
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token

router = APIRouter()


@router.get("/api/admin/cache/stats")
async def cache_statistics(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    if user.get("username") not in ADMIN_USERS:
        # 404, not 403: an endpoint you may not use should not confirm it exists.
        raise HTTPExceptionJson(404, "Not found")
    return await cache_stats()
