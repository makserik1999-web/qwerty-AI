"""One-time tokens sent by email: confirming an address, resetting a password.

The token itself goes into the link and nowhere else; the database keeps its
sha256, the same way sessions are stored, so a copy of the database is not a
pile of working links. Each token is spent at most once - `consume` marks it
used in the same operation that finds it, so two clicks on one link cannot
both succeed - and expires on its own through a TTL index.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.db import db

VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def issue(kind: str, user_id: str, *, email: str, ttl: timedelta) -> str:
    """A fresh token of this kind; earlier unused ones for the user are void."""
    await db.db.auth_tokens.delete_many({"user_id": user_id, "kind": kind, "used_at": None})
    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    await db.db.auth_tokens.insert_one(
        {
            "token_hash": _hash(raw),
            "kind": kind,
            "user_id": user_id,
            # The address the link was sent to. Confirming it must confirm
            # that address, not whatever the account says by the time the
            # link is opened.
            "email": email,
            "created_at": now,
            "expires_at": now + ttl,
            "used_at": None,
        }
    )
    return raw


async def consume(kind: str, raw: str) -> Optional[Dict[str, Any]]:
    """The token's record if it is valid, marking it used; otherwise None."""
    if not raw or len(raw) > 200:
        return None
    now = datetime.now(timezone.utc)
    return await db.db.auth_tokens.find_one_and_update(
        {"token_hash": _hash(raw), "kind": kind, "used_at": None, "expires_at": {"$gt": now}},
        {"$set": {"used_at": now}},
    )


async def void_all(user_id: str, kind: Optional[str] = None) -> None:
    query: Dict[str, Any] = {"user_id": user_id}
    if kind:
        query["kind"] = kind
    await db.db.auth_tokens.delete_many(query)
