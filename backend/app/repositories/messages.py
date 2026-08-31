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
