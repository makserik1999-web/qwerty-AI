"""Hashed traces of where an account signed up and signs in from.

Kept to spot trial farming and self-referral - many accounts from one
browser or one network - without keeping anyone's IP address. What is stored
is an HMAC: equal inputs give equal hashes, so accounts can be grouped, but
the address itself cannot be read back.

The device is a random id the browser keeps in local storage. Clearing it is
trivial; it catches the careless, not the determined, and is weighed as a
hint in the admin panel, never as proof.
"""

import hashlib
import hmac
from typing import Optional

from app import config

MAX_KEPT = 10


def _key() -> bytes:
    secret = config.PHONE_HASH_SECRET or hashlib.sha256(
        f"{config.AGENT_SECRET}:phone-claims".encode()).hexdigest()
    return hashlib.sha256(f"{secret}:fingerprint".encode()).digest()


def fingerprint(kind: str, value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()[:200]
    if not value:
        return None
    return hmac.new(_key(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:32]


def trace_update(ip: Optional[str], device: Optional[str]) -> dict:
    """A Mongo update that remembers this IP and device, newest first, capped."""
    push = {}
    for field, kind, value in (("ip_hashes", "ip", ip), ("device_hashes", "device", device)):
        digest = fingerprint(kind, value)
        if digest:
            push[field] = {"$each": [digest], "$position": 0, "$slice": MAX_KEPT}
    return {"$push": push} if push else {}
