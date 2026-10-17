"""A teacher's quizzes: list, create, edit, copy, delete."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from quiz_service import lifecycle
from quiz_service.config import GRADES, LANGUAGES, MAX_QUESTIONS, MAX_QUIZZES_PER_OWNER, SUBJECTS
from quiz_service.db import iso
from quiz_service.errors import ApiError
from quiz_service.identity import require_teacher
from quiz_service.questions import (
    DEFAULT_SETTINGS,
    clean_questions,
    clean_settings,
    clean_title,
)
from quiz_service.store import players as players_store
from quiz_service.store import quizzes as store
from quiz_service.store import sessions as sessions_store

router = APIRouter()


class QuizBody(BaseModel):
    title: Optional[str] = None
    subject: Optional[str] = None
    grade: Optional[int] = None
    lang: Optional[str] = None
    topic: Optional[str] = None
    questions: Optional[List[Any]] = None
    settings: Optional[Dict[str, Any]] = None


def _fields(body: QuizBody, current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The fields a body sets. On an update, a field left out is unchanged."""
    creating = current is None
    out: Dict[str, Any] = {}
    if body.title is not None or creating:
        out["title"] = clean_title(body.title)
    if body.subject is not None or creating:
        out["subject"] = body.subject if body.subject in SUBJECTS else "other"
    if body.grade is not None or creating:
        out["grade"] = body.grade if body.grade in GRADES else 0
    if body.lang is not None or creating:
        out["lang"] = body.lang if body.lang in LANGUAGES else "kk"
    if body.topic is not None or creating:
        out["topic"] = (body.topic or "").strip()[:200]
    if body.questions is not None or creating:
        out["questions"] = clean_questions(body.questions or [], MAX_QUESTIONS)
    if body.settings is not None or creating:
        base = (current or {}).get("settings") or DEFAULT_SETTINGS
        out["settings"] = clean_settings(body.settings, base)
    return out


def _without_ids(question: Dict[str, Any]) -> Dict[str, Any]:
    """A question with its ids dropped, so the copy gets fresh ones.

    Two quizzes sharing question ids would share nothing else, and results are
    keyed by them. The right option is carried over by position for the same
    reason the generator names it that way.
    """
    copy = {k: v for k, v in question.items() if k != "id"}
    if question.get("type") == "choice":
        options = question.get("options") or []
        copy["options"] = [{k: v for k, v in o.items() if k != "id"} for o in options]
        copy["correct"] = next(
            (i for i, o in enumerate(options) if o.get("id") == question.get("correct")), None
        )
    return copy


