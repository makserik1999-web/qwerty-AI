"""Who among the staff did what, to whom, and when.

There are three of you with access. Without this, in a month nobody will
remember why a teacher has half a year of free subscription.

Append-only from the application: there is no route that edits or deletes an
entry. Grants made from the server command are recorded too, with the actor
marked as the server, since a shell user is not an account.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db import db


def staff_actor(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "staff",
        "user_id": str(user["_id"]),
        "email": user.get("email") or "",
        "role": user.get("staff_role") or "",
    }


CLI_ACTOR = {"kind": "server", "user_id": "", "email": "", "role": ""}


def user_target(user: Dict[str, Any]) -> Dict[str, Any]:
    return {"user_id": str(user["_id"]), "email": user.get("email") or ""}


async def record(
    *,
    actor: Dict[str, Any],
    action: str,
    target: Optional[Dict[str, Any]] = None,
    details: Optional[Dict[str, Any]] = None,
    reason: str = "",
) -> None:
    await db.db.admin_audit.insert_one(
        {
            "at": datetime.now(timezone.utc),
            "actor": actor,
            "action": action,
            "target": target or {},
            "details": details or {},
            "reason": reason[:500],
        }
    )


def _row(doc: Dict[str, Any]) -> Dict[str, Any]:
    at = doc.get("at")
    return {
        "id": str(doc["_id"]),
        "at": at.isoformat() if isinstance(at, datetime) else None,
        "actor": doc.get("actor") or {},
        "action": doc.get("action") or "",
        "target": doc.get("target") or {},
        "details": doc.get("details") or {},
        "reason": doc.get("reason") or "",
    }


async def list_entries(skip: int = 0, limit: int = 50) -> List[Dict[str, Any]]:
    cursor = db.db.admin_audit.find().sort("at", -1).skip(skip).limit(limit)
    return [_row(doc) async for doc in cursor]
