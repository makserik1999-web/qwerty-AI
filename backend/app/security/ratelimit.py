"""In-memory login rate limiting."""

import time
from typing import Dict, List

from fastapi import Request

from app.config import LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SEC


class LoginLimiter:
    """Simple in-memory limiter keyed by ip and ip+username."""

    def __init__(self, max_attempts: int, window_sec: int):
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self._attempts: Dict[str, List[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_sec
        stamps = [t for t in self._attempts.get(key, []) if t > cutoff]
        if len(stamps) >= self.max_attempts:
            self._attempts[key] = stamps
            return False
        stamps.append(now)
        self._attempts[key] = stamps
        # Bound the dict size
        if len(self._attempts) > 10000:
            for k in list(self._attempts.keys())[:5000]:
                self._attempts.pop(k, None)
        return True

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)


login_limiter = LoginLimiter(LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SEC)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
