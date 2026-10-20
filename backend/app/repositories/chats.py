"""Chat documents: creation, listing and deletion."""

from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from app.db import db


async def create_chat(user_id: str, title: str = "New Chat") -> dict:
    """Create a new chat for a user."""
    chat = {
        "user_id": user_id,
        "title": title,
        "current_video_url": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.db.chats.insert_one(chat)
    return {
        "id": str(result.inserted_id),
        "user_id": user_id,
        "title": title,
        "current_video_url": None,
        "created_at": chat["created_at"].isoformat(),
        "updated_at": chat["updated_at"].isoformat(),
        "message_count": 0,
    }


async def get_user_chats(user_id: str) -> list:
    """Get all chats for a user with message counts via aggregation (no N+1)."""
    # messages.chat_id is stored as a STRING while chats._id is an ObjectId.
    # Joining them directly compares two different BSON types, which never
    # matches, so message_count came back 0 for every chat. Cast the id to a
    # string first and join on that.
    #
    # This still pulls the matching message documents in order to size the
    # array. That is fine at the current scale; when chats grow long the right
    # fix is a counter denormalised onto the chat document, updated in
    # save_message, rather than a smarter aggregation.
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$addFields": {"_id_str": {"$toString": "$_id"}}},
        {"$lookup": {
            "from": "messages",
            "localField": "_id_str",
            "foreignField": "chat_id",
            "as": "msgs",
        }},
        {"$addFields": {"message_count": {"$size": "$msgs"}}},
        {"$sort": {"updated_at": -1}},
    ]
    chats = []
    async for chat in db.db.chats.aggregate(pipeline):
        chats.append({
            "id": str(chat["_id"]),
            "user_id": chat["user_id"],
            "title": chat["title"],
            "current_video_url": chat.get("current_video_url"),
            "created_at": _iso_or_none(chat.get("created_at")),
            "updated_at": _iso_or_none(chat.get("updated_at")),
            "message_count": chat.get("message_count", 0),
        })
    return chats


def _iso_or_none(value) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


async def delete_chat_by_id(chat_id: str, user_id: str) -> bool:
    """Delete a chat and its messages (ownership-checked)."""
    result = await db.db.chats.delete_one({
        "_id": ObjectId(chat_id),
        "user_id": user_id,
    })
    if result.deleted_count > 0:
        await db.db.messages.delete_many({"chat_id": chat_id})
        return True
    return False
