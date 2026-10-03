"""Sliding-window counters, in memory.

One process holds them, which is right for one replica. A second replica
would need them in shared storage - the same move the live hub would need,
and for the same reason.
"""

import time
from typing import Dict, List

from fastapi import Request


class Window:
    def __init__(self, limit: int, seconds: float):
        self.limit = limit
        self.seconds = seconds
        self._hits: Dict[str, List[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        stamps = [t for t in self._hits.get(key, []) if t > now - self.seconds]
        if len(stamps) >= self.limit:
            self._hits[key] = stamps
            return False
        stamps.append(now)
        self._hits[key] = stamps
        if len(self._hits) > 20000:
            for stale in list(self._hits)[:10000]:
                self._hits.pop(stale, None)
        return True

    def clear(self) -> None:
        self._hits.clear()


def client_ip(request: Request) -> str:
    """The address nginx accepted the connection from.

    X-Real-IP, which nginx overwrites. Not the first X-Forwarded-For entry,
    which the client writes itself - the backend's limits were bypassable with
    exactly that header until it stopped trusting it.
    """
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
