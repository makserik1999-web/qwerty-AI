"""Confirming an email address, and resetting a forgotten password.

The links in both emails open a page of the interface, which then POSTs the
token here. The link itself does nothing: mail scanners open links to check
them, and a GET that confirmed an address or spent a reset token would be
spent by the scanner before the person ever clicked.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import config
from app.config import _EMAIL_RE, SESSION_TTL_HOURS
from app.db import db
from app.errors import HTTPExceptionJson
from app.models import ForgotPasswordRequest, ResetPasswordRequest, TokenRequest
from app.repositories import auth_tokens
from app.security.cookies import _cookie_token, _session_cookie
from app.security.passwords import _hash_password
from app.security.ratelimit import LoginLimiter, _client_ip, login_limiter
from app.security.sessions import _create_session, _user_from_token, _user_payload
from app.services import mailer

router = APIRouter()

# Sending mail costs the provider's quota and lands in someone's inbox, so it
# is rationed per account and per address as well as per IP.
resend_limiter = LoginLimiter(5, 3600)
forgot_email_limiter = LoginLimiter(3, 3600)
forgot_ip_limiter = LoginLimiter(20, 3600)


def _link(path: str, token: str) -> str:
    return f"{config.PUBLIC_BASE_URL}{path}?token={token}"


async def send_verification(user: Dict[str, Any]) -> None:
    """Issue a confirmation link for the account's current address and mail it."""
    email = user.get("email")
    if not email:
        return
    token = await auth_tokens.issue(
        auth_tokens.VERIFY_EMAIL, str(user["_id"]), email=email,
        ttl=timedelta(hours=config.EMAIL_VERIFY_TTL_HOURS),
    )
    subject, text, html = mailer.verification_message(_link("/verify-email", token))
    mailer.send_later(email, subject, text, html)


@router.post("/api/auth/email/resend")
async def resend_verification(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    if not user.get("email"):
        raise HTTPExceptionJson(400, "Add an email address first", code="no_email")
    if user.get("email_verified_at"):
        return {"ok": True, "already": True}
    if not resend_limiter.allow(f"resend:{user['_id']}"):
        raise HTTPExceptionJson(429, "Too many emails. Try again in an hour.", code="too_many")
    await send_verification(user)
    return {"ok": True}


@router.post("/api/auth/email/verify")
async def verify_email(body: TokenRequest):
    """Confirm the address the link was sent to.

    No session needed: the link is often opened on a phone, signed in nowhere.
    The token is the proof.
    """
    record = await auth_tokens.consume(auth_tokens.VERIFY_EMAIL, body.token)
    if not record:
        raise HTTPExceptionJson(400, "This link has expired or was already used", code="link_invalid")
    user = await db.db.users.find_one({"_id": ObjectId(record["user_id"])})
    if not user:
        raise HTTPExceptionJson(400, "This link has expired or was already used", code="link_invalid")
    if (user.get("email") or "") != record.get("email"):
        # The address changed after the link was sent; confirming it now
        # would vouch for an address nobody opened a link at.
        raise HTTPExceptionJson(400, "This link is for a different address", code="link_stale")
    now = datetime.now(timezone.utc)
    if not user.get("email_verified_at"):
        await db.db.users.update_one({"_id": user["_id"]}, {"$set": {"email_verified_at": now}})
    return {"ok": True, "email": user.get("email")}


@router.post("/api/auth/password/forgot")
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """Mail a reset link if the address has an account.

    The answer is the same either way, so this cannot be used to find out who
    has an account.
    """
    email = (body.email or "").strip().lower()
    if not _EMAIL_RE.fullmatch(email):
        raise HTTPExceptionJson(400, "Invalid email address", code="email_invalid")
    if not forgot_ip_limiter.allow(f"forgot-ip:{_client_ip(request)}") or \
            not forgot_email_limiter.allow(f"forgot:{email}"):
        raise HTTPExceptionJson(429, "Too many requests. Try again in an hour.", code="too_many")

    user = await db.db.users.find_one({"email": email})
    if user:
        token = await auth_tokens.issue(
            auth_tokens.RESET_PASSWORD, str(user["_id"]), email=email,
            ttl=timedelta(minutes=config.PASSWORD_RESET_TTL_MINUTES),
        )
        subject, text, html = mailer.reset_message(
            _link("/reset-password", token), config.PASSWORD_RESET_TTL_MINUTES
        )
        mailer.send_later(email, subject, text, html)
    return {"ok": True}


@router.post("/api/auth/password/reset")
async def reset_password(body: ResetPasswordRequest):
    """Set a new password from a reset link, and sign in with it.

    Every other session of the account ends: if the reset happened because
    someone else knew the old password, they are out. Opening the link also
    proves the person reads that inbox, so the address counts as confirmed.
    """
    if len(body.password or "") < 8:
        raise HTTPExceptionJson(400, "Password must be at least 8 characters", code="password_short")
    record = await auth_tokens.consume(auth_tokens.RESET_PASSWORD, body.token)
    if not record:
        raise HTTPExceptionJson(400, "This link has expired or was already used", code="link_invalid")
    user = await db.db.users.find_one({"_id": ObjectId(record["user_id"])})
    if not user or (user.get("email") or "") != record.get("email"):
        raise HTTPExceptionJson(400, "This link has expired or was already used", code="link_invalid")

    user_id = str(user["_id"])
    changes: Dict[str, Any] = {"password_hash": _hash_password(body.password)}
    if not user.get("email_verified_at"):
        changes["email_verified_at"] = datetime.now(timezone.utc)
    await db.db.users.update_one({"_id": user["_id"]}, {"$set": changes})
    await db.db.sessions.delete_many({"user_id": user_id})
    await auth_tokens.void_all(user_id, auth_tokens.RESET_PASSWORD)
    login_limiter.reset(f"user:{record.get('email')}")

    token = await _create_session(user_id)
    response = JSONResponse({"user": _user_payload({**user, **changes})})
    response.headers["Set-Cookie"] = _session_cookie(token, SESSION_TTL_HOURS * 3600)
    return response
