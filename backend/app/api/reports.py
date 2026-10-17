""""Something is wrong with this": a teacher's report on a result.

The pilot's feedback channel. A report names what it is about - an
explanation, a paper, a plan, a quiz - and says in the teacher's words what
is wrong. It lands in the admin panel and, if the bot is set up, in the
team's Telegram, so a wrong answer key is seen the same day.

Staff mark a report done when it has been dealt with; nothing is deleted.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app import config
from app.db import db
from app.errors import HTTPExceptionJson
from app.repositories import audit
from app.security.roles import require_user
from app.security.staff import require_staff
from app.services import telegram

router = APIRouter()
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_staff)])

KINDS = {
    "explanation": "объяснение",
    "assessment": "БЖБ/ТЖБ",
    "lesson_plan": "план урока",
    "quiz": "квиз",
    "other": "другое",
}
MAX_TEXT = 1500
PER_DAY = 20


class ReportRequest(BaseModel):
    kind: str
    ref_id: Optional[str] = ""
    text: str
    # Where it was sent from, so a report about "this" can be found.
    page: Optional[str] = ""


class Resolve(BaseModel):
    reason: Optional[str] = ""


def _view(report: dict) -> dict:
    at = report.get("created_at")
    done = report.get("resolved_at")
    return {
        "id": str(report["_id"]),
        "kind": report.get("kind"),
        "ref_id": report.get("ref_id") or "",
        "text": report.get("text") or "",
        "page": report.get("page") or "",
        "user_id": report.get("user_id"),
        "email": report.get("email") or "",
        "status": report.get("status"),
        "created_at": at.isoformat() if isinstance(at, datetime) else None,
        "resolved_at": done.isoformat() if isinstance(done, datetime) else None,
        "resolved_by": report.get("resolved_by") or "",
    }


@router.post("/api/reports", status_code=201)
async def report_problem(body: ReportRequest, request: Request):
    user = await require_user(request)
    text = (body.text or "").strip()
    if not text:
        raise HTTPExceptionJson(400, "Say what is wrong", code="report_empty")
    if body.kind not in KINDS:
        raise HTTPExceptionJson(400, "Unknown kind")
    user_id = str(user["_id"])
    since = datetime.now(timezone.utc) - timedelta(days=1)
    if await db.db.problem_reports.count_documents({"user_id": user_id, "created_at": {"$gte": since}}) >= PER_DAY:
        raise HTTPExceptionJson(429, "That is enough reports for today", code="report_limit")

    report = {
        "user_id": user_id,
        "email": user.get("email") or "",
        "kind": body.kind,
        "ref_id": (body.ref_id or "").strip()[:64],
        "text": text[:MAX_TEXT],
        "page": (body.page or "").strip()[:200],
        "status": "open",
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.db.problem_reports.insert_one(report)
    telegram.send_later(
        f"🛠 Akron: сообщение о проблеме ({KINDS[body.kind]})\n\n"
        f"{report['text'][:800]}\n\n"
        f"Аккаунт: {report['email'] or user_id}\n"
        f"{config.PUBLIC_BASE_URL}/admin?tab=reports"
    )
    return {"id": str(result.inserted_id), "ok": True}


@admin_router.get("/reports")
async def list_reports(status: str = "open", limit: int = 100):
    query = {"status": status} if status in ("open", "resolved") else {}
    cursor = db.db.problem_reports.find(query).sort("created_at", -1).limit(min(max(limit, 1), 300))
    items = [_view(r) async for r in cursor]
    return {"items": items, "open": await db.db.problem_reports.count_documents({"status": "open"})}


@admin_router.post("/reports/{report_id}/resolve")
async def resolve(report_id: str, body: Resolve, actor=Depends(require_staff)):
    if not ObjectId.is_valid(report_id):
        raise HTTPExceptionJson(404, "Not found")
    found = await db.db.problem_reports.find_one_and_update(
        {"_id": ObjectId(report_id), "status": "open"},
        {"$set": {"status": "resolved", "resolved_at": datetime.now(timezone.utc),
                  "resolved_by": actor.get("email") or str(actor["_id"]),
                  "resolution": (body.reason or "")[:300]}},
    )
    if not found:
        raise HTTPExceptionJson(404, "Not found")
    await audit.record(actor=audit.staff_actor(actor), action="report.resolve",
                       target={"report_id": report_id, "user_id": found.get("user_id")},
                       reason=(body.reason or "")[:300])
    return {"ok": True}
