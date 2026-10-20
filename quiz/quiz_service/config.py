"""Settings, read once from the environment at import time."""

import os
from typing import Tuple


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"FATAL: {name}={raw!r} is not an integer") from exc
    if value < minimum:
        raise SystemExit(f"FATAL: {name}={value} is below {minimum}")
    return value


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"FATAL: {name}={raw!r} is not a number") from exc
    if value < minimum:
        raise SystemExit(f"FATAL: {name}={value} is below {minimum}")
    return value


MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongo:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "anyq_db")

# Where a teacher's session cookie is resolved to an account. The backend owns
# accounts; this service only ever asks.
IDENTITY_URL = os.getenv("QUIZ_IDENTITY_URL", "http://backend:8000/api/auth/me")
SESSION_COOKIE = os.getenv("SESSION_COOKIE_NAME", "anyq_session")
# How long an answer from the backend is reused. A sign-out therefore reaches
# this service within this many seconds - acceptable for an editor, and what
# keeps an autosave every few seconds from becoming a request to the backend
# every few seconds.
IDENTITY_CACHE_SEC = _float("QUIZ_IDENTITY_CACHE_SEC", 30.0)

# The same allowlist the backend uses. The teacher's live board authenticates
# with the session cookie, and a WebSocket upgrade is not covered by CORS, so
# without this check any page could open one with the teacher's cookie.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]

MAX_QUESTIONS = _int("QUIZ_MAX_QUESTIONS", 50, 1)
MAX_QUIZZES_PER_OWNER = _int("QUIZ_MAX_PER_OWNER", 300, 1)

# A class, with room for a merged one. The ceiling exists so that a code read
# out loud in the wrong room cannot fill a session with strangers.
MAX_PLAYERS = _int("QUIZ_MAX_PLAYERS", 80, 1)
# Open at once, per teacher: a lesson running in two rooms is plausible, five
# open lobbies are a forgotten tab each.
MAX_OPEN_SESSIONS = _int("QUIZ_MAX_OPEN_SESSIONS", 3, 1)
# A session nobody ended is ended for them after this long, which is also what
# frees its code. Longer than any lesson, short enough that a code does not
# stay joinable overnight.
SESSION_MAX_HOURS = _float("QUIZ_SESSION_MAX_HOURS", 4.0, 0.1)

# The beat between the teacher pressing Start and the first question: every
# phone and the projector count down together from the same server time.
COUNTDOWN_SEC = _float("QUIZ_COUNTDOWN_SEC", 4.0)
# An answer that left the phone before the deadline can arrive after it.
ANSWER_GRACE_SEC = _float("QUIZ_ANSWER_GRACE_SEC", 3.0)

# Minutes. 0 is "no limit": the teacher ends it.
TIME_LIMITS: Tuple[int, ...] = (0, 3, 5, 10, 15, 20, 30, 45)

# Joins per address per ten minutes. A school is one address, so this is far
# above a class and only stops a script that guesses codes.
JOIN_MAX_PER_IP = _int("QUIZ_JOIN_MAX_PER_IP", 400, 1)
# Code lookups per address per ten minutes, for the same reason and the same
# script.
LOOKUP_MAX_PER_IP = _int("QUIZ_LOOKUP_MAX_PER_IP", 600, 1)

SUBJECTS: Tuple[str, ...] = (
    "math", "geometry", "physics", "chemistry", "biology", "informatics",
    "history", "geography", "language", "other",
)
LANGUAGES: Tuple[str, ...] = ("kk", "ru", "en")
GRADES: Tuple[int, ...] = tuple(range(0, 12))
