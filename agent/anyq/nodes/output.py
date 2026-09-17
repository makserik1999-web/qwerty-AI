"""What the request finally answers with.

Moved verbatim out of nodes.py.
"""

from typing import Any, Dict

from anyq.language import _RENDER_FALLBACK_MESSAGES, _resolve_output_language
from anyq.nodes.state import ScienceVideoState


async def format_output(state: ScienceVideoState) -> Dict[str, Any]:
    if not state.get("is_science"):
        return {}

    text = (state.get("educator_text") or "").strip()
    video_path = (state.get("video_path") or "").strip()

    # Render failed even after the repair attempts: keep the explanation the
    # user already earned, and append a friendly note instead of an error.
    if state.get("video_needed") and not video_path:
        language = _resolve_output_language(state)
        note = _RENDER_FALLBACK_MESSAGES.get(language, _RENDER_FALLBACK_MESSAGES["kk"])
        text = f"{text}\n\n---\n\n{note}" if text else note

    return {
        "final_text": text,
        # "" rather than None: the state declares a str, reject_non_science
        # already returns "", and None made every reader add its own `or ""`.
        "final_video_path": video_path if state.get("video_needed") else "",
        # Carried out so the interface can label the answer with the subject
        # the model actually decided on, rather than guessing it back from the
        # wording. Free text, and the client maps what it recognises.
        "final_subject": (state.get("subject") or "").strip(),
    }
