"""Live channels: the teacher's board, and each student's phone.

Both are for being told, not for doing - answers and controls go over HTTP,
where they are idempotent and easy to retry. A socket that drops loses
nothing: on reconnect each side asks for a snapshot and carries on.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from quiz_service.config import CORS_ORIGINS
from quiz_service.db import now
from quiz_service.errors import ApiError
from quiz_service.hub import hub
from quiz_service.identity import teacher_for_socket
from quiz_service.logic import host_state, player_state
from quiz_service.store import players as players_store
from quiz_service.store import sessions as sessions_store

router = APIRouter()

HELLO_TIMEOUT_SEC = 10


def _origin_ok(websocket: WebSocket) -> bool:
    origin: Optional[str] = websocket.headers.get("origin")
    # Browsers always send one; a client that sends none is not a browser
    # carrying somebody's cookie, which is what this check is for.
    return not origin or origin in CORS_ORIGINS


async def _pump(websocket: WebSocket) -> None:
    """Answer pings until the socket goes. Nothing else is accepted."""
    while True:
        message = await websocket.receive_json()
        if isinstance(message, dict) and message.get("type") == "ping":
            await websocket.send_json({"type": "pong"})


@router.websocket("/ws/quiz/host/{session_id}")
async def host_socket(websocket: WebSocket, session_id: str):
    if not _origin_ok(websocket):
        await websocket.close(code=1008)
        return
    try:
        user = await teacher_for_socket(websocket)
    except ApiError:
        await websocket.close(code=1008)
        return
    session = await sessions_store.get(session_id, str(user["id"]))
    if not session:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    hub.add_host(session_id, websocket)
    try:
        players = await players_store.in_session(session_id)
        await websocket.send_json({"type": "snapshot", "state": host_state(session, players, now())})
        await _pump(websocket)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        hub.remove_host(session_id, websocket)


@router.websocket("/ws/quiz/play")
async def player_socket(websocket: WebSocket):
    """The token comes in the first message, not the URL - a URL ends up in
    access logs, and this token is the student's whole identity.

    No Origin check here, unlike the teacher's socket. That check exists
    because a cookie rides along on its own; a token has to be sent, and a
    page that does not know it cannot send it. Checking anyway would shut out
    the case it cannot tell from an attack - a class joining a stack run on
    the school network, at an address nobody put on the allowlist.
    """
    await websocket.accept()
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=HELLO_TIMEOUT_SEC)
    except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError, ValueError):
        await websocket.close(code=4400)
        return
    token = hello.get("token") if isinstance(hello, dict) else None
    player = await players_store.by_token(token or "")
    if not player or player.get("kicked"):
        await websocket.close(code=4401)
        return
    session = await sessions_store.get(player["session_id"])
    if not session:
        await websocket.close(code=4410)
        return

    session_id = str(session["_id"])
    player_id = str(player["_id"])
    hub.add_player(session_id, player_id, websocket)
    try:
        players = await players_store.in_session(session_id)
        await websocket.send_json({
            "type": "state",
            "state": player_state(session, player, now(), players),
            "players": len(players),
        })
        await _pump(websocket)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        hub.remove_player(session_id, player_id, websocket)
