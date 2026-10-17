"""How a document asked for in the background is getting on.

The page that asked with `Prefer: respond-async` polls here every few seconds.
Only the asker sees a job: anybody else's id is a 404, the same as a job that
does not exist.
"""

from fastapi import APIRouter, Request

from app.errors import HTTPExceptionJson
from app.repositories import lesson_plans
from app.security.roles import require_user
from app.services import jobs

router = APIRouter()


@router.get("/api/jobs/{job_id}")
async def job_status(job_id: str, request: Request):
    user = await require_user(request)
    job = await jobs.collect(job_id, str(user["_id"]))
    if not job:
        raise HTTPExceptionJson(404, "Not found")

    reply = {"id": str(job["_id"]), "kind": job.get("kind"), "status": job.get("status")}
    if job.get("status") == "failed":
        reply["error"] = job.get("error") or {"status": 502, "detail": "Could not finish this."}
    elif job.get("status") == "done":
        if job.get("kind") == "lesson_plan" and job.get("output_id"):
            reply["lesson_plan"] = await lesson_plans.get_lesson_plan(job["output_id"], str(user["_id"]))
        elif job.get("kind") == "quiz_draft":
            # Handed over once; a second look finds nothing, and the page says so.
            reply["result"] = job.get("result")
    return reply
