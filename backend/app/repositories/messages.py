"""Message documents: writing one and reading a chat's history."""

from datetime import datetime, timezone
from typing import Any, Dict, List

from bson import ObjectId

from app.db import db


async def save_message(chat_id: str, role: str, content: str,
                       screenshots: List[Dict[str, Any]] = None,
                       video_url: str = None) -> dict:
    """Save a message to the database."""
    message = {
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "screenshots": screenshots or [],
        "video_url": video_url,
        "timestamp": datetime.now(timezone.utc),
    }
    result = await db.db.messages.insert_one(message)

    update_fields = {"updated_at": datetime.now(timezone.utc)}
    if video_url:
        update_fields["current_video_url"] = video_url

    await db.db.chats.update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": update_fields},
    )

    return {
        "id": str(result.inserted_id),
        "role": role,
        "content": content,
        "screenshots": screenshots or [],
        "video_url": video_url,
        "timestamp": message["timestamp"].isoformat(),
    }


async def owned_message(message_id: str, user_id: str) -> Dict[str, Any] | None:
    """The message, if it belongs to a chat this user owns. Otherwise nothing.

    Callers turn the None into a 404 without saying which of the two it was:
    telling "no such message" apart from "not yours" would let someone probe
    for which message ids exist.

    Shared rather than copied. Two implementations of one access rule is how
    the copy that nobody remembered to update becomes the way in.
    """
    if not ObjectId.is_valid(message_id):
        return None
    message = await db.db.messages.find_one({"_id": ObjectId(message_id)})
    if not message:
        return None

    chat_id = message.get("chat_id", "")
    if not ObjectId.is_valid(chat_id):
        return None
    chat = await db.db.chats.find_one({"_id": ObjectId(chat_id)})
    if not chat or str(chat.get("user_id")) != str(user_id):
        return None
    return message


async def question_before(message: Dict[str, Any]) -> str:
    """The user's question that this answer replies to.

    Falls back to the answer's own opening words when the chat has no question
    before it, which happens for a partially deleted chat.
    """
    asked = await db.db.messages.find_one(
        {"chat_id": message.get("chat_id"), "role": "user",
         "timestamp": {"$lte": message.get("timestamp")}},
        sort=[("timestamp", -1)],
    )
    title = (asked or {}).get("content", "") or message.get("content", "")
    return str(title)[:200]


async def get_chat_messages(chat_id: str) -> list:
    """Get all messages for a chat."""
    cursor = db.db.messages.find({"chat_id": chat_id}).sort("timestamp", 1)
    messages = []
    async for msg in cursor:
        timestamp = msg["timestamp"]
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        messages.append({
            "id": str(msg["_id"]),
            "role": msg["role"],
            "content": msg.get("content", ""),
            "screenshots": msg.get("screenshots", []),
            "video_url": msg.get("video_url"),
            "timestamp": timestamp.isoformat(),
        })
    return messages
