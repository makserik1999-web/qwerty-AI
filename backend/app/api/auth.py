"""Signup, login, logout, the current-user probe, and the account itself."""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import (
    _EMAIL_RE,
    _USERNAME_RE,
    NAME_MAX_LEN,
    SESSION_TTL_HOURS,
    SIGNUP_MAX_PER_HOUR,
    USER_ROLE_DEFAULT,
    USER_ROLES,
)
from app.db import db
from app.errors import HTTPExceptionJson
from app.models import LoginRequest, ProfileRequest, SignupRequest
from app.security.cookies import _cookie_token, _expired_session_cookie, _session_cookie
from app.security.passwords import _hash_password, _verify_password
from app.security.ratelimit import _client_ip, login_ip_limiter, login_limiter, signup_limiter
from app.security.sessions import _create_session, _hash_token, _user_from_token, _user_payload

router = APIRouter()

_NOT_USERNAME_CHARS = re.compile(r"[^A-Za-z0-9_]+")


async def _derive_username(email: str) -> str:
    """Invent a handle for someone who was never asked for one.

    The interface collects a name, an email and a role. Usernames stay because
    everything else is keyed on them, so one is built from the email's local
    part: "aisulu.b@school.kz" becomes "aisulu_b". The result has to satisfy
    _USERNAME_RE, which is stricter than an email local part in every
    direction - hence the substitution, the padding and the fallback for a
    local part with no usable characters at all.

    Collisions are resolved by counting up rather than by a random suffix: two
    people called aisulu should be aisulu and aisulu2, not aisulu and
    aisulu_7f3a91. The loop is bounded because an unbounded one here is a way
    to hold a request open forever.
    """
    stem = _NOT_USERNAME_CHARS.sub("_", email.split("@")[0]).strip("_")
    stem = stem[:24]

    # A Kazakh or Russian address loses every letter to the substitution above
    # and can leave nothing but the digits, which passes _USERNAME_RE and then
    # reads as a database id rather than as a person. Anything without a
    # letter in it gets the prefix instead: "айсұлу.б70390" becomes
    # "user70390", which at least looks like a handle nobody chose.
    if not any(c.isascii() and c.isalpha() for c in stem):
        stem = f"user{stem}"[:24]
    if len(stem) < 3:
        stem = f"{stem}_user"[:24]

    for attempt in range(200):
        candidate = stem if attempt == 0 else f"{stem}{attempt + 1}"
        if not _USERNAME_RE.fullmatch(candidate):
            break
        if not await db.db.users.find_one({"username": candidate}, {"_id": 1}):
            return candidate

    # Nothing sensible was free. Falling back to a random handle beats
    # refusing the signup: the person never chose this name and cannot fix it.
    from uuid import uuid4

    return f"user_{uuid4().hex[:12]}"


def _clean_name(raw: str | None, fallback: str) -> str:
    name = " ".join((raw or "").split())
    if not name:
        return fallback
    return name[:NAME_MAX_LEN]


def _clean_role(raw: str | None) -> str:
    """Anything we do not recognise becomes a student.

    The role arrives from the client and decides what the interface offers, so
    it is validated the way the narration voice is: against a closed set, with
    the fallback pointing at the lesser privilege.
    """
    role = (raw or "").strip().lower()
    return role if role in USER_ROLES else USER_ROLE_DEFAULT


