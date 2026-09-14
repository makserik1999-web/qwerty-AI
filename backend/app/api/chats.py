"""Listing a user's chats and reading one chat's history."""

from bson import ObjectId
from fastapi import APIRouter, Request

from app.db import db
from app.errors import HTTPExceptionJson
from app.repositories.chats import _iso_or_none, delete_chat_by_id, get_user_chats
from app.repositories.messages import get_chat_messages
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token
from app.validators import _validate_chat_id

router = APIRouter()


# ---------- Chats (identity from session) ----------
@router.get("/api/chats")
async def list_user_chats(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    chats = await get_user_chats(str(user["_id"]))
    return {"items": chats}


@router.get("/api/chats/{chat_id}")
async def get_chat_history(chat_id: str, request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    if not _validate_chat_id(chat_id):
        raise HTTPExceptionJson(400, "Invalid chat_id")

    chat = await db.db.chats.find_one({"_id": ObjectId(chat_id), "user_id": str(user["_id"])})
    if not chat:
        raise HTTPExceptionJson(404, "Chat not found")

    messages = await get_chat_messages(chat_id)
    return {
        "id": chat_id,
        "user_id": str(user["_id"]),
        "title": chat["title"],
        "current_video_url": chat.get("current_video_url"),
        "created_at": _iso_or_none(chat.get("created_at")),
        "updated_at": _iso_or_none(chat.get("updated_at")),
        "message_count": len(messages),
        "messages": messages,
    }


@router.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str, request: Request):
    """Remove one chat and its messages.

    The same operation the `delete_chat` socket frame has always offered, over
    the route the history is actually read on: the list comes from GET
    /api/chats, so the entry a person wants gone is addressed here rather than
    through a connection that may not be open.

    Ownership is checked in the delete itself - the id is matched together with
    the user, so somebody else's chat is not found rather than removed. A chat
    that is not there returns 404 instead of pretending to have deleted it.
    """
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    if not _validate_chat_id(chat_id):
        raise HTTPExceptionJson(400, "Invalid chat_id")

    deleted = await delete_chat_by_id(chat_id, str(user["_id"]))
    if not deleted:
        raise HTTPExceptionJson(404, "Chat not found")
    return {"id": chat_id, "deleted": True}
