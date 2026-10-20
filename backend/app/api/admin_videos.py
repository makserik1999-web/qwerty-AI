"""The video library in the admin panel: what the topic cache filled, to check.

Watch it, then put it on the showcase, reject it (never served again) or
delete it. Title, topic and grade can be corrected - the classifier will
sometimes file a video under the wrong topic. Support may do all of this;
every change is in the audit log.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import ASSESSMENT_GRADES
from app.db import db
from app.errors import HTTPExceptionJson
from app.repositories import audit
from app.security.staff import require_staff
from app.services import topic_cache

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_staff)])


class Edit(BaseModel):
    title: Optional[str] = None
    topic_id: Optional[str] = None
    grade: Optional[int] = None
    reason: Optional[str] = ""


class Decision(BaseModel):
    reason: Optional[str] = ""


async def _entry(video_id: str) -> Dict[str, Any]:
    entry = await topic_cache.get(video_id)
    if not entry:
        raise HTTPExceptionJson(404, "Not found")
    return entry


def _target(entry):
    return {"video_id": str(entry["_id"]), "topic_id": entry.get("topic_id"), "title": entry.get("title")}


@router.get("/videos")
async def list_videos(status: str = "cached", subject: str = "", silent: bool = False, limit: int = 100):
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if subject:
        query["subject"] = subject
    if silent:
        query["has_audio"] = False
    cursor = db.db.video_cache.find(query).sort("created_at", -1).limit(min(max(limit, 1), 300))
    items = [topic_cache.public_view(e) async for e in cursor]
    counts = {s: await db.db.video_cache.count_documents({"status": s})
              for s in (topic_cache.CACHED, topic_cache.PUBLIC, topic_cache.REJECTED)}
    return {"items": items, "counts": counts}


@router.get("/topics")
async def list_topics():
    """The fixed topic list, for correcting a video's topic."""
    return {"items": list(topic_cache.topics().values())}


async def _forget_everywhere(entry: Dict[str, Any]) -> None:
    """The same file is also kept under the exact wording of the question
    that made it. Rejected or deleted here, it must not keep being served from
    there - which is what happened: deleted from the library, still answered."""
    if entry.get("video_url"):
        await db.db.library_entries.delete_many({"video_url": entry["video_url"]})


async def _set_status(video_id: str, status: str, action: str, actor, reason: str):
    entry = await _entry(video_id)
    if status == topic_cache.REJECTED:
        await _forget_everywhere(entry)
    await db.db.video_cache.update_one({"_id": entry["_id"]}, {"$set": {
        "status": status, "reviewed_at": datetime.now(timezone.utc),
        "reviewed_by": actor.get("email") or str(actor["_id"])}})
    await audit.record(actor=audit.staff_actor(actor), action=action, target=_target(entry),
                       details={"before": entry.get("status")}, reason=reason)
    return topic_cache.public_view(await _entry(video_id))


@router.post("/videos/{video_id}/publish")
async def publish(video_id: str, body: Decision, actor=Depends(require_staff)):
    return await _set_status(video_id, topic_cache.PUBLIC, "video.publish", actor,
                             (body.reason or "").strip() or "Проверено, в витрину")


@router.post("/videos/{video_id}/reject")
async def reject(video_id: str, body: Decision, actor=Depends(require_staff)):
    return await _set_status(video_id, topic_cache.REJECTED, "video.reject", actor,
                             (body.reason or "").strip() or "Отклонено")


@router.post("/videos/{video_id}/delete")
async def delete(video_id: str, body: Decision, actor=Depends(require_staff)):
    """Gone from the library. The file is left to retention: a chat that
    showed this video still links to it."""
    entry = await _entry(video_id)
    await _forget_everywhere(entry)
    await db.db.video_cache.delete_one({"_id": entry["_id"]})
    await db.db.video_ratings.delete_many({"video_id": video_id})
    await audit.record(actor=audit.staff_actor(actor), action="video.delete", target=_target(entry),
                       reason=(body.reason or "").strip() or "Удалено")
    return {"ok": True}


@router.put("/videos/{video_id}")
async def edit(video_id: str, body: Edit, actor=Depends(require_staff)):
    entry = await _entry(video_id)
    changes: Dict[str, Any] = {}
    if body.title is not None:
        title = " ".join(body.title.split())[:200]
        if not title:
            raise HTTPExceptionJson(400, "Title cannot be empty")
        changes["title"] = title
    if body.topic_id is not None:
        topic = topic_cache.topics().get(body.topic_id)
        if not topic:
            raise HTTPExceptionJson(400, "Unknown topic")
        changes.update({"topic_id": body.topic_id, "subject": topic["subject"], "grade": topic["grade"]})
    if body.grade is not None:
        if body.grade not in ASSESSMENT_GRADES and body.grade not in (5, 6):
            raise HTTPExceptionJson(400, "Unknown grade")
        changes["grade"] = body.grade
    if not changes:
        raise HTTPExceptionJson(400, "Nothing to change")
    await db.db.video_cache.update_one({"_id": ObjectId(video_id)}, {"$set": changes})
    await audit.record(actor=audit.staff_actor(actor), action="video.edit", target=_target(entry),
                       details={"before": {k: entry.get(k) for k in changes}, "after": changes},
                       reason=(body.reason or "").strip() or "Исправлено")
    return topic_cache.public_view(await _entry(video_id))