@router.post("/api/auth/signup")
async def signup(body: SignupRequest, request: Request):
    # Checked before anything else: an open signup endpoint is how a bounded
    # per-user quota gets turned into an unbounded one.
    if not signup_limiter.allow(f"signup:{_client_ip(request)}"):
        raise HTTPExceptionJson(
            429, f"Too many accounts created from here. Try again in an hour "
                 f"(limit {SIGNUP_MAX_PER_HOUR} per hour)."
        )

    username = (body.username or "").strip()
    # Lowercased before it is checked for duplicates or stored, so that one
    # address is one account. Typing it back with a capital on the sign-in
    # screen is not a different person, and the unique index cannot know that
    # by itself - it compares bytes.
    email = (body.email or "").strip().lower() or None
    password = body.password or ""

    if not username and not email:
        raise HTTPExceptionJson(400, "Email is required")
    if email and not _EMAIL_RE.fullmatch(email):
        raise HTTPExceptionJson(400, "Invalid email address")
    if len(password) < 8:
        raise HTTPExceptionJson(400, "Password must be at least 8 characters")

    # Checked before deriving one, so a client that does send a username still
    # gets told when it is malformed instead of having it silently replaced.
    if username and not _USERNAME_RE.fullmatch(username):
        raise HTTPExceptionJson(400, "Username must be 3-30 chars: letters, digits, underscore")
    if not username:
        username = await _derive_username(email)

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
            "name": _clean_name(body.name, username),
            # Self-declared, and that is the whole of it for now: nothing here
            # checks that a teacher teaches. What matters is that from this
            # point the value lives on the server - every later request reads
            # the account, never the client's word for what it is.
            "role": _clean_role(body.role),
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
    email = (body.email or "").strip()
    password = body.password or ""
    ip = _client_ip(request)

    # Whichever one was sent is what the per-account budget is spent against.
    # An address is looked up case-insensitively below, so its key is lowered
    # too: otherwise every capitalisation of one address was a budget of its
    # own, and five guesses became five per spelling.
    identifier = email.lower() if email else username
    ip_key = f"ip:{ip}"
    if login_ip_limiter.blocked(ip_key) or not login_limiter.allow(f"user:{identifier}"):
        raise HTTPExceptionJson(429, "Too many login attempts. Try again later.")

    if email:
        # Stored lowercase since roles landed, so that is the first lookup.
        # The second covers accounts written before that, whose address was
        # kept exactly as typed - without it those people could not sign in.
        user = await db.db.users.find_one({"email": email.lower()})
        if not user and email != email.lower():
            user = await db.db.users.find_one({"email": email})
    else:
        user = await db.db.users.find_one({"username": username})

    if not user or not _verify_password(password, user.get("password_hash", "")):
        login_ip_limiter.hit(ip_key)
        raise HTTPExceptionJson(401, "Invalid username or password")

    token = await _create_session(str(user["_id"]))
    # The account's budget only, never the address's: clearing that one on
    # success let anybody with an account wipe it between guesses at others.
    login_limiter.reset(f"user:{identifier}")

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


@router.patch("/api/auth/profile")
async def update_profile(body: ProfileRequest, request: Request):
    """Change the display name, the email, or both.

    Deliberately cannot change the role. The settings screen shows it as a
    badge rather than a control, and an endpoint that accepted it would be a
    way to become a teacher by sending one field - the interface not offering
    it is not a defence. Changing someone's role is an operation for whoever
    runs the service, and it has no route yet because nothing needs one.

    The username is not editable either: chats, sessions and the admin
    allowlist are keyed on it.
    """
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")

    changes: dict = {}

    if body.name is not None:
        name = _clean_name(body.name, "")
        if not name:
            raise HTTPExceptionJson(400, "Name cannot be empty")
        changes["name"] = name

    if body.email is not None:
        email = body.email.strip().lower()
        if not email:
            raise HTTPExceptionJson(400, "Email cannot be empty")
        if not _EMAIL_RE.fullmatch(email):
            raise HTTPExceptionJson(400, "Invalid email address")
        if email != user.get("email"):
            taken = await db.db.users.find_one(
                {"email": email, "_id": {"$ne": user["_id"]}}, {"_id": 1}
            )
            if taken:
                raise HTTPExceptionJson(409, "Email already registered")
            changes["email"] = email

    if changes:
        await db.db.users.update_one({"_id": user["_id"]}, {"$set": changes})
        user = {**user, **changes}

    return {"user": _user_payload(user)}


@router.delete("/api/auth/account")
async def delete_account(request: Request):
    """Remove the account and everything that belongs to it.

    Sessions go first: while any of them survives, the cookie in someone's
    browser still resolves to a user id, and every request made with it would
    read half-deleted data. Killing them turns the account off before it
    starts coming apart.

    Rendered videos are deliberately left where they are. They are shared -
    the answer library serves one file to everyone who asked the same thing -
    so deleting the files this person happened to ask for first would take
    answers away from other people. Retention collects them on its own
    schedule once nothing references them.

    Everything else keyed on the account goes: the papers and lesson plans a
    teacher wrote and the answers somebody saved. Those collections arrived
    after this route did and were never added to it, so a deleted account's
    documents stayed in the database for good, with nobody left who could
    see or remove them. Export jobs and quota events are left to their own
    expiry, which is hours, not never.
    """
    token = _cookie_token(request)
    user = await _user_from_token(token)
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")

    user_id = str(user["_id"])
    await db.db.sessions.delete_many({"user_id": user_id})

    chat_ids = [str(chat["_id"]) async for chat in db.db.chats.find({"user_id": user_id}, {"_id": 1})]
    if chat_ids:
        await db.db.messages.delete_many({"chat_id": {"$in": chat_ids}})
    await db.db.chats.delete_many({"user_id": user_id})
    await db.db.assessments.delete_many({"user_id": user_id})
    await db.db.lesson_plans.delete_many({"user_id": user_id})
    await db.db.saved_explanations.delete_many({"user_id": user_id})
    await db.db.users.delete_one({"_id": user["_id"]})

    response = JSONResponse({"ok": True})
    response.headers["Set-Cookie"] = _expired_session_cookie()
    return response
