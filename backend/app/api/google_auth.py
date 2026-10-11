"""Sign in with Google (OpenID Connect, authorization code flow with PKCE).

    /api/auth/google/start     -> 302 to Google
    /api/auth/google/callback  -> 302 back into the app, signed in

The state, nonce and PKCE verifier live in the database for ten minutes; the
browser holds only the state, in a cookie scoped to these two paths. The
callback accepts a state only if it matches that cookie - that is what stops
someone else's half-finished sign-in being completed in your browser.

The id_token is not signature-checked, and that is the documented rule rather
than a shortcut: it is read from Google's token endpoint over TLS in exchange
for the code, never from the browser (OpenID Connect Core 3.1.3.7). Issuer,
audience, expiry and nonce are still checked.

Accounts are matched by Google's subject id first, then by email. Linking to
an existing account by email follows one rule: if that account never
confirmed its address, whoever created it may not be its owner - someone can
register your address before you do and wait. So linking then clears the
password and ends its sessions, and the Google owner of the address gets the
account clean.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app import config
from app.api.auth import _clean_name, _clean_role, _derive_username
from app.config import COOKIE_SECURE, SESSION_TTL_HOURS
from app.db import db
from app.errors import HTTPExceptionJson
from app.security.cookies import _session_cookie
from app.security.fingerprint import trace_update
from app.security.ratelimit import _client_ip, signup_limiter
from app.security.sessions import _create_session

router = APIRouter()

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
STATE_COOKIE = "anyq_oauth_state"
STATE_TTL = timedelta(minutes=10)
CALLBACK_PATH = "/api/auth/google/callback"


def google_configured() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def _redirect_uri() -> str:
    return f"{config.PUBLIC_BASE_URL}{CALLBACK_PATH}"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _state_cookie(value: str, max_age: int) -> str:
    secure = "; Secure" if COOKIE_SECURE else ""
    return (f"{STATE_COOKIE}={value}; Path=/api/auth/google; HttpOnly; SameSite=Lax; "
            f"Max-Age={max_age}{secure}")


def _safe_next(value: str) -> str:
    """Only a path on this site; anything else is an open redirect."""
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value[:200]
    return "/app/explain"


def _fail(where: str, reason: str) -> RedirectResponse:
    response = RedirectResponse(f"{where}?auth_error=google_{reason}", status_code=302)
    response.headers.append("Set-Cookie", _state_cookie("", 0))
    return response


@router.get("/api/auth/providers")
async def providers():
    """Which sign-in and confirmation methods this server has set up."""
    from app.services import sms

    return {"google": google_configured(), "phone": sms.configured()}


@router.get("/api/auth/google/start")
async def google_start(role: str = "", next: str = "", ref: str = "", device: str = ""):
    if not google_configured():
        raise HTTPExceptionJson(404, "Google sign-in is not set up")
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    await db.db.oauth_states.insert_one({
        "state_hash": _hash(state),
        "nonce": nonce,
        "verifier": verifier,
        # Only used if this turns out to be a new account: an existing one
        # keeps the role it has.
        "role": role.strip().lower(),
        "next": _safe_next(next) if next else "/app/explain",
        "ref": ref.strip()[:12],
        "device": device.strip()[:200],
        "created_at": now,
        "expires_at": now + STATE_TTL,
    })
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    response = RedirectResponse(f"{AUTH_URL}?{urllib.parse.urlencode(params)}", status_code=302)
    response.headers.append("Set-Cookie", _state_cookie(state, int(STATE_TTL.total_seconds())))
    return response


def _exchange_sync(code: str, verifier: str) -> Dict[str, Any]:
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }).encode("ascii")
    request = urllib.request.Request(TOKEN_URL, data=data, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as reply:  # noqa: S310 - fixed https URL
        return json.loads(reply.read().decode("utf-8"))


async def exchange_code(code: str, verifier: str) -> Dict[str, Any]:
    """Google's token response for this code. Replaced in tests."""
    return await asyncio.to_thread(_exchange_sync, code, verifier)


def id_token_claims(id_token: str) -> Dict[str, Any]:
    parts = (id_token or "").split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))


