"""Connection registries for UI clients and the AI agent.

Also owns the pending-request bookkeeping: the TTL sweep and the notification
sent to waiting users when the agent goes away.
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

from app.config import (
    AGENT_ACK_TIMEOUT_SEC,
    PENDING_REQUESTS_TTL_SEC,
    PENDING_SWEEP_INTERVAL_SEC,
)


class AgentDeliveryError(RuntimeError):
    """The request never reached the agent.

    Distinguished from every other send failure because it is the one the
    person who asked can act on: nothing was rendered, nothing was charged,
    and asking again is the right thing to do.
    """


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

    def disconnect(self, user_id: str, websocket: Optional[WebSocket] = None):
        """Forget this socket - but only if it is still the registered one.

        A reconnect closes the old socket and opens a new one, and the old
        one's cleanup usually runs AFTER the new one has registered. Popping
        by user id alone therefore deleted the socket that had just taken
        over: it stayed open, the browser saw no disconnect, and every answer
        for that person went nowhere, because delivery is a lookup in this
        map. The symptom was a question that reached the agent, rendered, and
        never came back - with the interface still showing "connected".
        """
        current = self.active_connections.get(user_id)
        if websocket is not None and current is not websocket:
            # A newer socket owns this user now. Leave it alone.
            return
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
        self.pending_assessments: Dict[str, asyncio.Future] = {}
        # Sends waiting for the agent to say it has the request. Writing to a
        # socket proves nothing: a TCP connection whose far end has gone still
        # accepts bytes into the kernel buffer, so send_json succeeds and the
        # request is never seen by anybody. Only the agent's own reply proves
        # delivery, and this is where the sender waits for it.
        self.pending_acks: Dict[str, asyncio.Future] = {}
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

    async def request_assessment(self, spec: dict, timeout: float) -> dict:
        """Ask the agent to write one assessment paper.

        Kept separate from request_embedding, which swallows every failure and
        returns None: an embedding is an optimisation and its absence costs a
        cache miss, while this is the teacher's actual request. They have to be
        told the difference between "the agent is down" and "come back in a
        minute", so the reasons are distinguished and returned.
        """
        if not self.agent_connection:
            return {"error": "agent_unavailable"}
        if "assessment" not in self.agent_features:
            # An older agent that only knows how to render videos.
            return {"error": "agent_unavailable"}

        request_id = f"assess-{uuid.uuid4().hex[:16]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self.pending_assessments[request_id] = future
        try:
            await self.agent_connection.send_json(
                {"type": "assessment", "request_id": request_id, "spec": spec}
            )
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": "timeout"}
        except Exception as e:  # noqa: BLE001
            print(f"assessment request failed: {type(e).__name__}: {e}")
            return {"error": "agent_unavailable"}
        finally:
            self.pending_assessments.pop(request_id, None)

    def resolve_assessment(self, request_id: str, payload: dict) -> bool:
        """Hand an agent's paper to whoever asked for it."""
        future = self.pending_assessments.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(payload)
        return True

    def resolve_ack(self, request_id: str) -> bool:
        """The agent has this request; release whoever sent it."""
        future = self.pending_acks.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(True)
        return True

    def _fail_pending_acks(self) -> None:
        """The socket has gone, so nothing still waiting on it will be acked.

        Without this every sender in flight would sit out the full ack timeout
        for an answer that cannot come - the connection is already known to be
        dead, and making people wait to be told so is the bug over again.
        """
        for request_id, future in list(self.pending_acks.items()):
            self.pending_acks.pop(request_id, None)
            if not future.done():
                future.set_result(False)

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
            # Anything waiting for an ack was written to the socket just
            # closed. A reconnecting agent did not read those frames, so no
            # ack for them is ever coming.
            self._fail_pending_acks()
        self.agent_connection = websocket
        print("AI Agent connected")

    def disconnect(self, websocket: Optional[WebSocket] = None):
        """Same race as the UI manager, with worse consequences.

        An agent reconnect that cleared the new connection would leave the
        backend believing no agent is available while one is sitting there -
        and would fire _notify_pending_failures at everyone waiting.
        """
        if websocket is not None and self.agent_connection is not websocket:
            return
        self.agent_connection = None
        self._fail_pending_acks()
        print("AI Agent disconnected")

    async def send_to_agent(self, request_id: str, user_id: str, chat_id: str,
                            text: Optional[str], screenshots: List[Dict[str, Any]],
                            narration: bool = True, narration_voice: str = "aigul",
                            video_length: str = "", effort: str = ""):
        """Hand one question to the agent, and wait to be told it arrived.

        The wait is the point. This used to end at send_json, which reports
        success for a socket whose far end has gone: the kernel takes the
        bytes and there is nobody to read them. The request was then charged
        to the user's quota and entered in pending_requests, where it sat as a
        generation in progress that no machine was working on - blocking every
        later question under GENERATION_MAX_CONCURRENT until the half-hour TTL
        sweep, with an indicator spinning the whole time. Any drop of the agent
        connection reproduced it; one did.

        Only an agent that declares `ack` is waited for, so an older build
        still works exactly as before rather than failing every request.
        """
        if not self.agent_connection:
            raise RuntimeError("AI Agent not connected")

        image_data = None
        if screenshots:
            image_data = screenshots[0].get("image_base64")

        want_ack = "ack" in self.agent_features
        ack: Optional[asyncio.Future] = None
        if want_ack:
            ack = asyncio.get_running_loop().create_future()
            # Registered BEFORE the send: the agent answers off the wire, and
            # a reply arriving before this map knew to expect it would be
            # dropped as unknown and time out a request that had in fact
            # landed.
            self.pending_acks[request_id] = ack

        try:
            await self.agent_connection.send_json({
                "request_id": request_id,
                "text": text,
                "image_data": image_data,
                # Already validated against the closed set in ws/ui.py - the
                # agent trusts these because the backend, not the client,
                # chose them.
                "narration": narration,
                "narration_voice": narration_voice,
                "video_length": video_length,
                "effort": effort,
            })

            if ack is not None:
                try:
                    delivered = await asyncio.wait_for(ack, AGENT_ACK_TIMEOUT_SEC)
                except asyncio.TimeoutError:
                    delivered = False
                if not delivered:
                    raise AgentDeliveryError(
                        "the agent never confirmed it received the request"
                    )
        finally:
            self.pending_acks.pop(request_id, None)

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
    """Tell every user with an in-flight request that the agent went away.

    The entry is marked rather than dropped. A request is only in this table
    while the agent is working on it, and the work does not stop because the
    socket did: the agent goes on rendering, finishes, reconnects and delivers.
    Dropping the entry here threw that away - a video that had been rendered
    and written to disk was discarded because nothing remembered who had asked
    for it.

    The person is still told at once, and still refunded, because they should
    not sit watching an indicator for a connection that has gone. If the answer
    does arrive afterwards it is saved and cached, so asking again returns it
    immediately instead of rendering it a second time.

    The TTL sweep clears these on its own; `notified` stops it saying so twice.
    """
    for request_id, info in list(agent_manager.pending_requests.items()):
        user_id = info.get("user_id")
        chat_id = info.get("chat_id")
        if info.get("notified"):
            continue
        info["notified"] = True
        await _refund_quietly(request_id)
        if user_id:
            await ui_manager.send_to_user(user_id, {
                "type": "error",
                "data": {"message": message, "chat_id": chat_id},
            })


async def _sweep_once():
    """One pass of the TTL sweep. Separate so a test can run it on demand."""
    now = time.monotonic()
    stale = [
        rid for rid, info in agent_manager.pending_requests.items()
        if now - info.get("created_at", now) > PENDING_REQUESTS_TTL_SEC
    ]
    for rid in stale:
        info = agent_manager.pending_requests.pop(rid, None)
        await _refund_quietly(rid)
        if info and info.get("notified"):
            # Already reported when the agent dropped; this is only the entry
            # being cleared out, and saying so again would be a second failure
            # for one question.
            continue
        if info and info.get("user_id"):
            await ui_manager.send_to_user(info["user_id"], {
                "type": "error",
                "data": {
                    "message": "Processing timed out. Please try again.",
                    "chat_id": info.get("chat_id"),
                },
            })


async def _sweep_pending_requests_loop():
    """TTL sweep for pending_requests (agent died mid-request -> no leak)."""
    while True:
        await asyncio.sleep(PENDING_SWEEP_INTERVAL_SEC)
        try:
            await _sweep_once()
        except Exception as e:
            print(f"pending sweep error: {type(e).__name__}: {e}")
