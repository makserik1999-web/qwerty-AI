"""The agent channel: authenticated handshake, then request/response relay."""

import asyncio
import json
import os
import secrets
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import (
    _SAFE_MEDIA_RE,
    AGENT_HANDSHAKE_TIMEOUT_SEC,
    AGENT_SECRET,
    CACHE_ENABLED,
)
from app.repositories.messages import save_message
from app.services import cache_service, jobs, plans, quota, topic_cache, usage_log
from app.ws.manager import _notify_pending_failures, agent_manager, ui_manager

router = APIRouter()


def _number(value, cap: float = 10**9):
    """A count or a duration from the agent, or None. Never trusted to be a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, min(cap, value))


@router.websocket("/ws/agent")
async def websocket_agent_endpoint(websocket: WebSocket):
    """WebSocket endpoint for AI Agent, protected by AGENT_SECRET handshake."""
    await websocket.accept()
    authed = False
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=AGENT_HANDSHAKE_TIMEOUT_SEC
        )
        data = json.loads(raw)
        if (
            data.get("type") == "auth"
            and AGENT_SECRET
            and secrets.compare_digest(str(data.get("token") or ""), AGENT_SECRET)
        ):
            authed = True
            features = data.get("features")
            agent_manager.agent_features = (
                {str(f) for f in features} if isinstance(features, list) else set()
            )
            await websocket.send_json({"type": "auth_ok"})
            print(f"AI Agent authenticated (features: "
                  f"{sorted(agent_manager.agent_features) or 'none'})")
        else:
            print("Agent handshake failed: wrong or missing AGENT_SECRET")
            await websocket.close(code=1008, reason="auth failed")
            return
    except Exception as e:
        print(f"Agent handshake error: {type(e).__name__}: {e}")
        try:
            await websocket.close(code=1008, reason="handshake failed")
        except Exception:
            pass
        return

    try:
        await agent_manager.connect(websocket)
    except Exception as e:
        print(f"Agent manager connect error: {e}")
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except Exception:
                print("Agent sent non-JSON message; ignoring")
                continue
            if not authed:
                continue
            agent_manager.last_seen = time.time()

            # The agent's status, twice a minute: for the system page, nothing else.
            if data.get("type") == "heartbeat":
                agent_manager.heartbeat = {
                    "at": time.time(),
                    "busy": bool(data.get("busy")),
                    "queue": _number(data.get("queue"), 10_000),
                    "held": _number(data.get("held"), 10_000),
                    "uptime_sec": _number(data.get("uptime_sec")),
                }
                continue

            request_id = data.get("request_id")

            # "I have it." Not an answer and not progress - the proof that the
            # frame reached a process rather than a socket buffer, which is
            # the only thing a successful send does not tell us.
            if data.get("type") == "ack":
                if request_id:
                    agent_manager.resolve_ack(request_id)
                continue

            # Embedding replies are internal lookups, not answers to a user:
            # they have no chat, no message and no quota behind them.
            if data.get("type") == "classify_result":
                agent_manager.resolve_classification(
                    request_id,
                    None if data.get("error") else {
                        "specificity": data.get("specificity") or "specific",
                        "topic_id": data.get("topic_id"),
                        "language": data.get("language") or "",
                    },
                )
                continue

            if data.get("type") == "embed_result":
                agent_manager.resolve_embedding(
                    request_id,
                    None if data.get("error") else {
                        "vector": data.get("vector") or [],
                        "language": data.get("language") or "",
                        "model": data.get("model") or "",
                    },
                )
                continue

            # A stage report, not an answer: the request stays open and
            # nothing is saved. Forwarded so the person watching the three
            # steps sees them move instead of one indicator for ninety
            # seconds. `pop=False` matters - popping here would leave the real
            # answer with nowhere to go.
            if data.get("type") == "progress":
                stage = str(data.get("stage") or "")
                if stage in ("understand", "write", "render") and request_id:
                    info = agent_manager.get_request_info(request_id, pop=False)
                    if info:
                        await jobs.running(request_id)
                        await ui_manager.send_to_user(info["user_id"], {
                            "type": "progress",
                            "data": {"chat_id": info["chat_id"], "stage": stage},
                        })
                continue

            # A written document, not an answer to a chat message: no chat, no
            # saved message, no quota of its own.
            #
            # The allowed keys are listed rather than the frame passed through
            # whole: this is the one place a reply from the agent turns into a
            # value the API returns, and a field nobody asked for should not
            # make that trip just because the agent sent it.
            if data.get("type") in ("assessment_result", "lesson_plan_result",
                                    "quiz_result"):
                agent_manager.resolve_assessment(request_id, {
                    k: v for k, v in data.items()
                    if k in ("questions", "total_marks", "requested",
                             "plan", "minutes_planned", "dropped_codes",
                             "dropped", "error")
                })
                continue

            response_text = data.get("text", "")
            status = data.get("status", "complete")
            video_path = data.get("video_path", "")
            # Free text from the model, passed through rather than validated:
            # it labels a badge, and the client maps what it recognises. A
            # closed set here would just be a second place to keep in step.
            subject = str(data.get("subject") or "")[:40]
            error = data.get("error", "")

            if not request_id:
                print("Agent sent message without request_id")
                continue

            pop_request = (status == "complete" or status == "error")
            request_info = agent_manager.get_request_info(request_id, pop=pop_request)

            if not request_info:
                print(f"Unknown request_id: {request_id}")
                continue

            user_id = request_info["user_id"]
            chat_id = request_info["chat_id"]

            if status == "error":
                # Give the quota back: charging for a video the user never
                # received is charging them for our failure.
                try:
                    await quota.refund(request_id)
                except Exception as e:
                    print(f"quota refund failed: {type(e).__name__}: {e}")
                await plans.release(request_id)
                await usage_log.log(user_id, "explanation", ok=False)
                await jobs.finish(request_id, ok=False,
                                  error_type=str(data.get("error_type") or "agent_error"),
                                  render_sec=_number(data.get("elapsed_sec")),
                                  tts_chars=_number(data.get("tts_chars")) or 0)
                await ui_manager.send_to_user(user_id, {
                    "type": "error",
                    "data": {
                        "message": error or "Agent processing failed",
                        "chat_id": chat_id,
                    },
                })
                continue

            video_url = None
            if video_path and _SAFE_MEDIA_RE.fullmatch(os.path.basename(video_path)):
                video_url = f"/media/{os.path.basename(video_path)}"
            # A trial video is watermarked; the agent also returns the clean
            # render, and that is what the shared library keeps.
            clean_path = str(data.get("clean_video_path") or "")
            clean_url = video_url
            if clean_path and _SAFE_MEDIA_RE.fullmatch(os.path.basename(clean_path)):
                clean_url = f"/media/{os.path.basename(clean_path)}"

            # The plan's unit stays spent only if a video came of it; a
            # text-only answer gives it back.
            if status == "complete" and video_url:
                await plans.commit(request_id)
            elif status == "complete":
                await plans.release(request_id)
            if status == "complete":
                has_audio = data.get("has_audio")
                await jobs.finish(request_id, ok=True, video=bool(video_url),
                                  has_audio=has_audio if isinstance(has_audio, bool) else None,
                                  duration=_number(data.get("duration"), 3600),
                                  render_sec=_number(data.get("elapsed_sec")),
                                  tts_chars=_number(data.get("tts_chars")) or 0)

            # A general question's video is filed under its topic for the
            # next person who asks - the clean render, never a trial's copy.
            video_cache_id = None
            classification = request_info.get("classification") or {}
            # Filed under the language the video is actually in: what the agent
            # says it answered in, else what was asked for, else the question's.
            answer_language = (str(data.get("language") or "")[:5]
                               or request_info.get("output_language")
                               or classification.get("language", ""))
            if (status == "complete" and response_text and clean_url
                    and classification.get("specificity") == "generic" and classification.get("topic_id")):
                try:
                    video_cache_id = await topic_cache.add(
                        topic_id=classification["topic_id"], lang=answer_language,
                        video_url=clean_url, text=response_text, user_id=user_id,
                        duration=data.get("duration"), has_audio=data.get("has_audio"),
                    )
                except Exception as e:
                    print(f"topic cache write failed: {type(e).__name__}: {e}")

            if status == "complete" and response_text:
                try:
                    msg_data = await save_message(
                        chat_id, "assistant", response_text,
                        video_url=video_url, video_cache_id=video_cache_id,
                    )
                except Exception as e:
                    print(f"Failed to save assistant message: {type(e).__name__}: {e}")
                    continue

                await ui_manager.send_to_user(user_id, {
                    "type": "ai_response",
                    "data": {
                        "message_id": msg_data["id"],
                        "chat_id": chat_id,
                        "content": response_text,
                        "video_url": video_url,
                        "timestamp": msg_data["timestamp"],
                        "subject": subject,
                        **({"video_cache_id": video_cache_id,
                            "rating": {"up": 0, "down": 0, "mine": 0}} if video_cache_id else {}),
                    },
                })
                await usage_log.log(user_id, "explanation", video=bool(video_url))

                # File the answer under the question that produced it. Done
                # after the user already has their reply, and never allowed to
                # fail the request: a cache write is an optimisation, not part
                # of answering.
                #
                # Not when the voice was asked for and the video came out
                # silent (Azure down, out of quota, a script with nothing to
                # say): the next person asking the same words would be handed
                # the silent one for as long as it stays in the cache.
                voiced = str(request_info.get("variant", "")).startswith("voice=")
                if CACHE_ENABLED and not (voiced and data.get("has_audio") is False):
                    try:
                        await cache_service.remember(
                            prompt=request_info.get("prompt", ""),
                            screenshots=request_info.get("screenshots", []),
                            text=response_text,
                            video_url=clean_url,
                            variant=request_info.get("variant", ""),
                        )
                    except Exception as e:
                        print(f"cache write failed: {type(e).__name__}: {e}")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Agent WebSocket error: {type(e).__name__}: {e}")
    finally:
        agent_manager.disconnect(websocket)
        # Only when nothing has taken this connection's place. An agent that
        # reconnected is an agent that is there, and telling everybody their
        # request failed because the previous socket finished closing would
        # be a failure we invented.
        if agent_manager.agent_connection is None:
            await _notify_pending_failures(
                "AI Agent is not available. Please try again later."
            )
