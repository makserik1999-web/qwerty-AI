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
# That specificity cuts both ways: the numbers are for 3.7-flash and were NOT
# re-measured when the default moved to 3.8-flash. "low" stays because it is
# the only measurement there is, not because it is known to still win.
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

# ============== Video length ==============
# How long the video runs, asked for as a bucket rather than in seconds.
#
# There is no duration parameter anywhere in Manim or in this pipeline - a
# video lasts exactly as long as its animations, and with narration on those
# are pinned to the speech (`run_time=tracker.duration`). So the length is
# controlled where it is actually decided: by how much the script is told to
# say. The characters are known BEFORE any rendering starts, which is what
# makes this checkable rather than a wish addressed to the model.
#
# The seconds-per-character rate is measured, not assumed: 11.8-13.8
# characters per second across fourteen renders on gemini-3.8-flash, mean
# 12.9, Kazakh and Russian alike. The budgets below are those seconds
# turned back into characters. The rate is a property of the MODEL's
# scripting habits as much as of the speech - deepseek measured 10.3-10.7
# on the same prompt - so it needs re-measuring if the default model
# changes.
#
# Hence buckets, and hence "~30-40 sec" in the interface rather than "35 sec":
# +-6% is the honest precision, and a slider promising seconds would be
# promising something this cannot deliver.
VIDEO_LENGTHS = ("short", "medium", "long")

# (minimum, maximum) narration characters, and the seconds they buy.
#
# Each window is CENTRED on its target duration rather than starting at it.
# The first cut set the floors at the target and every bucket came out at or
# below its lower second, because the model writes to the floor of whatever
# range it is given: measured at 329, 589 and 1009 against floors of 380, 635
# and 1015 - under all three. What it does land near is the middle of the
# window after a correction (459, 675, 1106 in windows centred on 445, 697 and
# 1080), so the middle is what has to be right.
#
# Rate: 12.9 characters per second, from fourteen measured renders
# (11.8 to 13.8).
# Wider than it looks - the +-6% spread is as wide as the ten-second windows
# themselves, which is why a bucket lands a second or two outside about a
# third of the time and why the interface says "~30-40 sec". A promise of
# exact seconds could not be kept by anything downstream of a language model.
VIDEO_LENGTH_BUDGETS = {
    "short": (430, 500),     # centre 465 -> ~36 s
    "medium": (700, 770),    # centre 735 -> ~57 s
    "long": (1090, 1165),    # centre 1127 -> ~87 s
}

# Medium, deliberately. Before this existed the prompt asked for "8-15 blocks,
# under 2000 characters" and produced 60-96 second videos - the length was
# whatever the model felt like, and nobody chose it. Medium is the shortest
# bucket that still fits a full explanation; set VIDEO_LENGTH_DEFAULT=long to
# keep videos closer to what they were.
VIDEO_LENGTH_DEFAULT = (os.getenv("VIDEO_LENGTH_DEFAULT", "medium") or "").strip().lower()
if VIDEO_LENGTH_DEFAULT not in VIDEO_LENGTHS:
    VIDEO_LENGTH_DEFAULT = "medium"

# ============== Effort ==============
# How much is spent making the video, as one word covering several settings.
#
# It is a bundle rather than a single knob because "effort" is not
# one-dimensional here, and because the one knob people reach for first -
# more deliberation from the model - is measurably WRONG on the part that
# matters: at default reasoning effort the Manim script rendered 2 times out
# of 4, at "low" it rendered 4 of 4, because extra deliberation is spent
# inventing API that is not in the prompt. So the script node stays on "low"
# at every level. A control that breaks rendering at its top setting would be
# selling a downgrade.
#
# What actually differs is what a person can see and what they wait for.
# Measured on one 37-second scene, rendering only:
#     480p15   11.4 s   0.34 MB
#     1080p60  68.8 s   1.28 MB     - six times the wait
# 720p30 sits between at roughly twice the low profile.
#
# NOT included, deliberately: a self-review pass over the explanation, and
# raising the reasoning effort of the EDUCATOR node (which, unlike the script
# node, has no API to hallucinate and might well benefit). Both are plausible
# and neither is measured, and shipping an unmeasured lever inside a control
# people pay attention to is how a slider ends up selling nothing.
EFFORT_LEVELS = ("low", "medium", "high")

# manim's -q flag: l=480p15, m=720p30, h=1080p60. Note this is frames as well
# as pixels - at "l" the animation runs at 15 fps, which on a projector in a
# classroom is visibly choppy, and that was the default until now.
EFFORT_PROFILES = {
    "low": {"quality": "l", "repair_attempts": 1},
    "medium": {"quality": "m", "repair_attempts": 2},
    "high": {"quality": "h", "repair_attempts": 3},
}

# Medium. 480p15 was never a deliberate choice - it is manim's own default and
# nothing ever passed anything else - and it is below what this product is
# for: a teacher putting the video on a projector. The upgrade costs about ten
# to twenty-five seconds per request.
EFFORT_DEFAULT = (os.getenv("EFFORT_DEFAULT", "medium") or "").strip().lower()
if EFFORT_DEFAULT not in EFFORT_LEVELS:
    EFFORT_DEFAULT = "medium"

# ============== Animation pacing ==============
# How long a single on-screen change may take.
#
# The prompt used to require run_time=tracker.duration on every animation,
# which stretched each one across the whole spoken sentence. A five-second
# sentence bought a five-second fade - and a five-second Transform between two
# captions, which spends those five seconds morphing the letters of one word
# into the letters of another and is unreadable for all of them.
#
# It was never needed for synchronisation: manim-voiceover's `voiceover` block
# calls wait_for_voiceover() when it exits, so the block already lasts exactly
# as long as its audio whatever the animation inside it did. The animation
# therefore plays at a normal speed and the rest of the sentence is a still
# frame the viewer reads while the teacher talks - which is what an
# explanation looks like, rather than everything moving in slow motion.
ANIM_RUN_TIME_CAP = _get_float("ANIM_RUN_TIME_CAP", 1.0)

# What leaves the screen goes faster than what arrives: a departure is not
# information, it is the room being cleared for the next thing.
ANIM_EXIT_RUN_TIME = _get_float("ANIM_EXIT_RUN_TIME", 0.35)

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