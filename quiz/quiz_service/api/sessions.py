"""Running a quiz: open a lobby, start it, end it, read what happened."""

from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from quiz_service import lifecycle, results
from quiz_service.config import COUNTDOWN_SEC, MAX_OPEN_SESSIONS
from quiz_service.db import iso, now
from quiz_service.errors import ApiError
from quiz_service.hub import hub
from quiz_service.identity import require_teacher
from quiz_service.logic import host_state
from quiz_service.questions import clean_settings, problems
from quiz_service.store import players as players_store
from quiz_service.store import quizzes as quizzes_store
from quiz_service.store import sessions as store

router = APIRouter()


class OpenBody(BaseModel):
    settings: Optional[Dict[str, Any]] = None
    classLabel: Optional[str] = None


async def _owned(session_id: str, request: Request) -> Dict[str, Any]:
    user = await require_teacher(request)
    session = await store.get(session_id, str(user["id"]))
    if not session:
        raise ApiError(404, "Session not found")
    return session


async def _state(session: Dict[str, Any]) -> Dict[str, Any]:
    players = await players_store.in_session(str(session["_id"]))
    return host_state(session, players, now())


@router.post("/api/quiz/quizzes/{quiz_id}/sessions", status_code=201)
async def open_session(quiz_id: str, body: OpenBody, request: Request):
    """A lobby with a fresh code. Students can join from this moment."""
    user = await require_teacher(request)
    owner = str(user["id"])
    quiz = await quizzes_store.get(quiz_id, owner)
    if not quiz:
        raise ApiError(404, "Quiz not found")

    questions = quiz.get("questions") or []
    if not questions or any(problems(q) for q in questions):
        # The editor shows which question and why; this is the backstop for
        # a client that did not.
        raise ApiError(409, "Some questions are not finished yet", "quiz_not_ready")
    if await store.count_open(owner) >= MAX_OPEN_SESSIONS:
        raise ApiError(409, f"{MAX_OPEN_SESSIONS} quizzes are already open. End one first.",
                       "too_many_open")

    settings = clean_settings(body.settings, quiz.get("settings"))
    # What was chosen this time is the default next time.
    await quizzes_store.update(quiz_id, owner, {"settings": settings})
    label = (body.classLabel or "").strip()[:40]
    session = await store.create(quiz, owner, settings, label)
    return await _state(session)


@router.get("/api/quiz/sessions/{session_id}")
async def read_session(session_id: str, request: Request):
    return await _state(await _owned(session_id, request))


@router.post("/api/quiz/sessions/{session_id}/start")
async def start_session(session_id: str, request: Request):
    """Everyone in the lobby starts together, after the countdown.

    The start is a moment in the future rather than now: every phone and the
    projector count down to the same server time, so the first question
    appears everywhere at once instead of in the order the sockets happen to
    be written to.
    """
    session = await _owned(session_id, request)
    if session.get("status") != "lobby":
        raise ApiError(409, "This quiz has already started", "not_in_lobby")
    if not await players_store.count(session_id):
        raise ApiError(409, "Nobody has joined yet", "empty_lobby")

    starts_at = now() + timedelta(seconds=COUNTDOWN_SEC)
    started = await store.start(session_id, starts_at)
    if not started:
        raise ApiError(409, "This quiz has already started", "not_in_lobby")
    await players_store.start_waiting(session_id, starts_at)

    event = {
        "type": "status",
        "status": "running",
        "startsAt": iso(starts_at),
        "serverNow": iso(now()),
    }
    await hub.to_hosts(session_id, event)
    await hub.to_players(session_id, event)
    return await _state(started)


@router.post("/api/quiz/sessions/{session_id}/end")
async def end_session(session_id: str, request: Request):
    session = await _owned(session_id, request)
    ended = await lifecycle.end_session(session_id)
    return await _state(ended or session)


@router.delete("/api/quiz/sessions/{session_id}/players/{player_id}")
async def remove_player(session_id: str, player_id: str, request: Request):
    """Take somebody out - the name nobody should have typed, usually."""
    await _owned(session_id, request)
    player = await players_store.kick(session_id, player_id)
    if not player:
        raise ApiError(404, "Player not found")
    await hub.to_players(session_id, {"type": "kicked"}, player_id)
    await hub.close_player(session_id, player_id, 4403)
    await hub.to_hosts(session_id, {"type": "left", "playerId": player_id})
    await hub.to_players(session_id, {
        "type": "lobby", "players": await players_store.count(session_id),
    })
    return {"id": player_id, "removed": True}


@router.get("/api/quiz/sessions/{session_id}/results")
async def session_results(session_id: str, request: Request):
    session = await _owned(session_id, request)
    players = await players_store.in_session(session_id, include_kicked=True)
    return results.build(session, players)


@router.delete("/api/quiz/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    await _owned(session_id, request)
    await lifecycle.end_session(session_id)
    await players_store.delete_for_sessions([session_id])
    await store.delete_many([session_id])
    return {"id": session_id, "deleted": True}
