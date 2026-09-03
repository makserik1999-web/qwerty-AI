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

# ============== Reasoning effort ==============
# gemini-3.7-flash reasons before it writes, and on this workload the default
# effort is a bad trade. Measured on the Manim script node: default took 24.4s
# and the result rendered 2 times out of 4, "low" took 16.5s and rendered 4 out
# of 4 - with MORE animated steps, not fewer, and a longer video.
#
# The reason is specific to this prompt rather than a general claim about the
# model: build_manim_system_prompt already carries a Manim API reference, so
# extra deliberation mostly invents API that is not in it (the two failures
# were `ease_out_quad` and `AQUA`, neither of which exists).
#
# Empty disables the field. That is also what any provider other than
# OpenRouter needs: extra_body is an OpenAI-wire concept, and the native
# Gemini provider would reject it - so the gate below keeps
# DEFAULT_LLM_PROVIDER=gemini working unchanged.
_ALLOWED_REASONING_EFFORTS = {"minimal", "low", "medium", "high"}

DEFAULT_LLM_PROVIDER = (os.getenv("DEFAULT_LLM_PROVIDER", "") or "").strip().lower()
LLM_REASONING_EFFORT = (os.getenv("LLM_REASONING_EFFORT", "low") or "").strip().lower()

if LLM_REASONING_EFFORT and LLM_REASONING_EFFORT not in _ALLOWED_REASONING_EFFORTS:
    # Fail at startup rather than on every request: a typo here would 400 the
    # upstream call for every question, and the graph would report it as an
    # LLM outage.
    print(
        f"FATAL: LLM_REASONING_EFFORT must be one of "
        f"{sorted(_ALLOWED_REASONING_EFFORTS)} or empty, got {LLM_REASONING_EFFORT!r}. "
        "Fix .env and restart the agent.",
        file=sys.stderr,
    )
    sys.exit(1)


# ============== Output language ==============
# Explanations and all on-screen wording follow the user's language;
# Kazakh is the product default.
DEFAULT_OUTPUT_LANGUAGE = (os.getenv("DEFAULT_OUTPUT_LANGUAGE", "kk") or "kk").strip().lower()

# ============== Narration ==============
# Speech is synthesised here, in the agent, and never in the render
# subprocess: that process executes model-written code and is given no
# credentials on purpose (see safe_env in manim_server.run_manim_script).
#
# Azure rather than Google because Kazakh decides it. Gemini TTS covers 99
# languages and Kazakh is not one of them, so the GEMINI_API_KEY above cannot
# narrate the product's primary language.
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "").strip()
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "").strip()

# On by default. Off renders the same script silently - the animation is
# generated once either way, so this costs nothing at generation time.
NARRATION_ENABLED = (os.getenv("NARRATION_ENABLED", "1") or "1").strip() != "0"

# Which of the two Kazakh voices speaks: aigul (female) or daulet (male).
# Russian and English follow with a voice of the same gender.
NARRATION_VOICE = (os.getenv("NARRATION_VOICE", "aigul") or "aigul").strip().lower()

# A school explanation, not a news read. Azure's SSML rate, relative.
NARRATION_RATE = (os.getenv("NARRATION_RATE", "-8%") or "-8%").strip()

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