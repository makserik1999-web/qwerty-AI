"""The student's side: find a quiz by its code, join it, answer it.

No account. A student is whoever holds the token the join handed out, sent
in the `X-Player-Token` header - not a cookie, so it never rides along with a
request the student did not mean to make, and never mixes with the session
cookie of somebody signed in on the same browser.
"""

import random
import re
import unicodedata
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from quiz_service import lifecycle
from quiz_service.codes import normalize
from quiz_service.config import (
    COUNTDOWN_SEC,
    JOIN_MAX_PER_IP,
    LOOKUP_MAX_PER_IP,
    MAX_PLAYERS,
)
from quiz_service.db import aware, now
from quiz_service.errors import ApiError
from quiz_service.hub import hub
from quiz_service.limits import Window, client_ip
from quiz_service.logic import (
    current_question,
    host_player,
    player_state,
    score,
    status,
)
from quiz_service.questions import mark, option_order, reveal
from quiz_service.store import players as players_store
from quiz_service.store import sessions as sessions_store

router = APIRouter()

join_window = Window(JOIN_MAX_PER_IP, 600)
lookup_window = Window(LOOKUP_MAX_PER_IP, 600)

MAX_NAME = 24
_CONTROL = re.compile(r"[\u0000-\u001f\u007f-\u009f​-‏ -‮⁠-⁯]")


class JoinBody(BaseModel):
    name: str


class AnswerBody(BaseModel):
    questionId: str
    optionId: Optional[str] = None
    text: Optional[str] = None
    skip: bool = False


def clean_name(raw: str) -> str:
    """A display name: printable, single-spaced, short enough for a chip."""
    name = unicodedata.normalize("NFC", raw or "")
    name = _CONTROL.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:MAX_NAME].strip()


async def _session_for(code_raw: str) -> Dict[str, Any]:
    code = normalize(code_raw)
    session = await sessions_store.get_open_by_code(code) if code else None
    if not session:
        raise ApiError(404, "No open quiz has this code", "no_such_code")
    return session


async def _player(request: Request) -> Dict[str, Any]:
    token = request.headers.get("x-player-token", "")
    player = await players_store.by_token(token)
    if not player:
        raise ApiError(401, "This phone is not in a quiz", "player_unknown")
    return player


async def _state_of(player: Dict[str, Any]) -> Dict[str, Any]:
    """The player's state, finishing them first if their time ran out.

    Lazily: nothing marks a student finished at the exact second their clock
    hits zero, so whoever asks first - this, or the sweep - does it.
    """
    session = await sessions_store.get(player["session_id"])
    if not session:
        raise ApiError(410, "This quiz no longer exists", "session_gone")
    at = now()
    if status(session, player, at) == "finished" and not player.get("finished_at") \
            and not player.get("kicked"):
        await lifecycle.finish_player(session, player)
        player = await players_store.get(str(player["_id"])) or player
    players = await players_store.in_session(str(session["_id"]))
    return player_state(session, player, at, players)


@router.get("/api/play/code/{code}")
async def lookup(code: str, request: Request):
    """What the join screen shows before anybody types a name."""
    if not lookup_window.allow(client_ip(request)):
        raise ApiError(429, "Too many attempts. Wait a minute.", "slow_down")
    session = await _session_for(code)
    settings = session.get("settings") or {}
    joinable = session["status"] == "lobby" or bool(settings.get("lateJoin", True))
    return {
        "code": session["code"],
        "title": session.get("title", ""),
        "status": session["status"],
        "questionCount": len(session.get("questions") or []),
        "timeLimitMin": settings.get("timeLimitMin", 0),
        "players": await players_store.count(str(session["_id"])),
        "joinable": joinable,
    }


