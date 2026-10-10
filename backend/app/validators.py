"""Payload validation shared by the HTTP and WebSocket entry points."""

from typing import Any, Optional

from app.config import (
    _OBJECT_ID_RE,
    MAX_PROMPT_LEN,
    MAX_SCREENSHOT_B64_LEN,
    MAX_SCREENSHOTS,
    MAX_TITLE_LEN,
)


def _validate_chat_id(chat_id: str) -> bool:
    return bool(chat_id) and bool(_OBJECT_ID_RE.fullmatch(chat_id))


def _validate_screenshots(screenshots: Any) -> Optional[str]:
    """Returns an error message, or None when the payload is acceptable."""
    if not isinstance(screenshots, list):
        return "screenshots must be a list"
    if len(screenshots) > MAX_SCREENSHOTS:
        return f"Too many screenshots (max {MAX_SCREENSHOTS})"
    for ss in screenshots:
        b64 = ""
        if isinstance(ss, dict):
            b64 = ss.get("image_base64") or ""
        if not isinstance(b64, str) or not b64:
            return "screenshot is missing image_base64"
        if len(b64) > MAX_SCREENSHOT_B64_LEN:
            return "screenshot is too large"
    return None


def _validate_title(title: Any) -> str:
    t = str(title or "").strip() or "New Chat"
    return t[:MAX_TITLE_LEN]


def _validate_prompt(prompt: Any) -> Optional[str]:
    if not isinstance(prompt, str):
        return "prompt must be a string"
    if len(prompt) > MAX_PROMPT_LEN:
        return f"Message is too long (max {MAX_PROMPT_LEN} characters)"
    return None
