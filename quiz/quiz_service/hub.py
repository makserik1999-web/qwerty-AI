"""Who is watching which session, and telling them when it changes.

The teacher's board and every student's phone hold a socket here. Answers
arrive over HTTP; this only fans the consequences out. In memory, because
there is one replica - a second one would put this behind Redis pub/sub, and
nothing outside this module would have to change.
"""

from collections import defaultdict
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket


class Hub:
    def __init__(self) -> None:
        self._hosts: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._players: Dict[str, Dict[str, Set[WebSocket]]] = defaultdict(
            lambda: defaultdict(set)
        )

    def add_host(self, session_id: str, socket: WebSocket) -> None:
        self._hosts[session_id].add(socket)

    def remove_host(self, session_id: str, socket: WebSocket) -> None:
        sockets = self._hosts.get(session_id)
        if sockets is not None:
            sockets.discard(socket)
            if not sockets:
                self._hosts.pop(session_id, None)

    def add_player(self, session_id: str, player_id: str, socket: WebSocket) -> None:
        self._players[session_id][player_id].add(socket)

    def remove_player(self, session_id: str, player_id: str, socket: WebSocket) -> None:
        players = self._players.get(session_id)
        if not players:
            return
        sockets = players.get(player_id)
        if sockets is not None:
            sockets.discard(socket)
            if not sockets:
                players.pop(player_id, None)
        if not players:
            self._players.pop(session_id, None)

    async def to_hosts(self, session_id: str, event: Dict[str, Any]) -> None:
        for socket in list(self._hosts.get(session_id, ())):
            await self._send(socket, event)

    async def to_players(self, session_id: str, event: Dict[str, Any],
                         player_id: Optional[str] = None) -> None:
        players = self._players.get(session_id, {})
        targets = [player_id] if player_id else list(players)
        for pid in targets:
            for socket in list(players.get(pid, ())):
                await self._send(socket, event)

    async def close_player(self, session_id: str, player_id: str, code: int) -> None:
        for socket in list(self._players.get(session_id, {}).get(player_id, ())):
            try:
                await socket.close(code=code)
            except Exception:  # noqa: BLE001 - already gone
                pass

    @staticmethod
    async def _send(socket: WebSocket, event: Dict[str, Any]) -> None:
        # A socket that has gone is noticed by its own receive loop, which
        # unregisters it; failing here must not stop the others being told.
        try:
            await socket.send_json(event)
        except Exception:  # noqa: BLE001
            pass


hub = Hub()
