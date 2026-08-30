"""Environment configuration for the Anyq agent.

Every os.getenv() read of the agent lives here, as a module constant.
Other modules import these constants instead of calling os.getenv themselves.

Env values are validated at import time: a typo or an out-of-range value
exits with a clear message instead of a traceback deep inside a node.
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _get_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        print(
            f"FATAL: environment variable {name} must be an integer, got {raw!r}. "
            "Fix .env and restart the agent.",
            file=sys.stderr,
        )
        sys.exit(1)
    if value < minimum:
        print(
            f"FATAL: environment variable {name} must be >= {minimum}, got {value}. "
            "Fix .env and restart the agent.",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


def _get_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        print(
            f"FATAL: environment variable {name} must be a number, got {raw!r}. "
            "Fix .env and restart the agent.",
            file=sys.stderr,
        )
        sys.exit(1)
    if value < minimum:
        print(
            f"FATAL: environment variable {name} must be >= {minimum}, got {value}. "
            "Fix .env and restart the agent.",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


# ============== LLM retries ==============
# Gemini intermittently returns 503 UNAVAILABLE ("experiencing high demand").
# A single failure otherwise aborts the whole graph, so retry transient errors
# with exponential backoff before giving up.
_LLM_RETRIES = _get_int("GEMINI_RETRY_ATTEMPTS", 3)
_LLM_RETRY_BASE_DELAY = _get_float("GEMINI_RETRY_BASE_DELAY", 2.0)

# ============== Output language ==============
# Explanations and all on-screen wording follow the user's language;
# Kazakh is the product default.
DEFAULT_OUTPUT_LANGUAGE = (os.getenv("DEFAULT_OUTPUT_LANGUAGE", "kk") or "kk").strip().lower()

# ============== Fonts ==============
MANIM_TEXT_FONT = os.getenv("MANIM_TEXT_FONT", "").strip()

# ============== LaTeX ==============
MANIM_ALLOW_LATEX = os.getenv("MANIM_ALLOW_LATEX")

# ============== Render repair ==============
# How many times to ask the model to repair a script Manim refused to render.
_RENDER_REPAIR_ATTEMPTS = _get_int("MANIM_REPAIR_ATTEMPTS", 2)

# ============== MCP render server ==============
MANIM_MCP_SERVER_SCRIPT = os.getenv("MANIM_MCP_SERVER_SCRIPT")
MANIM_MCP_PYTHON = os.getenv("MANIM_MCP_PYTHON", sys.executable)
MANIM_EXECUTABLE = os.getenv("MANIM_EXECUTABLE")

# ============== Gemini vision ==============
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-pro")

# ============== Snippet mode ==============
DOC_SNIPPET_MODE = os.getenv("DOC_SNIPPET_MODE")

# ============== WebSocket client ==============
DEFAULT_WS_URL = os.getenv("AGENT_WS_URL", "ws://backend:8000/ws/agent")
RECONNECT_DELAY_SEC = _get_float("AGENT_WS_RECONNECT_DELAY_SEC", 5.0)

# Shared secret for the agent channel handshake (must match the backend).
AGENT_SECRET = os.getenv("AGENT_SECRET", "")

# A single video can take minutes to render, during which this connection is
# idle. The default 20s keepalive closes it mid-render (1011 keepalive ping
# timeout) and the finished response is lost, so allow long quiet periods.
WS_PING_INTERVAL_SEC = _get_float("AGENT_WS_PING_INTERVAL_SEC", 30.0)
WS_PING_TIMEOUT_SEC = _get_float("AGENT_WS_PING_TIMEOUT_SEC", 60.0)

# Incoming frame size limit (base64 screenshots can be large).
WS_MAX_MESSAGE_SIZE = _get_int("AGENT_WS_MAX_MESSAGE_SIZE", 16 * 1024 * 1024)

# Idle receive timeout: if the backend says nothing for this long, drop the
# connection and reconnect (liveness net; protocol pings already catch dead
# peers much sooner).
WS_RECV_TIMEOUT_SEC = _get_float("AGENT_WS_RECV_TIMEOUT_SEC", 3600.0)

# Per-request deadline for the whole pipeline (LLM + render + repair loops).
REQUEST_DEADLINE_SEC = _get_float("AGENT_REQUEST_DEADLINE_SEC", 1200.0)

# Handshake timeout after connecting (backend must answer auth_ok).
AGENT_HANDSHAKE_TIMEOUT_SEC = _get_float("AGENT_HANDSHAKE_TIMEOUT_SEC", 10.0)

# ============== Image limits ==============
MAX_IMAGES = _get_int("AGENT_MAX_IMAGES", 3)
MAX_IMAGE_BYTES = _get_int("AGENT_MAX_IMAGE_BYTES", 5 * 1024 * 1024)
MAX_IMAGE_B64_LEN = MAX_IMAGE_BYTES * 4 // 3 + 16

# ============== Telemetry ==============
ANYQ_TELEMETRY_PATH = os.getenv("ANYQ_TELEMETRY_PATH", "/app/logs/runs.jsonl")