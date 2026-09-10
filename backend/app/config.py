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

# What a person is called on screen. Free text, because names are, so the only
# rule is a length that cannot be used to push anything else off the page.
NAME_MAX_LEN = 80

# Which interface a person gets. A closed set for the same reason the narration
# voices are one: this value is chosen by the client, and anything outside the
# set has to fall back rather than be stored. The default is deliberately the
# lesser of the two - a request with no role, or with a role we do not
# recognise, must never come out the other side as a teacher.
USER_ROLES = ("student", "teacher")
USER_ROLE_DEFAULT = "student"


# ============== Assessments ==============
# Closed sets, because every one of these reaches a prompt. Free text there is
# somebody else's instructions with extra steps, and the interface only ever
# offers these values anyway.
# The subjects and content languages the product knows, wherever it labels
# something. Assessments named them first; the aliases below keep that code
# reading as it did.
CONTENT_SUBJECTS = ("math", "geometry", "physics", "chemistry", "biology", "informatics")
CONTENT_LANGUAGES = ("kk", "ru")

ASSESSMENT_SUBJECTS = CONTENT_SUBJECTS
ASSESSMENT_TYPES = ("sor", "soch", "quiz")
ASSESSMENT_DIFFICULTIES = ("easy", "medium", "hard")
ASSESSMENT_LANGUAGES = CONTENT_LANGUAGES
ASSESSMENT_GRADES = tuple(range(5, 12))
ASSESSMENT_MAX_QUESTIONS = 20
ASSESSMENT_TOPIC_MAX_LEN = 200
# Writing a paper is one text call, so this is generous next to the video
# quota - but not unbounded: it still costs tokens, and a loop in somebody's
# script should not be able to spend the month's budget in an afternoon.
ASSESSMENT_MAX_PER_HOUR = int(os.getenv("ASSESSMENT_MAX_PER_HOUR", "40"))
ASSESSMENT_TIMEOUT_SEC = float(os.getenv("ASSESSMENT_TIMEOUT_SEC", "90"))


# ============== Narration ==============
# The speech itself is synthesised in the agent, which holds the Azure key;
# the backend only records what was asked for, so it can key the cache on
# it and pass it along.
NARRATION_DEFAULT = os.getenv("NARRATION_DEFAULT", "1") != "0"
NARRATION_VOICES = ("aigul", "daulet")
NARRATION_VOICE_DEFAULT = os.getenv("NARRATION_VOICE", "aigul")
if NARRATION_VOICE_DEFAULT not in NARRATION_VOICES:
    NARRATION_VOICE_DEFAULT = "aigul"




# ============== Answer cache ==============
# Bump PIPELINE_VERSION whenever the prompts, the model or the renderer change:
# it is part of every cache key, so raising it retires every stored answer at
# once instead of serving output the current pipeline would no longer produce.
# v2: narration. Every stored answer before this was rendered silent, and
# the pipeline now speaks by default, so serving them would hand people a
# mute video for a question they asked with the voice on.
# v3: the model default moved from gemini-3.7-flash to gemini-3.8-flash. A
# cached answer is a recording of what one model wrote; keeping it would mean
# the switch quietly did not apply to exactly the questions asked most often.
PIPELINE_VERSION = os.getenv("PIPELINE_VERSION", "v2")

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



# ============== Export jobs ==============
# Where finished exports land. A separate directory from MEDIA_DIR because
# these are derived, disposable files: they are swept on a fixed TTL rather
# than by the value-based scoring that protects rendered videos.
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "/app/media/exports"))

# Export results are not videos. Reusing _SAFE_MEDIA_RE here would 404 every
# gif, png and pptx on download while letting mp4 clips through - so exports
# get their own allowlist, with the same no-separator, no-traversal shape.
_SAFE_EXPORT_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(gif|mp4|webm|png|pptx|pdf)$")
EXPORT_TTL_HOURS = int(os.getenv("EXPORT_TTL_HOURS", "24"))

# Encoding is CPU-heavy and runs on the same box as Manim, so a user cannot
# queue an unbounded amount of it.
EXPORT_MAX_PER_HOUR = int(os.getenv("EXPORT_MAX_PER_HOUR", "5"))

