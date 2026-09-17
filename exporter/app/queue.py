"""The consumer half of the export queue.

The schema is owned by `backend/app/repositories/exports.py`, which creates the
documents and the indexes; this module only claims and completes them. The two
are deliberately separate modules rather than a shared import, because they
live in different images - so the field names below are a contract, and
changing one side means changing both.

`claim` is a single find_one_and_update: the read and the state change are one
operation, so a second worker can be started without either doing the same
encode twice.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


class JobQueue:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.jobs = db.export_jobs

    async def claim(self) -> Optional[Dict[str, Any]]:
        return await self.jobs.find_one_and_update(
            {"status": STATUS_QUEUED},
            {"$set": {"status": STATUS_RUNNING,
                      "started_at": datetime.now(timezone.utc)}},
            sort=[("created_at", 1)],
            return_document=True,
        )

    async def progress(self, job_id: Any, value: int) -> None:
        await self.jobs.update_one(
            {"_id": job_id}, {"$set": {"progress": max(0, min(100, int(value)))}}
        )

    async def finish(self, job_id: Any, output_name: str, size: int,
                     result: Dict[str, Any]) -> None:
        await self.jobs.update_one(
            {"_id": job_id},
            {"$set": {
                "status": STATUS_DONE,
                "progress": 100,
                "output_path": output_name,
                "output_bytes": int(size),
                "result": result,
                "finished_at": datetime.now(timezone.utc),
            }},
        )

    async def fail(self, job_id: Any, error: str) -> None:
        await self.jobs.update_one(
            {"_id": job_id},
            {"$set": {
                "status": STATUS_FAILED,
                # Shown to the user, so it is trimmed: an ffmpeg traceback is
                # neither useful to them nor something to hand over whole.
                "error": (error or "")[:300],
                "finished_at": datetime.now(timezone.utc),
            }},
        )

    async def reclaim_stale(self, timeout_sec: int) -> int:
        """Fail jobs whose worker died mid-encode.

        Without this, a killed worker leaves the job "running" forever and the
        UI spins on a result that will never arrive.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_sec)
        result = await self.jobs.update_many(
            {"status": STATUS_RUNNING, "started_at": {"$lt": cutoff}},
            {"$set": {"status": STATUS_FAILED,
                      "error": "the export worker stopped before finishing",
                      "finished_at": datetime.now(timezone.utc)}},
        )
        return result.modified_count

    async def expired(self) -> List[Dict[str, Any]]:
        """Jobs past their TTL that still have a file to remove.

        The TTL index drops the documents on its own schedule, which would
        leave the files orphaned; this catches them while the document still
        says where the file is.
        """
        now = datetime.now(timezone.utc)
        return [
            job
            async for job in self.jobs.find(
                {"expires_at": {"$lt": now}, "output_path": {"$nin": ["", None]}}
            )
        ]

    async def forget(self, job_id: Any) -> None:
        await self.jobs.delete_one({"_id": job_id})
