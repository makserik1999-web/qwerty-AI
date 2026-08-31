"""Every environment read and shared constant for the backend.

Moved verbatim out of main.py. Other modules import these names instead of
calling os.getenv themselves, mirroring how agent/anyq/config.py works.
"""

import os
import re
from datetime import timedelta
from pathlib import Path

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongo:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "anyq_db")

# Agent channel secret: both backend and agent must share it. When it is empty
# the backend refuses every agent connection (fail closed).
AGENT_SECRET = os.getenv("AGENT_SECRET", "")

# Cookie: HttpOnly + SameSite=Lax; Secure is enabled when the deployment sets
# COOKIE_SECURE=1 (behind TLS). Compose sets it for you when HTTPS_TERMINATED=1.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "720"))
SESSION_TTL = timedelta(hours=SESSION_TTL_HOURS)
COOKIE_NAME = "anyq_session"

# CORS allowlist (comma separated). Credentials are allowed, so origins must be
# explicit - never "*".
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if o.strip()
]

# Media directory: the shared volume where the agent drops rendered videos.
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/app/media"))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# Payload limits
MAX_PROMPT_LEN = int(os.getenv("MAX_PROMPT_LEN", "4000"))
MAX_TITLE_LEN = int(os.getenv("MAX_TITLE_LEN", "100"))
MAX_SCREENSHOTS = int(os.getenv("MAX_SCREENSHOTS", "3"))
MAX_SCREENSHOT_BYTES = int(os.getenv("MAX_SCREENSHOT_BYTES", str(2 * 1024 * 1024)))
MAX_SCREENSHOT_B64_LEN = MAX_SCREENSHOT_BYTES * 4 // 3 + 16

# Login rate limiting (in-memory; single-process uvicorn)
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SEC = int(os.getenv("LOGIN_WINDOW_SEC", "900"))  # 15 min

# Agent channel
AGENT_HANDSHAKE_TIMEOUT_SEC = float(os.getenv("AGENT_HANDSHAKE_TIMEOUT_SEC", "10"))
PENDING_REQUESTS_TTL_SEC = int(os.getenv("PENDING_REQUESTS_TTL_SEC", "1800"))
PENDING_SWEEP_INTERVAL_SEC = int(os.getenv("PENDING_SWEEP_INTERVAL_SEC", "60"))

_OBJECT_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")
_SAFE_MEDIA_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(mp4|webm|mov|m4v)$")
_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".m4v": "video/mp4",
}

# ============== Auth validation ==============
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ============== Answer cache ==============
# Bump PIPELINE_VERSION whenever the prompts, the model or the renderer change:
# it is part of every cache key, so raising it retires every stored answer at
# once instead of serving output the current pipeline would no longer produce.
PIPELINE_VERSION = os.getenv("PIPELINE_VERSION", "v1")

# Questions longer than this are somebody's specific problem, not a topic that
# repeats, so they are never cached.
CACHE_MAX_QUESTION_LEN = int(os.getenv("CACHE_MAX_QUESTION_LEN", "200"))

# A fresh answer is kept briefly; it only earns the long tier once the same
# question actually comes back this many times.
CACHE_EPHEMERAL_TTL_HOURS = int(os.getenv("CACHE_EPHEMERAL_TTL_HOURS", "48"))
CACHE_WARM_TTL_DAYS = int(os.getenv("CACHE_WARM_TTL_DAYS", "30"))
CACHE_WARM_PROMOTION_HITS = int(os.getenv("CACHE_WARM_PROMOTION_HITS", "3"))

# Master switch, so the cache can be turned off without a redeploy.
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "1") == "1"

# Usernames allowed to read cache statistics. Empty (the default) means nobody:
# the endpoint has to be opened deliberately, not left ajar.
ADMIN_USERS = {
    u.strip() for u in os.getenv("ADMIN_USERS", "").split(",") if u.strip()
}

# ============== Media retention ==============
# Disk budget for rendered videos. Collection only starts above the high-water
# mark and stops at the low-water one, so it runs rarely and in bulk instead of
# deleting a file every few minutes.
MEDIA_MAX_BYTES = int(os.getenv("MEDIA_MAX_BYTES", str(20 * 1024 * 1024 * 1024)))
MEDIA_GC_HIGH_WATER = float(os.getenv("MEDIA_GC_HIGH_WATER", "0.9"))
MEDIA_GC_LOW_WATER = float(os.getenv("MEDIA_GC_LOW_WATER", "0.75"))
# A video must survive at least this long: someone may be watching it.
MEDIA_MIN_AGE_HOURS = int(os.getenv("MEDIA_MIN_AGE_HOURS", "24"))
MEDIA_GC_INTERVAL_SEC = int(os.getenv("MEDIA_GC_INTERVAL_SEC", "3600"))

