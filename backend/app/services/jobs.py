"""Every generation as a task: what is waiting, what is running, what failed and why.

usage_log counts what people made, which is what the statistics need. It
cannot say what is happening right now, how long a render took, why one
failed, which videos came out silent, or let anybody try a failure again.
This does - one document per generation, videos and documents alike:

    kind          video | assessment | lesson_plan | quiz_draft
    user_id
    ref           the id the work goes by: the agent's request id for a
                  video, the plan reservation's ref for a document
    status        queued -> running -> done | failed
    created_at, started_at, finished_at
    render_sec    how long the agent worked on it - measured by the agent for
                  a video, so a wait in its queue is not counted as rendering
    error_type    a short name for what went wrong: timeout, agent_lost,
                  agent_unavailable, delivery, backend_restart, or the class
                  name the agent reported. Never the error text.
    video, has_audio, narration, duration, tts_chars        (videos)
    spec          what was asked for, so a failure can be made again. The
                  question is already in the teacher's chat; screenshots are
                  not copied here, they stay in the chat message. The
                  question goes when the task succeeds, or two weeks after it
                  failed.
    error         for a document: the status, detail and code the page is
                  shown, the same as a failed request would have answered
    output_id     the saved paper or plan it produced
    result        a quiz draft made in the background, until it is collected
    restart_of / restarted_as

Writing here must never fail the generation it describes: every write
swallows its own errors, like usage_log.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Dict, List, Optional

from bson import ObjectId

from app.db import db
from app.errors import HTTPExceptionJson

KINDS = ("video", "assessment", "lesson_plan", "quiz_draft")
DOCUMENT_KINDS = ("assessment", "lesson_plan", "quiz_draft")
OPEN = ("queued", "running")

# A document made in the background waits this long to be collected.
RESULT_KEEP = timedelta(hours=1)

# A failure keeps what was asked for this long, to be restarted; then it goes.
SPEC_KEEP = timedelta(days=14)
# The parts of a video's spec that are the teacher's words or point at them.
_ASKED = ("prompt", "chat_id", "user_message_id")

# What an HTTP failure from a document endpoint means, as an error type.
_TYPE_FOR_STATUS = {503: "agent_unavailable", 504: "timeout", 502: "bad_output"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> Optional[str]:
    moment = _aware(value)
    return moment.isoformat() if moment else None


def error_type_for(status: int) -> str:
    return _TYPE_FOR_STATUS.get(int(status or 0), f"http_{status}")


async def start(kind: str, user_id: str, ref: str, *, spec: Optional[Dict[str, Any]] = None,
                **fields: Any) -> Optional[str]:
    """Record a generation that has been asked for. Returns the job id."""
    try:
        result = await db.db.generation_jobs.insert_one({
            "kind": kind,
            "user_id": str(user_id),
            "ref": ref,
            "status": "queued",
            "created_at": _now(),
            "spec": spec or {},
            **fields,
        })
        return str(result.inserted_id)
    except Exception as e:  # noqa: BLE001 - a log never fails the work
        print(f"job start write failed: {type(e).__name__}: {e}")
        return None


async def running(ref: str) -> None:
    """The work has begun. Only the first report counts as the start."""
    try:
        await db.db.generation_jobs.update_one(
            {"ref": ref, "status": "queued"},
            {"$set": {"status": "running", "started_at": _now()}},
        )
    except Exception as e:  # noqa: BLE001
        print(f"job running write failed: {type(e).__name__}: {e}")


async def finish(ref: str, *, ok: bool, error_type: Optional[str] = None,
                 render_sec: Optional[float] = None, **fields: Any) -> None:
    """Done or failed. A late answer after a failure turns it into done."""
    try:
        job = await db.db.generation_jobs.find_one({"ref": ref}, {"created_at": 1, "started_at": 1})
        if not job:
            return
        now = _now()
        update: Dict[str, Any] = {"status": "done" if ok else "failed", "finished_at": now, **fields}
        if render_sec is None:
            begun = _aware(job.get("started_at")) or _aware(job.get("created_at"))
            render_sec = (now - begun).total_seconds() if begun else None
        if render_sec is not None:
            try:
                update["render_sec"] = round(float(render_sec), 1)
            except (TypeError, ValueError):
                pass
        unset: Dict[str, str] = {}
        if ok:
            # A finished task is never made again, so what was asked is not
            # kept: the question stays in the teacher's chat, and only there.
            unset = {"error_type": "", "error": "", **{f"spec.{key}": "" for key in _ASKED}}
        else:
            update["error_type"] = str(error_type or "unknown")[:60]
        await db.db.generation_jobs.update_one(
            {"_id": job["_id"]}, {"$set": update, **({"$unset": unset} if unset else {})})
    except Exception as e:  # noqa: BLE001
        print(f"job finish write failed: {type(e).__name__}: {e}")


async def failed(ref: str, exc: BaseException) -> None:
    """A document's generation raised. What the page is told is kept with the job,
    so a page polling for it gets the same answer the request would have."""
    if isinstance(exc, HTTPExceptionJson):
        error = {"status": exc.status_code, "detail": exc.detail,
                 **({"code": exc.code} if exc.code else {})}
        await finish(ref, ok=False, error_type=error_type_for(exc.status_code), error=error)
    elif isinstance(exc, asyncio.CancelledError):
        await finish(ref, ok=False, error_type="cancelled",
                     error={"status": 503, "detail": "The server restarted. Please try again."})
    else:
        await finish(ref, ok=False, error_type="internal",
                     error={"status": 500, "detail": "Internal error"})


def wants_background(request: Any) -> bool:
    """The page asked to poll for the result rather than wait on the response."""
    return "respond-async" in (request.headers.get("prefer") or "").lower()


async def fail_open(refs: List[str], error_type: str) -> None:
    """Mark these generations failed, if they are still waiting or running."""
    if not refs:
        return
    try:
        await db.db.generation_jobs.update_many(
            {"ref": {"$in": refs}, "status": {"$in": list(OPEN)}},
            {"$set": {"status": "failed", "error_type": error_type, "finished_at": _now()}},
        )
    except Exception as e:  # noqa: BLE001
        print(f"job failure write failed: {type(e).__name__}: {e}")


async def get(job_id: str) -> Optional[Dict[str, Any]]:
    if not ObjectId.is_valid(job_id):
        return None
    return await db.db.generation_jobs.find_one({"_id": ObjectId(job_id)})


async def collect(job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """The asker's own job. A finished result is handed over once, then forgotten.

    Forgotten because a quiz draft is not something this side keeps: until it
    is collected it has to live somewhere, and that is all this is.
    """
    if not ObjectId.is_valid(job_id):
        return None
    query = {"_id": ObjectId(job_id), "user_id": str(user_id)}
    job = await db.db.generation_jobs.find_one(query)
    if job and job.get("status") == "done" and "result" in job:
        await db.db.generation_jobs.update_one(query, {"$unset": {"result": ""},
                                                       "$set": {"collected_at": _now()}})
    return job


# A background task nobody holds a reference to can be collected mid-flight.
_tasks: set = set()


def spawn(work: Awaitable[Any]) -> None:
    """Run a document's generation after the request that asked for it has returned."""
    async def _guarded() -> None:
        try:
            await work
        except Exception as e:  # noqa: BLE001 - the job already says it failed
            if not isinstance(e, HTTPExceptionJson):
                print(f"background job failed: {type(e).__name__}: {e}")

    task = asyncio.create_task(_guarded())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def recover_after_restart() -> int:
    """Close the jobs a previous backend process left open, and give their units back.

    A document's generation is a task in this process, and a video's request
    lives in its memory: neither survives a restart, so a job still open at
    start-up will never finish. Saying so beats a spinner that never stops.
    """
    from app.services import plans, quota

    count = 0
    try:
        async for job in db.db.generation_jobs.find({"status": {"$in": list(OPEN)}}, {"ref": 1, "kind": 1}):
            ref = job.get("ref") or ""
            await plans.release(ref)
            if job.get("kind") == "video":
                await quota.refund(ref)
            count += 1
        if count:
            await db.db.generation_jobs.update_many(
                {"status": {"$in": list(OPEN)}},
                {"$set": {"status": "failed", "error_type": "backend_restart", "finished_at": _now()}},
            )
    except Exception as e:  # noqa: BLE001 - start-up must not fail on this
        print(f"job recovery failed: {type(e).__name__}: {e}")
    return count


