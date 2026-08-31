"""Signup, login, logout and the current-user probe."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import _EMAIL_RE, _USERNAME_RE, SESSION_TTL_HOURS
from app.db import db
from app.errors import HTTPExceptionJson
from app.models import LoginRequest, SignupRequest
from app.security.cookies import _cookie_token, _expired_session_cookie, _session_cookie
from app.security.passwords import _hash_password, _verify_password
from app.security.ratelimit import _client_ip, login_limiter
from app.security.sessions import _create_session, _hash_token, _user_from_token, _user_payload

router = APIRouter()


@router.post("/api/auth/signup")
async def signup(body: SignupRequest, request: Request):
    username = (body.username or "").strip()
    email = (body.email or "").strip() or None
    password = body.password or ""

    if not _USERNAME_RE.fullmatch(username):
        raise HTTPExceptionJson(400, "Username must be 3-30 chars: letters, digits, underscore")
    if email and not _EMAIL_RE.fullmatch(email):
        raise HTTPExceptionJson(400, "Invalid email address")
    if len(password) < 8:
        raise HTTPExceptionJson(400, "Password must be at least 8 characters")

    # Note: {email: null} in Mongo matches users with NO email field, so the
    # email condition must only be added when an email was actually provided.
    conditions = [{"username": username}]
    if email:
        conditions.append({"email": email})
    existing = await db.db.users.find_one({"$or": conditions})
    if existing:
        if existing.get("username") == username:
            raise HTTPExceptionJson(409, "Username already taken")
        raise HTTPExceptionJson(409, "Email already registered")

    try:
        user = {
            "username": username,
            "password_hash": _hash_password(password),
            "created_at": datetime.now(timezone.utc),
        }
        # Only store email when provided. The sparse unique index on email
        # treats explicit null as a VALUE (not "missing"), so writing
        # email=None here would make every subsequent signup without an email
        # collide with this document (DuplicateKeyError).
        if email:
            user["email"] = email
        result = await db.db.users.insert_one(user)
    except Exception:
        # `from None`: the DuplicateKeyError is deliberately dropped - the
        # client is told "already registered" and never sees Mongo internals.
        raise HTTPExceptionJson(409, "Username or email already registered") from None

    user_id = str(result.inserted_id)
    token = await _create_session(user_id)
    login_limiter.reset(f"user:{username}")

    response = JSONResponse(
        {"user": _user_payload({**user, "_id": result.inserted_id})},
        status_code=201,
    )
    response.headers["Set-Cookie"] = _session_cookie(token, SESSION_TTL_HOURS * 3600)
    return response


@router.post("/api/auth/login")
async def login(body: LoginRequest, request: Request):
    username = (body.username or "").strip()
    password = body.password or ""
    ip = _client_ip(request)

    if not login_limiter.allow(f"ip:{ip}") or not login_limiter.allow(f"user:{username}"):
        raise HTTPExceptionJson(429, "Too many login attempts. Try again later.")

    user = await db.db.users.find_one({"username": username})
    if not user or not _verify_password(password, user.get("password_hash", "")):
        raise HTTPExceptionJson(401, "Invalid username or password")

    token = await _create_session(str(user["_id"]))
    login_limiter.reset(f"user:{username}")
    login_limiter.reset(f"ip:{ip}")

    response = JSONResponse({"user": _user_payload(user)})
    response.headers["Set-Cookie"] = _session_cookie(token, SESSION_TTL_HOURS * 3600)
    return response


@router.post("/api/auth/logout")
async def logout(request: Request):
    token = _cookie_token(request)
    if token:
        await db.db.sessions.delete_many({"token_hash": _hash_token(token)})
    response = JSONResponse({"ok": True})
    response.headers["Set-Cookie"] = _expired_session_cookie()
    return response


@router.get("/api/auth/me")
async def me(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    return {"user": _user_payload(user)}
