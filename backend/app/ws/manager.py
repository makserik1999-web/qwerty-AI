"""Connection registries for UI clients and the AI agent.

Also owns the pending-request bookkeeping: the TTL sweep and the notification
sent to waiting users when the agent goes away.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

from app.config import PENDING_REQUESTS_TTL_SEC, PENDING_SWEEP_INTERVAL_SEC


class UIConnectionManager:
    """Manages WebSocket connections from UI clients."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        # Replace any previous socket for the same user (avoid leaks/races)
        old = self.active_connections.get(user_id)
        if old and old is not websocket:
            try:
                await old.close(code=1001, reason="replaced by new connection")
            except Exception:
                pass
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"UI client connected: user_id={user_id}")

    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)
        print(f"UI client disconnected: user_id={user_id}")

    async def send_to_user(self, user_id: str, message: dict):
        ws = self.active_connections.get(user_id)
        if ws is None:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception as e:
            print(f"Error sending to user {user_id}: {type(e).__name__}")
            return False

    def get_connection(self, user_id: str) -> Optional[WebSocket]:
        return self.active_connections.get(user_id)


class AgentConnectionManager:
    """Manages WebSocket connection to AI Agent."""

    def __init__(self):
        self.agent_connection: Optional[WebSocket] = None
        self.pending_requests: Dict[str, dict] = {}

    async def connect(self, websocket: WebSocket):
        old = self.agent_connection
        if old and old is not websocket:
            try:
                await old.close(code=1001, reason="replaced by new agent")
            except Exception:
                pass
        self.agent_connection = websocket
        print("AI Agent connected")

    def disconnect(self):
        self.agent_connection = None
        print("AI Agent disconnected")

    async def send_to_agent(self, request_id: str, user_id: str, chat_id: str,
                            text: Optional[str], screenshots: List[Dict[str, Any]]):
        if not self.agent_connection:
            raise RuntimeError("AI Agent not connected")

        image_data = None
        if screenshots:
            image_data = screenshots[0].get("image_base64")

        await self.agent_connection.send_json({
            "request_id": request_id,
            "text": text,
            "image_data": image_data,
        })

    def get_request_info(self, request_id: str, pop: bool = True) -> Optional[dict]:
        if pop:
            return self.pending_requests.pop(request_id, None)
        return self.pending_requests.get(request_id)


ui_manager = UIConnectionManager()
agent_manager = AgentConnectionManager()


async def _notify_pending_failures(message: str):
    """Tell every user with an in-flight request that the agent went away."""
    for request_id, info in list(agent_manager.pending_requests.items()):
        user_id = info.get("user_id")
        chat_id = info.get("chat_id")
        agent_manager.pending_requests.pop(request_id, None)
        if user_id:
            await ui_manager.send_to_user(user_id, {
                "type": "error",
                "data": {"message": message, "chat_id": chat_id},
            })


async def _sweep_pending_requests_loop():
    """TTL sweep for pending_requests (agent died mid-request -> no leak)."""
    while True:
        await asyncio.sleep(PENDING_SWEEP_INTERVAL_SEC)
        try:
            now = time.monotonic()
            stale = [
                rid for rid, info in agent_manager.pending_requests.items()
                if now - info.get("created_at", now) > PENDING_REQUESTS_TTL_SEC
            ]
            for rid in stale:
                info = agent_manager.pending_requests.pop(rid, None)
                if info and info.get("user_id"):
                    await ui_manager.send_to_user(info["user_id"], {
                        "type": "error",
                        "data": {
                            "message": "Processing timed out. Please try again.",
                            "chat_id": info.get("chat_id"),
                        },
                    })
        except Exception as e:
            print(f"pending sweep error: {type(e).__name__}: {e}")
