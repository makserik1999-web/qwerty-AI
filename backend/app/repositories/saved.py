"""A person's own saved explanations.

NOT `library_entries`. That collection, in repositories/library.py, is the
global answer cache: one row serves everyone who asked the same thing, and
deleting one takes an answer away from strangers. This one is private, one row
per person per saved answer, and deleting one affects nobody else. The two
share a word in the interface and nothing else.

Rows here are a SNAPSHOT, not a pointer into the chat. A pointer would be
smaller and would stay in step with an edited message - but it would also mean
that tidying up a chat silently empties somebody's library, and that is not a
trade a person would make knowingly. The video is referenced rather than
copied, because videos are shared and swept on their own schedule: a saved
answer whose file has been collected still reads, it just no longer plays.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.db import db

# Beyond this the grid stops being something a person browses. The interface
# filters on the client, so the whole list is sent - which is only reasonable
# while the list is this size.
MAX_SAVED = 500

TITLE_MAX_LEN = 200


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None


def _public(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "question": doc.get("question", ""),
        "markdown": doc.get("content", ""),
        "videoUrl": doc.get("video_url") or None,
        "subject": doc.get("subject", ""),
        "lang": doc.get("language", ""),
        # When the answer was made, not when it was filed: the card is sorted
        # and dated by the explanation, which is what a person remembers.
        "createdAt": _iso(doc.get("created_at")),
        "savedAt": _iso(doc.get("saved_at")),
        "messageId": doc.get("message_id", ""),
        "chatId": doc.get("chat_id", ""),
    }


async def already_saved(user_id: str, message_id: str) -> Optional[Dict[str, Any]]:
    """Saving the same answer twice is a duplicate card, not a second answer."""
    doc = await db.db.saved_explanations.find_one(
        {"user_id": user_id, "message_id": message_id}
    )
    return _public(doc) if doc else None


async def save(user_id: str, message: Dict[str, Any], question: str,
               subject: str, language: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": user_id,
        "message_id": str(message["_id"]),
        "chat_id": message.get("chat_id", ""),
        "question": question[:TITLE_MAX_LEN],
        "content": message.get("content", ""),
        "video_url": message.get("video_url") or "",
        "subject": subject,
        "language": language,
        "created_at": message.get("timestamp") or now,
        "saved_at": now,
    }
    result = await db.db.saved_explanations.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _public(doc)


async def list_saved(user_id: str) -> List[Dict[str, Any]]:
    cursor = (
        db.db.saved_explanations.find({"user_id": user_id})
        .sort("saved_at", -1)
        .limit(MAX_SAVED)
    )
    return [_public(doc) async for doc in cursor]


async def count_for(user_id: str) -> int:
    return await db.db.saved_explanations.count_documents({"user_id": user_id})


async def rename(saved_id: str, user_id: str, question: str) -> Optional[Dict[str, Any]]:
    """The title only. The explanation itself is what was answered.

    A card people can rename is how a library becomes usable - "инерция, 7
    класс" beats the sentence somebody typed at eleven at night. The body stays
    as the model wrote it, because a saved answer that can be edited is no
    longer a record of what was said.
    """
    if not ObjectId.is_valid(saved_id):
        return None
    doc = await db.db.saved_explanations.find_one_and_update(
        {"_id": ObjectId(saved_id), "user_id": user_id},
        {"$set": {"question": question[:TITLE_MAX_LEN]}},
        return_document=True,
    )
    return _public(doc) if doc else None


async def remove(saved_id: str, user_id: str) -> bool:
    """Removes the card, never the video.

    The file is shared: the same render answers everyone who asked the same
    question. Deleting it here would take an answer away from people who never
    touched this library. Retention collects videos on its own terms.
    """
    if not ObjectId.is_valid(saved_id):
        return False
    result = await db.db.saved_explanations.delete_one(
        {"_id": ObjectId(saved_id), "user_id": user_id}
    )
    return result.deleted_count > 0
