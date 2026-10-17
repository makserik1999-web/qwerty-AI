"""Export jobs: the queue between the API and the exporter worker.

A Mongo collection rather than Redis, deliberately. There is one worker, and
the job rate is bounded by EXPORT_MAX_PER_HOUR per user; a real broker earns
its keep at the second worker, not before. The collection gives durability and
a status the UI can poll for free.

State machine, and nothing outside it:

    queued -> running -> done
                      -> failed

`claim_next_job` moves queued to running with a single atomic update, so two
workers could be started tomorrow without either doing the same encode twice.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.config import EXPORT_JOB_TIMEOUT_SEC, EXPORT_TTL_HOURS
from app.db import db

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# Job types the API accepts. Anything else is rejected before it reaches the
# queue, so the worker never has to decide what an unknown type means.
JOB_GIF = "gif"
JOB_CLIP = "clip"
JOB_FRAME = "frame"
JOB_PPTX = "pptx"
KNOWN_JOB_TYPES = (JOB_GIF, JOB_CLIP, JOB_FRAME, JOB_PPTX)


async def create_job(
    user_id: str,
    job_type: str,
    source_path: str,
    params: Dict[str, Any],
    message_id: str = "",
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": user_id,
        "type": job_type,
        "source_path": source_path,
        "message_id": message_id,
        "params": params,
        "status": STATUS_QUEUED,
        "progress": 0,
        "error": "",
        "output_path": "",
        "output_bytes": 0,
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        # The result file is disposable; the document goes with it.
        "expires_at": now + timedelta(hours=EXPORT_TTL_HOURS),
    }
    result = await db.db.export_jobs.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    if not ObjectId.is_valid(job_id):
        return None
    return await db.db.export_jobs.find_one({"_id": ObjectId(job_id)})


async def jobs_started_since(user_id: str, since: datetime) -> int:
    """How many jobs this user queued in the window - the rate limit input."""
    return await db.db.export_jobs.count_documents(
        {"user_id": user_id, "created_at": {"$gte": since}}
    )


async def claim_next_job() -> Optional[Dict[str, Any]]:
    """Take the oldest queued job, atomically.

    find_one_and_update rather than find-then-update: the read and the state
    change are one operation, so a second worker cannot claim the same job.
    """
    return await db.db.export_jobs.find_one_and_update(
        {"status": STATUS_QUEUED},
        {"$set": {"status": STATUS_RUNNING, "started_at": datetime.now(timezone.utc)}},
        sort=[("created_at", 1)],
        return_document=True,
    )


async def set_progress(job_id: Any, progress: int) -> None:
    await db.db.export_jobs.update_one(
        {"_id": job_id}, {"$set": {"progress": max(0, min(100, int(progress)))}}
    )


async def finish_job(job_id: Any, output_path: str, output_bytes: int) -> None:
    await db.db.export_jobs.update_one(
        {"_id": job_id},
        {
            "$set": {
                "status": STATUS_DONE,
                "progress": 100,
                "output_path": output_path,
                "output_bytes": int(output_bytes),
                "finished_at": datetime.now(timezone.utc),
            }
        },
    )


async def fail_job(job_id: Any, error: str) -> None:
    await db.db.export_jobs.update_one(
        {"_id": job_id},
        {
            "$set": {
                "status": STATUS_FAILED,
                # Truncated: this string is shown to the user, and an ffmpeg
                # traceback is neither useful nor safe to hand over whole.
                "error": (error or "")[:300],
                "finished_at": datetime.now(timezone.utc),
            }
        },
    )


async def reclaim_stale_jobs() -> int:
    """Fail jobs whose worker died mid-encode.

    Without this a killed worker leaves the job "running" forever, and the UI
    shows a spinner that will never resolve.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=EXPORT_JOB_TIMEOUT_SEC)
    result = await db.db.export_jobs.update_many(
        {"status": STATUS_RUNNING, "started_at": {"$lt": cutoff}},
        {
            "$set": {
                "status": STATUS_FAILED,
                "error": "the export worker stopped before finishing",
                "finished_at": datetime.now(timezone.utc),
            }
        },
    )
    return result.modified_count


async def expired_jobs() -> List[Dict[str, Any]]:
    """Finished jobs past their TTL, so their files can be removed.

    The TTL index removes the documents on its own schedule; this returns them
    while they are still readable, because the file on disk has to go too.
    """
    now = datetime.now(timezone.utc)
    return [
        job
        async for job in db.db.export_jobs.find(
            {"expires_at": {"$lt": now}, "output_path": {"$ne": ""}}
        )
    ]


async def drop_job(job_id: Any) -> None:
    await db.db.export_jobs.delete_one({"_id": job_id})
