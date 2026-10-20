"""What is left of this user's generation budget.

A separate endpoint rather than a field on /api/auth/me: the budget changes
while the page is open, and the UI needs to re-read it after every generation
without re-fetching the session.
"""

from fastapi import APIRouter, Request

from app.errors import HTTPExceptionJson
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token
from app.services.quota import usage

router = APIRouter()


@router.get("/api/quota")
async def generation_quota(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    return await usage(str(user["_id"]))
