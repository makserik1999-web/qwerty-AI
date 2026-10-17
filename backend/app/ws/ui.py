"""The UI socket: chat operations and forwarding questions to the agent."""

import json
import time
import uuid

from bson import ObjectId
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import (
    CACHE_ENABLED,
    CLASSIFY_TIMEOUT_SEC,
    COOKIE_NAME,
    EFFORT_DEFAULT,
    EFFORT_LEVELS,
    EXPLANATION_LANGUAGES,
    NARRATION_DEFAULT,
    NARRATION_VOICE_DEFAULT,
    NARRATION_VOICES,
    TOPIC_CACHE_ENABLED,
    USER_ROLE_DEFAULT,
    VIDEO_LENGTH_DEFAULT,
    VIDEO_LENGTHS,
    VIDEO_ORIENTATION_DEFAULT,
    VIDEO_ORIENTATIONS,
)
from app.db import db
from app.repositories.chats import create_chat, delete_chat_by_id
from app.repositories.messages import save_message
from app.security.origins import _is_allowed_origin
from app.security.sessions import _user_from_token
from app.security.verified import EMAIL_UNVERIFIED, may_generate
from app.services import cache_service, jobs, plans, quota, topic_cache, usage_log
from app.validators import (
    _validate_chat_id,
    _validate_prompt,
    _validate_screenshots,
    _validate_title,
)
from app.ws.manager import AgentDeliveryError, agent_manager, ui_manager

router = APIRouter()


