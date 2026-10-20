"""In-memory rate limiting for the auth endpoints."""

import time
from typing import Dict, List

from fastapi import Request

from app.config import (
    LOGIN_IP_MAX_FAILURES,
    LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_SEC,
    SIGNUP_MAX_PER_HOUR,
)


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
        self._bound()
        return True

    def blocked(self, key: str) -> bool:
        """Whether `key` has used up its window, WITHOUT spending any of it.

        For a budget only failures should spend: ask this before the attempt,
        and call `hit` once it has actually failed. `allow` cannot do that job -
        it spends a slot on the way in, so a success would have to hand the
        slot back, and handing back is what `reset` did to the whole key.
        """
        cutoff = time.monotonic() - self.window_sec
        stamps = [t for t in self._attempts.get(key, []) if t > cutoff]
        if stamps:
            self._attempts[key] = stamps
        else:
            self._attempts.pop(key, None)
        return len(stamps) >= self.max_attempts

    def hit(self, key: str) -> None:
        """Spend one slot of `key`'s window."""
        self._attempts.setdefault(key, []).append(time.monotonic())
        self._bound()

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)

    def _bound(self) -> None:
        # Bound the dict size
        if len(self._attempts) > 10000:
            for k in list(self._attempts.keys())[:5000]:
                self._attempts.pop(k, None)


login_limiter = LoginLimiter(LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SEC)

# Failed sign-ins per IP. Separate from the per-account budget above because it
# guards against something else: not guessing one password, but trying one or
# two common passwords against many accounts, which no per-account limit sees.
#
# Only failures spend it and a success does not clear it. It used to be the
# same attempt budget as the account one, reset by any successful sign-in -
# so anyone with an account of their own could clear it between guesses by
# logging into that account. Counting failures alone is also what lets a
# classroom behind one address sign in together without the successes
# locking the class out.
login_ip_limiter = LoginLimiter(LOGIN_IP_MAX_FAILURES, LOGIN_WINDOW_SEC)

# Account creation, per IP per hour. Generous on purpose: a school computer
# room shares one address, so a tight limit would lock out a whole class
# signing up together while barely slowing a script down. The limit that
# actually bounds cost is the per-user generation quota, not this one.
signup_limiter = LoginLimiter(SIGNUP_MAX_PER_HOUR, 3600)


def _client_ip(request: Request) -> str:
    """The address of whoever is actually on the other end.

    The backend is reachable only through nginx (its port is not published),
    and nginx sets X-Real-IP to the peer it accepted the connection from,
    overwriting anything the browser sent under that name.

    X-Forwarded-For is not like that: nginx APPENDS the peer to whatever value
    the client supplied, so the FIRST entry is whatever the client chose to
    write there. That entry was the one being read, which let anyone get a
    fresh per-IP budget on every request by inventing an address - the signup
    and login limits held against nobody who knew the header existed. Where
    X-Real-IP is missing, the last entry is the one the proxy added.
    """
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