def check_claims(claims: Dict[str, Any], nonce: str) -> Optional[str]:
    """None if the claims are acceptable, otherwise a short reason."""
    if claims.get("iss") not in ISSUERS:
        return "issuer"
    aud = claims.get("aud")
    if aud != config.GOOGLE_CLIENT_ID and not (isinstance(aud, list) and config.GOOGLE_CLIENT_ID in aud):
        return "audience"
    if float(claims.get("exp") or 0) < time.time() - 60:
        return "expired"
    if not nonce or claims.get("nonce") != nonce:
        return "nonce"
    if not claims.get("sub") or not claims.get("email"):
        return "claims"
    if claims.get("email_verified") not in (True, "true"):
        return "email_unverified"
    return None


@router.get(CALLBACK_PATH)
async def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if not google_configured():
        raise HTTPExceptionJson(404, "Google sign-in is not set up")
    if error:
        return _fail("/signin", "cancelled")
    cookie_state = request.cookies.get(STATE_COOKIE) or ""
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        return _fail("/signin", "state")
    flow = await db.db.oauth_states.find_one_and_delete({"state_hash": _hash(state)})
    expires = flow.get("expires_at") if flow else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not flow or (expires and expires < datetime.now(timezone.utc)):
        return _fail("/signin", "state")
    if not code:
        return _fail("/signin", "failed")

    try:
        tokens = await exchange_code(code, flow["verifier"])
        claims = id_token_claims(tokens.get("id_token", ""))
    except Exception as e:  # noqa: BLE001 - the person gets a message, the log the cause
        print(f"[google] code exchange failed: {type(e).__name__}: {str(e)[:200]}")
        return _fail("/signin", "failed")
    problem = check_claims(claims, flow.get("nonce", ""))
    if problem:
        print(f"[google] id_token rejected: {problem}")
        return _fail("/signin", "failed")

    sub = str(claims["sub"])
    email = str(claims["email"]).strip().lower()
    now = datetime.now(timezone.utc)

    user = await db.db.users.find_one({"google_sub": sub})
    if not user:
        user = await db.db.users.find_one({"email": email})
        if user:
            link: Dict[str, Any] = {"$set": {"google_sub": sub, "email_verified_at": user.get("email_verified_at") or now}}
            if not user.get("email_verified_at"):
                # Nobody proved they own this address until now. Whoever set
                # the password may not be its owner, so the password and every
                # session it opened end here.
                link["$unset"] = {"password_hash": ""}
                await db.db.sessions.delete_many({"user_id": str(user["_id"])})
            await db.db.users.update_one({"_id": user["_id"]}, link)
        else:
            if flow.get("role") not in ("teacher", "student"):
                # Signing in with an account that does not exist: the sign-up
                # page asks who they are first, then comes back here.
                return _fail("/signup", "choose_role")
            if not signup_limiter.allow(f"signup:{_client_ip(request)}"):
                return _fail("/signup", "too_many")
            username = await _derive_username(email)
            doc = {
                "username": username,
                "email": email,
                "name": _clean_name(claims.get("name"), username),
                "role": _clean_role(flow.get("role")),
                "google_sub": sub,
                "email_verified_at": now,
                "created_at": now,
            }
            from app.services.referrals import inviter_for

            inviter = await inviter_for(flow.get("ref"))
            if inviter:
                doc["referred_by"] = str(inviter["_id"])
            try:
                result = await db.db.users.insert_one(doc)
            except Exception:
                return _fail("/signup", "failed")
            user = {**doc, "_id": result.inserted_id}

    if user.get("blocked_at"):
        return _fail("/signin", "blocked")
    trace = trace_update(_client_ip(request), flow.get("device"))
    if trace:
        await db.db.users.update_one({"_id": user["_id"]}, trace)
    token = await _create_session(str(user["_id"]))
    response = RedirectResponse(flow.get("next") or "/app/explain", status_code=302)
    response.headers.append("Set-Cookie", _state_cookie("", 0))
    response.headers.append("Set-Cookie", _session_cookie(token, SESSION_TTL_HOURS * 3600))
    return response