async def _runs(session_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each run with how many took part and how they did."""
    from quiz_service.db import db

    ids = [str(s["_id"]) for s in session_docs]
    tally: Dict[str, List[int]] = {i: [] for i in ids}
    if ids:
        cursor = db.db.quiz_players.find(
            {"session_id": {"$in": ids}, "kicked": False},
            {"session_id": 1, "correct": 1, "order": 1, "answered": 1},
        )
        async for player in cursor:
            total = len(player.get("order") or [])
            if total and player.get("answered"):
                tally[player["session_id"]].append(round(100 * player.get("correct", 0) / total))
            else:
                tally[player["session_id"]].append(-1)
    runs = []
    for session in session_docs:
        scores = tally.get(str(session["_id"]), [])
        played = [s for s in scores if s >= 0]
        runs.append({
            "id": str(session["_id"]),
            "code": session.get("code", ""),
            "status": session.get("status"),
            "classLabel": session.get("class_label", ""),
            "createdAt": iso(session.get("created_at")),
            "startsAt": iso(session.get("starts_at")),
            "endedAt": iso(session.get("ended_at")),
            "players": len(scores),
            "averagePercent": round(sum(played) / len(played)) if played else None,
        })
    return runs


@router.get("/api/quiz/quizzes")
async def list_quizzes(request: Request):
    user = await require_teacher(request)
    owner = str(user["id"])
    docs = await store.list_for(owner)
    latest: Dict[str, Dict[str, Any]] = {}
    for session in await sessions_store.latest_for_owner(owner):
        latest.setdefault(session["quiz_id"], session)
    runs = {r["id"]: r for r in await _runs(list(latest.values()))}
    items = []
    for doc in docs:
        item = store.summary(doc)
        last = latest.get(str(doc["_id"]))
        item["lastRun"] = runs.get(str(last["_id"])) if last else None
        items.append(item)
    return {"items": items}


@router.post("/api/quiz/quizzes", status_code=201)
async def create_quiz(body: QuizBody, request: Request):
    user = await require_teacher(request)
    owner = str(user["id"])
    if await store.count_for(owner) >= MAX_QUIZZES_PER_OWNER:
        raise ApiError(409, f"A library holds {MAX_QUIZZES_PER_OWNER} quizzes. Remove one first.",
                       "too_many_quizzes")
    doc = await store.create(owner, _fields(body))
    return {**store.public(doc), "runs": []}


@router.get("/api/quiz/quizzes/{quiz_id}")
async def read_quiz(quiz_id: str, request: Request):
    user = await require_teacher(request)
    owner = str(user["id"])
    doc = await store.get(quiz_id, owner)
    if not doc:
        raise ApiError(404, "Quiz not found")
    runs = await _runs(await sessions_store.list_for_quiz(quiz_id, owner))
    return {**store.public(doc), "runs": runs}


@router.put("/api/quiz/quizzes/{quiz_id}")
async def update_quiz(quiz_id: str, body: QuizBody, request: Request):
    """The quiz as the editor has it now. Saved as the teacher types.

    Only shape is enforced here - a half-written question is a legitimate
    thing to save. What stops a quiz being played is reported in `problems`
    and enforced when a session is opened, not by refusing the save.
    """
    user = await require_teacher(request)
    owner = str(user["id"])
    current = await store.get(quiz_id, owner)
    if not current:
        raise ApiError(404, "Quiz not found")
    doc = await store.update(quiz_id, owner, _fields(body, current))
    if not doc:
        raise ApiError(404, "Quiz not found")
    return store.public(doc)


@router.post("/api/quiz/quizzes/{quiz_id}/copy", status_code=201)
async def copy_quiz(quiz_id: str, request: Request):
    user = await require_teacher(request)
    owner = str(user["id"])
    source = await store.get(quiz_id, owner)
    if not source:
        raise ApiError(404, "Quiz not found")
    if await store.count_for(owner) >= MAX_QUIZZES_PER_OWNER:
        raise ApiError(409, f"A library holds {MAX_QUIZZES_PER_OWNER} quizzes. Remove one first.",
                       "too_many_quizzes")
    fields = {k: source.get(k) for k in ("subject", "grade", "lang", "topic", "settings")}
    fields["questions"] = clean_questions(
        [_without_ids(q) for q in source.get("questions") or []], MAX_QUESTIONS
    )
    fields["title"] = clean_title(f"{source.get('title', '')} (2)")
    doc = await store.create(owner, fields)
    return {**store.public(doc), "runs": []}


@router.delete("/api/quiz/quizzes/{quiz_id}")
async def delete_quiz(quiz_id: str, request: Request):
    """The quiz, its runs and their answers - results without the quiz they
    belong to would be rows nobody could read."""
    user = await require_teacher(request)
    owner = str(user["id"])
    if not await store.get(quiz_id, owner):
        raise ApiError(404, "Quiz not found")
    session_ids = await sessions_store.ids_for_quiz(quiz_id)
    for session_id in session_ids:
        await lifecycle.end_session(session_id)
    await players_store.delete_for_sessions(session_ids)
    await sessions_store.delete_many(session_ids)
    await store.delete(quiz_id, owner)
    return {"id": quiz_id, "deleted": True}
