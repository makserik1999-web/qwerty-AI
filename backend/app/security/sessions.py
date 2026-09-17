"""Session tokens: creation, lookup and the user payload they resolve to."""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId

from app.config import SESSION_TTL, USER_ROLE_DEFAULT
from app.db import db


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_session_token() -> str:
    return secrets.token_urlsafe(48)


def _user_payload(user: Dict[str, Any]) -> Dict[str, Any]:
    """What the client is told about itself.

    `role` is read here and nowhere else on the way out, so the interface can
    only learn a role that is stored on the account. Accounts created before
    roles existed have no field, and they read as students - the same fallback
    the signup path uses, and the safe direction to be wrong in.
    """
    return {
        "id": str(user["_id"]),
        "username": user.get("username", ""),
        "email": user.get("email"),
        "name": user.get("name") or user.get("username", ""),
        "role": user.get("role") or USER_ROLE_DEFAULT,
        "created_at": user.get("created_at").isoformat()
        if isinstance(user.get("created_at"), datetime)
        else None,
    }


async def _create_session(user_id: str) -> str:
    token = _new_session_token()
    now = datetime.now(timezone.utc)
    await db.db.sessions.insert_one(
        {
            "token_hash": _hash_token(token),
            "user_id": user_id,
            "created_at": now,
            "expires_at": now + SESSION_TTL,
        }
    )
    return token


async def _user_from_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    session = await db.db.sessions.find_one({"token_hash": _hash_token(token)})
    if not session:
        return None
    # Safety net for the TTL index (which can lag by up to 60s)
    expires_at = session.get("expires_at")
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < datetime.now(timezone.utc):
        await db.db.sessions.delete_one({"_id": session["_id"]})
        return None
    return await db.db.users.find_one({"_id": ObjectId(session["user_id"])})
