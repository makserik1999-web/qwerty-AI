"""A teacher's invite link, and what it has earned."""

from fastapi import APIRouter, Depends, Request

from app.errors import HTTPExceptionJson
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token
from app.security.staff import require_staff
from app.services import referrals

router = APIRouter()


@router.get("/api/referrals")
async def mine(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    if user.get("role") != "teacher":
        raise HTTPExceptionJson(403, "Invites are for teacher accounts", code="teacher_only")
    return await referrals.summary(user)


admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_staff)])


@admin_router.get("/referrals")
async def staff_view():
    """Who invited whom, and the accounts that share a device or a network."""
    return {"pairs": await referrals.pairs_for_staff(),
            "crowded": await referrals.crowded_fingerprints()}