# A GIF grows with the square of its dimensions and linearly with length; past
# ~15 seconds it stops being a GIF and becomes a bad video.
EXPORT_MAX_CLIP_SEC = float(os.getenv("EXPORT_MAX_CLIP_SEC", "15"))
EXPORT_MAX_OUTPUT_BYTES = int(os.getenv("EXPORT_MAX_OUTPUT_BYTES", str(20 * 1024 * 1024)))

# A job that is still "running" after this long is presumed dead: the worker
# was killed mid-encode, and nothing else would ever move it out of the state.
EXPORT_JOB_TIMEOUT_SEC = int(os.getenv("EXPORT_JOB_TIMEOUT_SEC", "600"))


# ============== Generation quotas ==============
# Authorisation alone does not bound load: signup is open, and rendering is the
# most expensive thing the system does. These are what make "logged-in only"
# actually mean something.
#
# The binding limit is CONCURRENT, not the hourly one. A generation occupies
# the single agent for about a minute and a half, so one user with one slot
# cannot queue work faster than it drains - the per-hour and per-day numbers
# are comfort limits on top of that, deliberately generous.
GENERATION_MAX_CONCURRENT = int(os.getenv("GENERATION_MAX_CONCURRENT", "1"))
GENERATION_MAX_PER_HOUR = int(os.getenv("GENERATION_MAX_PER_HOUR", "15"))
GENERATION_MAX_PER_DAY = int(os.getenv("GENERATION_MAX_PER_DAY", "50"))

# With one agent, a queue longer than this is not a queue, it is a lie about
# how soon anyone will be served.
GENERATION_QUEUE_MAX = int(os.getenv("GENERATION_QUEUE_MAX", "20"))

# Per IP, per hour. Deliberately loose, for two reasons.
#
# A school computer room shares one address: 30 students signing up together
# is a normal Tuesday, and a tight limit would lock out the back half of the
# class. And this is not the limit that bounds cost - the per-user generation
# quota is, and behind it the single agent caps total output at roughly 40
# videos an hour however many accounts exist. So this one only has to make
# mass account farming inconvenient, not impossible.
#
# It is in-memory, so restarting the backend clears it. That is the intended
# escape hatch when a test run exhausts it.
SIGNUP_MAX_PER_HOUR = int(os.getenv("SIGNUP_MAX_PER_HOUR", "100"))


# ============== Semantic cache layer (L2) ==============
# Exact matching only catches the same wording. This layer catches the same
# question asked differently - but it is the layer that can hand someone an
# answer to a question they did not ask, so it is tuned conservatively.
#
# The threshold was measured, not guessed. On labelled pairs of this
# product's own questions, genuinely different questions reach 0.797 and
# paraphrases of the same question start at 0.701 - the bands overlap, so no
# threshold is perfect. 0.85 sits above every observed different-question
# pair with margin, catching about half the paraphrases and none of the
# collisions. Raise it if a wrong answer ever appears; lower it only with
# fresh measurements.
CACHE_SEMANTIC_ENABLED = os.getenv("CACHE_SEMANTIC_ENABLED", "1") == "1"
CACHE_SEMANTIC_THRESHOLD = float(os.getenv("CACHE_SEMANTIC_THRESHOLD", "0.85"))

# Matching NEVER crosses languages. A Kazakh and a Russian phrasing of the
# same question score 0.92 - above any usable threshold - so without this a
# Kazakh student would be handed a Russian video. This is not a tuning knob.
CACHE_SEMANTIC_SAME_LANGUAGE_ONLY = True

# The agent owns the embedding key, so a lookup costs a round trip. Short:
# the fallback is a normal generation, and waiting seconds to maybe avoid one
# is a bad trade.
CACHE_EMBED_TIMEOUT_SEC = float(os.getenv("CACHE_EMBED_TIMEOUT_SEC", "4"))

# Above this many stored vectors, the in-process scan below stops being
# cheap and the search belongs in a vector index instead.
CACHE_SEMANTIC_MAX_CANDIDATES = int(os.getenv("CACHE_SEMANTIC_MAX_CANDIDATES", "5000"))
