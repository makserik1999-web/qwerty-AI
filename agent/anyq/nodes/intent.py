"""Is this a science question, and does it want a video.

Moved verbatim out of nodes.py.
"""

from typing import Any, Dict

from spoon_ai.schema import Message

from anyq.config import DOC_SNIPPET_MODE
from anyq.language import _REJECT_MESSAGES, _resolve_output_language
from anyq.llm_client import _llm_chat
from anyq.nodes.state import USER_CONTENT_NOTICE, ScienceVideoState, _wrap
from anyq.script_guard import _safe_json_loads


async def classify_intent(state: ScienceVideoState) -> Dict[str, Any]:
    q = (state.get("user_message") or "").strip()
    if not q:
        raise ValueError("user_message is required")
    img_ctx = (state.get("image_context") or "").strip()

    if DOC_SNIPPET_MODE == "1":
        return {"is_science": True, "subject": "physics", "intent_reason": "(stub)"}

    resp = await _llm_chat(
        [
            Message(
                role="system",
                content=(
                    "Classify if the user request is scientific/educational.\n"
                    "Return ONLY valid JSON with keys:\n"
                    '- "is_science": boolean\n'
                    '- "subject": string\n'
                    '- "reason": string\n'
                ),
            ),
            Message(
                role="user",
                content=(
                    USER_CONTENT_NOTICE
                    + "\n\n"
                    + _wrap("user_input", q)
                    + (f"\n\n{_wrap('image_context', img_ctx)}" if img_ctx else "")
                ),
            ),
        ]
    )
    payload = _safe_json_loads(resp.content)
    return {
        "is_science": bool(payload.get("is_science")),
        "subject": str(payload.get("subject") or "other"),
        "intent_reason": str(payload.get("reason") or ""),
    }


def route_after_intent(state: ScienceVideoState) -> str:
    return "science" if state.get("is_science") else "reject"


def _heuristic_video_needed(query: str) -> Dict[str, Any]:
    """
    Always return True for video generation for science questions.
    Only skip video for empty queries.
    """
    q = (query or "").strip()
    if not q:
        return {"video_needed": False, "video_reason": "empty query"}

    # ALWAYS generate videos for science questions - no exceptions
    return {"video_needed": True, "video_reason": "science question - always generate video"}


async def decide_video_needed(state: ScienceVideoState) -> Dict[str, Any]:
    """
    Decide if video is needed. For science questions, ALWAYS generate video.
    """
    q = (state.get("user_message") or "").strip()

    if not state.get("is_science"):
        return {"video_needed": False, "video_reason": "non-science"}

    # For science questions, ALWAYS generate videos
    return _heuristic_video_needed(q)


def route_after_video_needed(state: ScienceVideoState) -> str:
    return "video" if state.get("video_needed") else "no_video"


async def reject_non_science(state: ScienceVideoState) -> Dict[str, Any]:
    language = _resolve_output_language(state)
    msg = _REJECT_MESSAGES.get(language, _REJECT_MESSAGES["kk"])
    return {"final_text": msg, "final_video_path": "", "output_language": language}
