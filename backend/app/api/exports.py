"""Queueing exports and handing back the finished file.

The backend never encodes anything: ffmpeg would block the event loop for the
length of the encode, and every other request with it. It validates, writes a
job, and serves the result. The work happens in the `exporter` service.

Two access rules, both enforced here rather than trusted from the client:

- you may only export from a message in one of your own chats, so a guessed
  message id gets you nothing;
- a finished file is downloadable only by the user whose job produced it.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from app import config
from app.config import (
    _SAFE_EXPORT_RE,
    _SAFE_MEDIA_RE,
    EXPORT_MAX_CLIP_SEC,
    EXPORT_MAX_PER_HOUR,
)
from app.db import db
from app.errors import HTTPExceptionJson
from app.models import ExportRequest
from app.repositories import exports as jobs
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token
from app.services.export_naming import content_disposition, download_filename

router = APIRouter()

# What each job type produces, and what it is called when downloaded.
_OUTPUT_TYPES = {
    jobs.JOB_GIF: ("image/gif", ".gif"),
    jobs.JOB_CLIP: ("video/mp4", ".mp4"),
    jobs.JOB_FRAME: ("image/png", ".png"),
    jobs.JOB_PPTX: (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}

_ALLOWED_FPS = (10, 15, 20)
_ALLOWED_WIDTHS = (320, 480, 640, 800)


async def _require_user(request: Request) -> Dict[str, Any]:
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    return user


async def _owned_message(message_id: str, user_id: str) -> Dict[str, Any]:
    """The message, if it belongs to a chat this user owns.

    Same 404 for "no such message" and "not yours": telling the two apart
    would let someone probe for which message ids exist.
    """
    if not ObjectId.is_valid(message_id):
        raise HTTPExceptionJson(404, "Not found")
    message = await db.db.messages.find_one({"_id": ObjectId(message_id)})
    if not message:
        raise HTTPExceptionJson(404, "Not found")

    chat_id = message.get("chat_id", "")
    if not ObjectId.is_valid(chat_id):
        raise HTTPExceptionJson(404, "Not found")
    chat = await db.db.chats.find_one({"_id": ObjectId(chat_id)})
    if not chat or str(chat.get("user_id")) != str(user_id):
        raise HTTPExceptionJson(404, "Not found")
    return message


def _validate_clip_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Clamp the numbers to a range the encoder can actually deliver.

    Validated here, not in the worker: a request that can never succeed should
    be refused while the user is still looking at the dialog, rather than
    queued and failed a minute later.
    """
    try:
        start = float(params.get("start", 0))
        end = float(params.get("end", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPExceptionJson(400, "start and end must be numbers") from exc

    if start < 0 or end <= start:
        raise HTTPExceptionJson(400, "The selection is empty")
    if end - start > EXPORT_MAX_CLIP_SEC:
        raise HTTPExceptionJson(
            400, f"Select at most {EXPORT_MAX_CLIP_SEC:.0f} seconds"
        )

    fps = int(params.get("fps", 15))
    width = int(params.get("width", 640))
    if fps not in _ALLOWED_FPS:
        raise HTTPExceptionJson(400, f"fps must be one of {_ALLOWED_FPS}")
    if width not in _ALLOWED_WIDTHS:
        raise HTTPExceptionJson(400, f"width must be one of {_ALLOWED_WIDTHS}")

    return {
        "start": start,
        "end": end,
        "fps": fps,
        "width": width,
        "loop": bool(params.get("loop", True)),
        "caption": str(params.get("caption", ""))[:120],
    }


async def _question_for(message: Dict[str, Any]) -> str:
    """The question this answer replies to - the better name for an export.

    Falls back to the answer's own opening words when the chat has no user
    message before it, which happens for the first message of an imported or
    partially deleted chat.
    """
    question = await db.db.messages.find_one(
        {"chat_id": message.get("chat_id"), "role": "user",
         "timestamp": {"$lte": message.get("timestamp")}},
        sort=[("timestamp", -1)],
    )
    title = (question or {}).get("content", "") or message.get("content", "")
    return str(title)[:120]


@router.post("/api/export")
async def queue_export(payload: ExportRequest, request: Request):
    user = await _require_user(request)
    user_id = str(user["_id"])

    if payload.type not in jobs.KNOWN_JOB_TYPES:
        raise HTTPExceptionJson(400, f"Unknown export type {payload.type!r}")

    window_start = datetime.now(timezone.utc) - timedelta(hours=1)
    if await jobs.jobs_started_since(user_id, window_start) >= EXPORT_MAX_PER_HOUR:
        raise HTTPExceptionJson(
            429, f"Only {EXPORT_MAX_PER_HOUR} exports per hour. Try again later."
        )

    message = await _owned_message(payload.message_id, user_id)
    video_url = message.get("video_url") or ""
    filename = video_url.rsplit("/", 1)[-1]
    if not filename or not _SAFE_MEDIA_RE.fullmatch(filename):
        raise HTTPExceptionJson(400, "That message has no video to export")
    if not (config.MEDIA_DIR / filename).is_file():
        # Retention may have collected it; say so plainly rather than queueing
        # a job that cannot read its input.
        raise HTTPExceptionJson(410, "The video for that message is no longer stored")

    params = dict(payload.params or {})
    if payload.type in (jobs.JOB_GIF, jobs.JOB_CLIP):
        params = _validate_clip_params(params)
    elif payload.type == jobs.JOB_FRAME:
        try:
            params = {"at": max(0.0, float(params.get("at", 0)))}
        except (TypeError, ValueError) as exc:
            raise HTTPExceptionJson(400, "at must be a number") from exc

    params["source_title"] = await _question_for(message)
    if payload.type == jobs.JOB_PPTX:
        # The deck is built from the explanation itself, so it travels with
        # the job rather than being re-read by a worker with no database.
        params["educator_text"] = str(message.get("content", ""))[:8000]

    job = await jobs.create_job(
        user_id=user_id,
        job_type=payload.type,
        source_path=filename,
        params=params,
        message_id=payload.message_id,
    )
    return JSONResponse(status_code=202, content={"job_id": str(job["_id"])})


def _job_view(job: Dict[str, Any]) -> Dict[str, Any]:
    view = {
        "job_id": str(job["_id"]),
        "type": job.get("type", ""),
        "status": job.get("status", ""),
        "progress": int(job.get("progress", 0)),
        "error": job.get("error", ""),
        "output_bytes": int(job.get("output_bytes", 0)),
    }
    if job.get("status") == jobs.STATUS_DONE:
        view["download_url"] = f"/api/export/{view['job_id']}/download"
    return view


@router.get("/api/export/{job_id}")
async def export_status(job_id: str, request: Request):
    user = await _require_user(request)
    job = await jobs.get_job(job_id)
    if not job or str(job.get("user_id")) != str(user["_id"]):
        raise HTTPExceptionJson(404, "Not found")
    return _job_view(job)


@router.get("/api/export/{job_id}/download")
async def export_download(job_id: str, request: Request):
    user = await _require_user(request)
    job = await jobs.get_job(job_id)
    if not job or str(job.get("user_id")) != str(user["_id"]):
        raise HTTPExceptionJson(404, "Not found")
    if job.get("status") != jobs.STATUS_DONE:
        raise HTTPExceptionJson(409, "That export is not finished")

    stored = str(job.get("output_path") or "")
    # The worker writes the name; treat it as untrusted anyway, so a bad write
    # can never turn into a path escape here.
    if not stored or not _SAFE_EXPORT_RE.fullmatch(stored):
        raise HTTPExceptionJson(404, "Not found")
    path: Path = config.EXPORT_DIR / stored
    if not path.is_file():
        raise HTTPExceptionJson(410, "That export has expired")

    media_type, suffix = _OUTPUT_TYPES.get(job.get("type", ""), ("application/octet-stream", ""))
    nice_name = download_filename(job.get("params", {}).get("source_title", ""), suffix)
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(nice_name),
            "Cache-Control": "private, no-store",
        },
    )