async def forget_uncollected(now: Optional[datetime] = None) -> int:
    """Drop background results nobody came back for, and old failures' questions."""
    now = now or _now()
    result = await db.db.generation_jobs.update_many(
        {"result": {"$exists": True}, "finished_at": {"$lt": now - RESULT_KEEP}},
        {"$unset": {"result": ""}},
    )
    await db.db.generation_jobs.update_many(
        {"status": "failed", "finished_at": {"$lt": now - SPEC_KEEP}, "spec.prompt": {"$exists": True}},
        {"$unset": {f"spec.{key}": "" for key in _ASKED}},
    )
    return result.modified_count


async def housekeeping_loop() -> None:
    while True:
        await asyncio.sleep(600)
        try:
            await forget_uncollected()
        except Exception as e:  # noqa: BLE001
            print(f"job housekeeping failed: {type(e).__name__}: {e}")


# ------------------------------------------------------------------ admin --


def public(job: Dict[str, Any], email: str = "") -> Dict[str, Any]:
    """A job as the admin panel shows it."""
    spec = job.get("spec") or {}
    return {
        "id": str(job["_id"]),
        "kind": job.get("kind"),
        "user_id": job.get("user_id"),
        "email": email,
        "status": job.get("status"),
        "created_at": _iso(job.get("created_at")),
        "started_at": _iso(job.get("started_at")),
        "finished_at": _iso(job.get("finished_at")),
        "render_sec": job.get("render_sec"),
        "error_type": job.get("error_type"),
        "video": job.get("video"),
        "has_audio": job.get("has_audio"),
        "narration": job.get("narration"),
        "duration": job.get("duration"),
        "tts_chars": job.get("tts_chars"),
        "effort": spec.get("effort"),
        "summary": str(spec.get("prompt") or spec.get("topic")
                       or (spec.get("classification") or {}).get("topic_id") or "")[:160],
        "restart_of": job.get("restart_of"),
        "restarted_as": job.get("restarted_as"),
        "restartable": restartable(job),
    }