@router.post("/api/play/code/{code}/join", status_code=201)
async def join(code: str, body: JoinBody, request: Request):
    if not join_window.allow(client_ip(request)):
        raise ApiError(429, "Too many attempts. Wait a minute.", "slow_down")
    session = await _session_for(code)
    session_id = str(session["_id"])
    settings = session.get("settings") or {}

    if session["status"] == "running" and not settings.get("lateJoin", True):
        raise ApiError(409, "This quiz has already started", "late_join_closed")
    name = clean_name(body.name)
    if not name:
        raise ApiError(400, "Type a name", "no_name")
    if await players_store.count(session_id) >= MAX_PLAYERS:
        raise ApiError(409, "This quiz is full", "session_full")

    # Two students with one name get told apart rather than turned away: a
    # child who is refused their own name does not know what to type instead.
    unique = name
    suffix = 2
    while await players_store.name_taken(session_id, unique):
        unique = f"{name[:MAX_NAME - 3]} {suffix}"
        suffix += 1

    questions = session.get("questions") or []
    order = [q["id"] for q in questions]
    if settings.get("shuffleQuestions", True):
        random.SystemRandom().shuffle(order)
    orders = {
        q["id"]: option_order(q, bool(settings.get("shuffleOptions", True)))
        for q in questions if q["type"] == "choice"
    }
    # A late joiner gets a countdown of their own rather than a question
    # thrown at them mid-sentence.
    started_at = None
    if session["status"] == "running":
        started_at = now() + timedelta(seconds=COUNTDOWN_SEC)

    player = await players_store.create(session_id, unique, order, orders, started_at)
    token = player.pop("token")

    await hub.to_hosts(session_id, {"type": "joined", "player": host_player(player, session, now())})
    await hub.to_players(session_id, {"type": "lobby", "players": await players_store.count(session_id)})

    players = await players_store.in_session(session_id)
    return {"token": token, "state": player_state(session, player, now(), players)}


@router.get("/api/play/state")
async def read_state(request: Request):
    return await _state_of(await _player(request))


@router.post("/api/play/answer")
async def answer(body: AnswerBody, request: Request):
    player = await _player(request)
    session = await sessions_store.get(player["session_id"])
    if not session:
        raise ApiError(410, "This quiz no longer exists", "session_gone")

    at = now()
    if status(session, player, at) != "playing":
        raise ApiError(409, "Not answering right now", "not_playing")
    question = current_question(session, player)
    if question is None or question["id"] != body.questionId:
        # The phone is behind - a retry of an answer that already landed, or
        # a second tab. It reloads its state and carries on.
        raise ApiError(409, "That question is not the current one", "not_current")

    option_id = None
    text = None
    if not body.skip:
        if question["type"] == "choice":
            ids = {o["id"] for o in question.get("options") or []}
            if body.optionId not in ids:
                raise ApiError(400, "Unknown option", "bad_option")
            option_id = body.optionId
        else:
            text = (body.text or "").strip()[:60]
            if not text:
                raise ApiError(400, "Type an answer, or skip", "no_text")

    correct = False if body.skip else mark(question, option_id, text)
    points, streak = score(correct, int(player.get("streak") or 0))
    since = aware(player.get("last_answer_at")) or aware(player.get("started_at")) or at
    entry = {
        "option": option_id,
        "text": text,
        "skipped": body.skip,
        "correct": correct,
        "points": points,
        "ms": max(0, int((at - since).total_seconds() * 1000)),
        "at": at,
    }
    finished = int(player.get("answered") or 0) + 1 >= len(player.get("order") or [])
    if not await players_store.record_answer(player, question["id"], entry, points, streak, finished):
        raise ApiError(409, "That question is not the current one", "not_current")

    updated = await players_store.get(str(player["_id"])) or player
    session_id = str(session["_id"])
    await hub.to_hosts(session_id, {
        "type": "answer",
        "player": host_player(updated, session, now()),
        "questionId": question["id"],
        "optionId": option_id,
        "correct": correct,
    })

    players = await players_store.in_session(session_id)
    state = player_state(session, updated, now(), players)
    show = bool((session.get("settings") or {}).get("showResults", True))
    return {
        "correct": correct if show else None,
        "points": points if show else None,
        "reveal": reveal(question) if show else None,
        "state": state,
    }
