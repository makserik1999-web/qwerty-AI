"""Moments in a session's life that more than one caller brings about.

Ending a session happens when the teacher presses End, when the quiz is
deleted, when an account goes, and when a forgotten lobby times out; a
student's clock runs out whether or not their phone is still asking. Each of
those has to leave the same state behind and tell the same people, so each is
written once, here.
"""

import asyncio
from datetime import timedelta
from typing import Any, Dict, Optional

from quiz_service.config import ANSWER_GRACE_SEC, SESSION_MAX_HOURS
from quiz_service.db import aware, iso, now
from quiz_service.hub import hub
from quiz_service.logic import deadline, host_player
from quiz_service.store import players as players_store
from quiz_service.store import sessions as sessions_store

SWEEP_INTERVAL_SEC = 10


async def end_session(session_id: str) -> Optional[Dict[str, Any]]:
    """End an open session. Returns it, or None if it was not open."""
    session = await sessions_store.end(session_id)
    if not session:
        return None
    await players_store.finish_all(session_id, aware(session["ended_at"]))
    event = {
        "type": "status",
        "status": "ended",
        "startsAt": iso(session.get("starts_at")),
        "endedAt": iso(session.get("ended_at")),
        "serverNow": iso(now()),
    }
    await hub.to_hosts(session_id, event)
    await hub.to_players(session_id, event)
    return session


async def finish_player(session: Dict[str, Any], player: Dict[str, Any]) -> None:
    """A student whose time ran out: finished at their deadline, not later.

    Called lazily when their phone next asks, and by the sweep for the phones
    that never ask again - a student who locked the screen still has to show
    as finished on the teacher's board.
    """
    limit = deadline(session, player)
    at = min(now(), limit) if limit else now()
    if await players_store.finish(player["_id"], at):
        player = {**player, "finished_at": at, "streak": 0}
        session_id = str(session["_id"])
        await hub.to_hosts(session_id, {
            "type": "finished",
            "player": host_player(player, session, now()),
        })
        await hub.to_players(session_id, {"type": "refresh"}, str(player["_id"]))


async def sweep_once() -> None:
    stamp = now()
    for session in await sessions_store.open_sessions():
        session_id = str(session["_id"])
        if aware(session["created_at"]) < stamp - timedelta(hours=SESSION_MAX_HOURS):
            await end_session(session_id)
            continue
        if session.get("status") != "running":
            continue
        if not (session.get("settings") or {}).get("timeLimitMin"):
            continue
        for player in await players_store.in_session(session_id):
            if player.get("finished_at"):
                continue
            limit = deadline(session, player)
            if limit and stamp > limit + timedelta(seconds=ANSWER_GRACE_SEC):
                await finish_player(session, player)


async def sweep_loop() -> None:
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad pass must not stop the next
            print(f"[sweep] {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(SWEEP_INTERVAL_SEC)