def restartable(job: Dict[str, Any]) -> bool:
    spec = job.get("spec") or {}
    if job.get("status") != "failed" or job.get("restarted_as"):
        return False
    if job.get("kind") == "video":
        return bool(spec.get("prompt") and spec.get("chat_id"))
    return job.get("kind") == "lesson_plan" and bool(spec.get("topic"))


async def listing(*, status: str = "", kind: str = "", silent: bool = False,
                  page: int = 1, limit: int = 50) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if status == "open":
        query["status"] = {"$in": list(OPEN)}
    elif status in ("queued", "running", "done", "failed"):
        query["status"] = status
    if kind in KINDS:
        query["kind"] = kind
    if silent:
        # Asked to speak, came out without sound.
        query.update({"kind": "video", "video": True, "narration": True, "has_audio": False})
    page = max(1, page)
    total = await db.db.generation_jobs.count_documents(query)
    cursor = (db.db.generation_jobs.find(query).sort("created_at", -1)
              .skip((page - 1) * limit).limit(limit))
    found = [job async for job in cursor]
    ids = list({ObjectId(j["user_id"]) for j in found if ObjectId.is_valid(j.get("user_id") or "")})
    emails = {str(u["_id"]): u.get("email", "") async for u in db.db.users.find({"_id": {"$in": ids}}, {"email": 1})}
    return {
        "items": [public(job, emails.get(job.get("user_id"), "")) for job in found],
        "total": total,
        "page": page,
        "counts": await counts(),
    }


async def counts() -> Dict[str, int]:
    since = _now() - timedelta(hours=24)
    return {
        "queued": await db.db.generation_jobs.count_documents({"status": "queued"}),
        "running": await db.db.generation_jobs.count_documents({"status": "running"}),
        "failed_24h": await db.db.generation_jobs.count_documents(
            {"status": "failed", "finished_at": {"$gte": since}}),
        "silent_24h": await db.db.generation_jobs.count_documents(
            {"kind": "video", "video": True, "narration": True, "has_audio": False,
             "finished_at": {"$gte": since}}),
    }
