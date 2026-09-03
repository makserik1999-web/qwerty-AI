"""Connection registries for UI clients and the AI agent.

Also owns the pending-request bookkeeping: the TTL sweep and the notification
sent to waiting users when the agent goes away.
"""

import asyncio
import time
import uuid
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
        # Embedding requests waiting for the agent to answer. Separate from
        # pending_requests: those are user-visible generations with a quota
        # and a chat behind them, these are a sub-second internal lookup.
        self.pending_embeddings: Dict[str, asyncio.Future] = {}
        # Declared by the agent at handshake. Empty means an older build
        # that only understands generation requests.
        self.agent_features: set = set()

    async def request_embedding(self, text: str, timeout: float) -> Optional[dict]:
        """Ask the agent for a question's vector and language.

        Returns None on any failure - no agent, a timeout, a refusal. The
        semantic layer is an optimisation, so its absence must cost a cache
        miss and never an answer.
        """
        if not self.agent_connection or "embed" not in self.agent_features:
            return None

        request_id = f"embed-{uuid.uuid4().hex[:16]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self.pending_embeddings[request_id] = future
        try:
            await self.agent_connection.send_json(
                {"type": "embed", "request_id": request_id, "text": text}
            )
            return await asyncio.wait_for(future, timeout=timeout)
        except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
            if not isinstance(e, asyncio.TimeoutError):
                print(f"embedding request failed: {type(e).__name__}: {e}")
            return None
        finally:
            self.pending_embeddings.pop(request_id, None)

    def resolve_embedding(self, request_id: str, payload: Optional[dict]) -> bool:
        """Hand an agent's reply to whoever asked for it."""
        future = self.pending_embeddings.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(payload)
        return True

    def in_flight_for(self, user_id: str) -> int:
        """How many generations this user has running right now."""
        return sum(
            1 for r in self.pending_requests.values() if r.get("user_id") == user_id
        )

    def queue_depth(self) -> int:
        """Everything waiting on the agent, from every user."""
        return len(self.pending_requests)

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
                            text: Optional[str], screenshots: List[Dict[str, Any]],
                            narration: bool = True, narration_voice: str = "aigul"):
        if not self.agent_connection:
            raise RuntimeError("AI Agent not connected")

        image_data = None
        if screenshots:
            image_data = screenshots[0].get("image_base64")

        await self.agent_connection.send_json({
            "request_id": request_id,
            "text": text,
            "image_data": image_data,
            # Already validated against the closed set in ws/ui.py - the agent
            # trusts these because the backend, not the client, chose them.
            "narration": narration,
            "narration_voice": narration_voice,
        })

    def get_request_info(self, request_id: str, pop: bool = True) -> Optional[dict]:
        if pop:
            return self.pending_requests.pop(request_id, None)
        return self.pending_requests.get(request_id)


ui_manager = UIConnectionManager()
agent_manager = AgentConnectionManager()


async def _refund_quietly(request_id: str) -> None:
    """Return the quota for a generation that produced nothing.

    Imported inside the function: `app.services.quota` imports `app.db`, which
    imports this module for the sweep loop, so a top-level import would close
    the circle.
    """
    try:
        from app.services.quota import refund

        await refund(request_id)
    except Exception as e:  # noqa: BLE001 - a refund must never break a sweep
        print(f"quota refund failed for {request_id}: {type(e).__name__}: {e}")


async def _notify_pending_failures(message: str):
    """Tell every user with an in-flight request that the agent went away."""
    for request_id, info in list(agent_manager.pending_requests.items()):
        user_id = info.get("user_id")
        chat_id = info.get("chat_id")
        agent_manager.pending_requests.pop(request_id, None)
        await _refund_quietly(request_id)
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
                await _refund_quietly(rid)
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
