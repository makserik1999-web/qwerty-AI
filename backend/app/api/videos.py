"""Topic videos for everyone: 👍/👎 under a video, and the showcase.

The showcase is the videos the team has checked and put on display - what a
free account (students, teachers before a plan) can browse and watch.
"""

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import CONTENT_SUBJECTS
from app.errors import HTTPExceptionJson
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token
from app.services import topic_cache

router = APIRouter()

VOTES = {"up": 1, "down": -1, "none": 0}


class Vote(BaseModel):
    value: str


async def _signed_in(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    return user


@router.post("/api/videos/{video_id}/rate")
async def rate(video_id: str, body: Vote, request: Request):
    user = await _signed_in(request)
    if body.value not in VOTES:
        raise HTTPExceptionJson(400, "value must be up, down or none")
    entry = await topic_cache.get(video_id)
    if not entry or entry.get("status") not in topic_cache.SERVABLE:
        raise HTTPExceptionJson(404, "Not found")
    return await topic_cache.rate(video_id, str(user["_id"]), VOTES[body.value])


@router.get("/api/showcase")
async def showcase(request: Request, subject: str = "", grade: Optional[int] = None, lang: str = ""):
    await _signed_in(request)
    if subject and subject not in CONTENT_SUBJECTS:
        raise HTTPExceptionJson(400, "Unknown subject")
    items = await topic_cache.showcase(subject, grade, lang if lang in ("kk", "ru", "en") else "")
    return {"items": items}