async def _handle_ui_frame(websocket: WebSocket, user_id: str, data: dict) -> None:
    msg_type = data.get("type")
    payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}

    if msg_type == "ping":
        await websocket.send_json({"type": "pong"})
        return

    if msg_type == "create_chat":
        title = _validate_title(payload.get("title"))
        chat = await create_chat(user_id, title)
        await websocket.send_json({"type": "chat_created", "data": chat})
        return

    if msg_type == "delete_chat":
        chat_id = payload.get("chat_id")
        if chat_id and _validate_chat_id(chat_id):
            success = await delete_chat_by_id(chat_id, user_id)
            await websocket.send_json({
                "type": "chat_deleted",
                "data": {"chat_id": chat_id, "success": success},
            })
        else:
            await websocket.send_json({
                "type": "chat_deleted",
                "data": {"chat_id": chat_id, "success": False},
            })
        return

    if msg_type == "user_message":
        chat_id = payload.get("chat_id")
        prompt = payload.get("prompt", "")
        screenshots = payload.get("screenshots", [])

        if not chat_id or not _validate_chat_id(chat_id):
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Invalid chat_id", "chat_id": chat_id},
            })
            return

        prompt_err = _validate_prompt(prompt)
        if prompt_err:
            await websocket.send_json({
                "type": "error",
                "data": {"message": prompt_err, "chat_id": chat_id},
            })
            return

        shots_err = _validate_screenshots(screenshots)
        if shots_err:
            await websocket.send_json({
                "type": "error",
                "data": {"message": shots_err, "chat_id": chat_id},
            })
            return

        if not prompt and not screenshots:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Either prompt or screenshots required", "chat_id": chat_id},
            })
            return

        # Ownership check: the chat must belong to the session user.
        chat = await db.db.chats.find_one({"_id": ObjectId(chat_id), "user_id": user_id})
        if not chat:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Chat not found", "chat_id": chat_id},
            })
            return

        # Cache first: a stored answer costs a couple of database reads, while
        # a miss costs three LLM calls and minutes of rendering. This runs
        # BEFORE the agent-availability check on purpose - a question we have
        # already answered can be served even while the agent is down.
        # `force_regenerate` lets the user insist on a fresh answer.
        # What the asker wants made, not just asked. Validated against a
        # closed set before it goes anywhere near a cache key: a voice taken
        # straight from the client would let anyone mint unlimited entries for
        # one question.
        narration = bool(payload.get("narration", NARRATION_DEFAULT))
        voice = str(payload.get("narration_voice") or NARRATION_VOICE_DEFAULT)
        if voice not in NARRATION_VOICES:
            voice = NARRATION_VOICE_DEFAULT
        # How long a video the asker wants. In the cache key for the same
        # reason the voice is: a stored ninety-second answer is the wrong
        # answer to somebody who asked for thirty seconds.
        # Cased and trimmed before the closed-set check, the way the agent
        # does it: otherwise "Short" from a client is not a rejected value,
        # it is a silently substituted one - a control that looks like it
        # worked and did nothing.
        video_length = str(payload.get("video_length") or "").strip().lower()
        if video_length not in VIDEO_LENGTHS:
            video_length = VIDEO_LENGTH_DEFAULT
        # How much to spend making it. In the cache key because it decides
        # the resolution and frame rate of the video that comes back.
        effort = str(payload.get("effort") or "").strip().lower()
        if effort not in EFFORT_LEVELS:
            effort = EFFORT_DEFAULT
        # The plan caps the quality: 1080p is a Ұстаз thing. Capped before the
        # cache key is made, so the answer is filed under what was rendered,
        # not under what was asked for.
        account = await db.db.users.find_one({"_id": ObjectId(user_id)}) or {}
        entitlement = await plans.resolve(account) if account else None
        if entitlement and entitlement.plan:
            effort = plans.clamp_effort(effort, entitlement.plan)
        # The answer language, when the asker chose one. Otherwise the agent
        # answers in the language of the question, as it always has.
        output_language = str(payload.get("output_language") or "").strip().lower()
        if output_language not in EXPLANATION_LANGUAGES:
            output_language = ""
        # Landscape for the classroom, portrait for a phone. Changes the video
        # itself, so it is in the cache key like everything above.
        orientation = str(payload.get("orientation") or "").strip().lower()
        if orientation not in VIDEO_ORIENTATIONS:
            orientation = VIDEO_ORIENTATION_DEFAULT
        variant = cache_service.render_variant(narration, voice, video_length, effort, output_language,
                                               orientation)

        cached = None
        if CACHE_ENABLED and not payload.get("force_regenerate"):
            try:
                cached = await cache_service.lookup(prompt, screenshots, variant)
            except Exception as e:
                # The cache must never be the reason a question goes unanswered.
                print(f"cache lookup failed, falling through to the agent: {type(e).__name__}: {e}")

        if cached:
            await save_message(chat_id, "user", prompt, screenshots)
            await websocket.send_json({"type": "message_received"})
            msg_data = await save_message(
                chat_id, "assistant", cached.get("educator_text", ""),
                video_url=cached.get("video_url"),
            )
            await websocket.send_json({
                "type": "ai_response",
                "data": {
                    "message_id": msg_data["id"],
                    "chat_id": chat_id,
                    "content": msg_data["content"],
                    "video_url": msg_data["video_url"],
                    "timestamp": msg_data["timestamp"],
                    # The UI marks these, so nobody is left wondering why an
                    # answer that normally takes minutes arrived instantly.
                    "from_cache": True,
                    "cache_tier": cached.get("tier", ""),
                    # "exact" or "semantic". A semantic hit answered a
                    # DIFFERENT wording, so the reader is shown which question
                    # was matched - they can see it is not what they meant.
                    "cache_match": cached.get("match", "exact"),
                    "matched_question": cached.get("matched_question", ""),
                },
            })
            await usage_log.log(user_id, "explanation", cached=True,
                                video=bool(cached.get("video_url")))
            return

        # The topic layer. A general question ("explain Pythagoras") on a
        # topic that already has a video is answered with it - free, like any
        # library answer, and for students too. Whether it is general, and
        # which topic, is one short call to the agent; without an answer the
        # question is simply rendered. Asked even when the person insisted on
        # a new video: the new one is then filed as another version.
        classification = None
        if CACHE_ENABLED and TOPIC_CACHE_ENABLED and not screenshots and prompt:
            classification = await agent_manager.request_classification(prompt, CLASSIFY_TIMEOUT_SEC)
        if (classification and classification.get("specificity") == "generic"
                and classification.get("topic_id") and not payload.get("force_regenerate")):
            hit = None
            try:
                # The shelf in the language the answer is wanted in, which is
                # the question's own unless another was chosen.
                hit = await topic_cache.best(classification["topic_id"],
                                             output_language or classification.get("language", ""),
                                             narration=narration, orientation=orientation)
            except Exception as e:
                print(f"topic cache lookup failed, rendering instead: {type(e).__name__}: {e}")
            if hit:
                hit_id = str(hit["_id"])
                await save_message(chat_id, "user", prompt, screenshots)
                await websocket.send_json({"type": "message_received"})
                msg_data = await save_message(chat_id, "assistant", hit.get("text", ""),
                                              video_url=hit.get("video_url"), video_cache_id=hit_id)
                await topic_cache.served(hit["_id"])
                await websocket.send_json({
                    "type": "ai_response",
                    "data": {
                        "message_id": msg_data["id"],
                        "chat_id": chat_id,
                        "content": msg_data["content"],
                        "video_url": msg_data["video_url"],
                        "timestamp": msg_data["timestamp"],
                        "from_cache": True,
                        "cache_tier": hit.get("status", ""),
                        "cache_match": "topic",
                        # Which topic it was filed under, so a wrong match is
                        # visible - and the "make one for my question" button
                        # is there for exactly that.
                        "matched_question": hit.get("title", ""),
                        "video_cache_id": hit_id,
                        "rating": {"up": hit.get("rating_up", 0), "down": hit.get("rating_down", 0),
                                   "mine": await topic_cache.my_vote(hit_id, user_id)},
                    },
                })
                await usage_log.log(user_id, "explanation", cached=True, video=True)
                return

        # Making a new answer is for teachers. A student still gets whatever
        # the library already holds - that costs a couple of reads - but a
        # generation is a paid model call. Read from the account, like every
        # other access decision, never from the frame. The code lets the
        # interface say it in the reader's language.
        if ((account or {}).get("role") or USER_ROLE_DEFAULT) != "teacher":
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": "New videos are made by teacher accounts. "
                               "Answers already in the library still work.",
                    "chat_id": chat_id,
                    "code": "teacher_only",
                },
            })
            return
        if not may_generate(account or {}):
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": "Confirm your email address first - we sent you a link.",
                    "chat_id": chat_id,
                    "code": EMAIL_UNVERIFIED,
                },
            })
            return

        # Only a real generation is charged for, and only once the cache has
        # had its chance: an answer from the library costs a couple of reads,
        # so billing it would penalise exactly what protects the system.
        verdict = await quota.check(
            user_id,
            in_flight=agent_manager.in_flight_for(user_id),
            queue_depth=agent_manager.queue_depth(),
        )
        if not verdict.allowed:
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": verdict.reason,
                    "chat_id": chat_id,
                    "quota": {
                        "remaining_hour": verdict.remaining_hour,
                        "remaining_day": verdict.remaining_day,
                        "retry_after_sec": verdict.retry_after_sec,
                    },
                },
            })
            return

        # Check agent availability BEFORE saving anything (no orphan messages).
        if not agent_manager.agent_connection:
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": "AI Agent is not available. Please try again later.",
                    "chat_id": chat_id,
                },
            })
            return

        # One video off the plan, taken before anything is saved and given
        # back if no video comes of it. The request id names the reservation.
        request_id = str(uuid.uuid4())
        try:
            entitlement = await plans.reserve(entitlement.user if entitlement else account,
                                              "videos", request_id)
        except plans.PlanRefusal as refusal:
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": "Making a video needs the trial or the Ұстаз plan, "
                               "and this plan's videos are used up."
                               if refusal.code == "plan_exhausted"
                               else "Making a video needs the trial or the Ұстаз plan.",
                    "chat_id": chat_id,
                    "code": refusal.code,
                },
            })
            return

        user_message = await save_message(chat_id, "user", prompt, screenshots)
        await websocket.send_json({"type": "message_received"})

        agent_manager.pending_requests[request_id] = {
            "user_id": user_id,
            "chat_id": chat_id,
            "created_at": time.monotonic(),
            # Carried so the answer can be filed under the question that
            # produced it once the agent replies.
            "prompt": prompt,
            "screenshots": screenshots,
            # The answer must be filed under the same variant it was asked
            # for, or the next asker gets the wrong kind of video.
            "variant": variant,
            # A trial video carries a watermark; the cache gets the clean copy.
            "watermark": entitlement.watermark,
            # General or specific, and the topic: decides whether the video
            # is filed for the next person who asks.
            "classification": classification,
            "output_language": output_language,
            "orientation": orientation,
        }
        await quota.record(user_id, request_id)
        # The task the admin panel sees. What was asked is kept so a failure
        # can be made again; the screenshots stay in the chat message.
        await jobs.start("video", user_id, request_id, narration=narration, spec={
            "prompt": prompt, "chat_id": chat_id, "user_message_id": user_message["id"],
            "screenshots": len(screenshots or []), "narration": narration,
            "voice": voice, "video_length": video_length, "effort": effort,
            "variant": variant, "classification": classification,
            "output_language": output_language, "orientation": orientation,
        })
        try:
            await agent_manager.send_to_agent(
                request_id=request_id,
                user_id=user_id,
                chat_id=chat_id,
                text=prompt,
                screenshots=screenshots,
                narration=narration,
                narration_voice=voice,
                video_length=video_length,
                effort=effort,
                watermark=entitlement.watermark,
                output_language=output_language,
                orientation=orientation,
            )
        except Exception as e:
            agent_manager.pending_requests.pop(request_id, None)
            # Nothing was rendered, so nothing is owed.
            await quota.refund(request_id)
            await plans.release(request_id)
            await jobs.finish(request_id, ok=False, error_type="delivery")
            # A request the agent never confirmed is not a failure the person
            # has to understand - it is one they can simply retry, and saying
            # so beats handing them the mechanism. Every other send failure
            # keeps its detail, which is what makes it worth distinguishing.
            if isinstance(e, AgentDeliveryError):
                message = ("The request did not reach the AI Agent. "
                           "Please try again.")
            else:
                message = f"Failed to send to agent: {e}"
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": message,
                    "chat_id": chat_id,
                },
            })
        return

    # Unknown message type: ignore silently.


@router.websocket("/ws")
async def websocket_ui_endpoint(websocket: WebSocket):
    """WebSocket endpoint for UI clients; identity from the session cookie."""
    token = websocket.cookies.get(COOKIE_NAME)
    user = await _user_from_token(token)
    if not user:
        await websocket.close(code=1008, reason="not authenticated")
        return

    if not _is_allowed_origin(websocket.headers.get("origin")):
        await websocket.close(code=1008, reason="origin not allowed")
        return

    user_id = str(user["_id"])
    try:
        await ui_manager.connect(websocket, user_id)
    except Exception as e:
        print(f"UI connect failed: {e}")
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("frame must be an object")
            except Exception as e:
                # One malformed frame must not kill the connection.
                try:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": f"Invalid message: {type(e).__name__}"},
                    })
                except Exception:
                    pass
                continue

            try:
                await _handle_ui_frame(websocket, user_id, data)
            except WebSocketDisconnect:
                raise
            except Exception as e:
                print(f"UI frame error for user {user_id}: {type(e).__name__}: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "Internal error while processing message"},
                    })
                except Exception:
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"UI WebSocket error for user {user_id}: {type(e).__name__}: {e}")
    finally:
        ui_manager.disconnect(user_id, websocket)
