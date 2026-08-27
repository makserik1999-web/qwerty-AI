"""Environment configuration for the Anyq agent.

Every os.getenv() read of the agent lives here, as a module constant.
Other modules import these constants instead of calling os.getenv themselves.
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# ============== LLM retries ==============
# Gemini intermittently returns 503 UNAVAILABLE ("experiencing high demand").
# A single failure otherwise aborts the whole graph, so retry transient errors
# with exponential backoff before giving up.
_LLM_RETRIES = int(os.getenv("GEMINI_RETRY_ATTEMPTS", "3"))
_LLM_RETRY_BASE_DELAY = float(os.getenv("GEMINI_RETRY_BASE_DELAY", "2"))

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
_RENDER_REPAIR_ATTEMPTS = int(os.getenv("MANIM_REPAIR_ATTEMPTS", "2"))

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
RECONNECT_DELAY_SEC = float(os.getenv("AGENT_WS_RECONNECT_DELAY_SEC", "5"))

# A single video can take minutes to render, during which this connection is
# idle. The default 20s keepalive closes it mid-render (1011 keepalive ping
# timeout) and the finished response is lost, so allow long quiet periods.
WS_PING_INTERVAL_SEC = float(os.getenv("AGENT_WS_PING_INTERVAL_SEC", "600"))
WS_PING_TIMEOUT_SEC = float(os.getenv("AGENT_WS_PING_TIMEOUT_SEC", "600"))
