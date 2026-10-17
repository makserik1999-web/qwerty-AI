"""The export worker: one job at a time, forever.

A separate service rather than a thread in an existing one, for two concrete
reasons. The agent runs on a read-only rootfs with tight limits so that
LLM-written Manim cannot do damage - a general-purpose ffmpeg does not belong
inside that sandbox. And the backend is a single event loop: an encode there
would stall every other request for its whole duration, including the status
polls asking how the encode is going.

Polling rather than a broker. There is one worker and a per-user rate limit,
so the queue is short by construction; Redis earns its keep at the second
worker, not before. The claim is atomic, so adding that worker later is a
compose change rather than a rewrite.
"""

import asyncio
import os
import signal
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict

from motor.motor_asyncio import AsyncIOMotorClient

from app.jobs import clip, pptx
from app.queue import JobQueue

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongo:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "anyq_db")
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/app/media/outputs"))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "/app/media/exports"))
POLL_INTERVAL_SEC = float(os.getenv("EXPORT_POLL_INTERVAL_SEC", "2"))
SWEEP_INTERVAL_SEC = float(os.getenv("EXPORT_SWEEP_INTERVAL_SEC", "900"))
JOB_TIMEOUT_SEC = int(os.getenv("EXPORT_JOB_TIMEOUT_SEC", "600"))
MAX_OUTPUT_BYTES = int(os.getenv("EXPORT_MAX_OUTPUT_BYTES", str(20 * 1024 * 1024)))
# Touched every loop. The healthcheck reads its age, so "healthy" means the
# worker is actually looping - not merely that the process still exists or
# that Mongo happens to answer.
HEARTBEAT = Path(os.getenv("EXPORT_HEARTBEAT_PATH", "/tmp/exporter-heartbeat"))

# Each handler writes to `destination` and returns what it measured.
HANDLERS = {
    "gif": (clip.run_gif, ".gif"),
    "clip": (clip.run_clip, ".mp4"),
    "frame": (clip.run_frame, ".png"),
    "pptx": (pptx.run_pptx, ".pptx"),
}

_shutdown = asyncio.Event()


async def run_job(queue: JobQueue, job: Dict[str, Any]) -> None:
    job_id = job["_id"]
    job_type = job.get("type", "")
    handler = HANDLERS.get(job_type)
    if not handler:
        await queue.fail(job_id, f"no handler for export type {job_type!r}")
        return

    run, suffix = handler
    source = MEDIA_DIR / str(job.get("source_path", ""))
    if not source.is_file():
        await queue.fail(job_id, "the source video is no longer stored")
        return

    # The name is generated here, never taken from the request: it ends up in
    # a path, and the API re-validates it before serving anyway.
    output_name = f"{job_type}_{uuid.uuid4().hex[:12]}{suffix}"
    destination = EXPORT_DIR / output_name
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_running_loop()

    def on_progress(value: int) -> None:
        # The encode runs in a worker thread; hop back to the loop to write.
        asyncio.run_coroutine_threadsafe(queue.progress(job_id, value), loop)

    try:
        await queue.progress(job_id, 5)
        result = await asyncio.to_thread(
            run, source, destination, job.get("params", {}), MAX_OUTPUT_BYTES, on_progress
        )
    except Exception as exc:  # noqa: BLE001 - the reason is reported to the user
        print(f"[worker] job {job_id} failed: {traceback.format_exc()[-800:]}")
        destination.unlink(missing_ok=True)
        await queue.fail(job_id, f"{type(exc).__name__}: {exc}")
        return

    size = result.get("bytes", 0)
    await queue.finish(job_id, output_name, size, result)
    note = " (still over budget)" if result.get("over_budget") else ""
    print(f"[worker] {job_type} {output_name} {size / 1e6:.2f}MB{note}")


async def sweep(queue: JobQueue) -> None:
    """Delete expired result files, then their documents.

    File first: if the process dies between the two, the next sweep still sees
    the document and retries. The other order would leak the file forever.
    """
    for job in await queue.expired():
        name = str(job.get("output_path") or "")
        if name:
            (EXPORT_DIR / name).unlink(missing_ok=True)
        await queue.forget(job["_id"])

    reclaimed = await queue.reclaim_stale(JOB_TIMEOUT_SEC)
    if reclaimed:
        print(f"[worker] reclaimed {reclaimed} stalled job(s)")


async def main() -> None:
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    queue = JobQueue(client[DATABASE_NAME])
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[worker] watching {MONGO_URL}/{DATABASE_NAME}, writing to {EXPORT_DIR}")

    last_sweep = 0.0
    loop = asyncio.get_running_loop()
    try:
        while not _shutdown.is_set():
            HEARTBEAT.touch()
            now = loop.time()
            if now - last_sweep > SWEEP_INTERVAL_SEC:
                last_sweep = now
                try:
                    await sweep(queue)
                except Exception as exc:  # noqa: BLE001
                    # A failed sweep must never stop the worker encoding.
                    print(f"[worker] sweep failed: {type(exc).__name__}: {exc}")

            try:
                job = await queue.claim()
            except Exception as exc:  # noqa: BLE001 - mongo may be restarting
                print(f"[worker] cannot reach the queue: {type(exc).__name__}: {exc}")
                await asyncio.sleep(5)
                continue

            if not job:
                try:
                    await asyncio.wait_for(_shutdown.wait(), timeout=POLL_INTERVAL_SEC)
                except asyncio.TimeoutError:
                    pass
                continue

            await run_job(queue, job)
    finally:
        client.close()
        print("[worker] stopped")


if __name__ == "__main__":
    runner = asyncio.new_event_loop()
    asyncio.set_event_loop(runner)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            runner.add_signal_handler(sig, _shutdown.set)
        except NotImplementedError:
            # Windows has no signal handlers on the loop; the container is
            # Linux, and a local run can still be stopped with Ctrl+C.
            pass
    runner.run_until_complete(main())
