"""Join codes: six characters a class can read off a projector.

The alphabet leaves out every character that has a twin at the back of a
classroom - 0/O, 1/I/L, 2/Z, 5/S, 8/B - so a code read aloud or copied from a
blurry screen is still the code. 25 characters over six places is about 240
million codes, against a handful open at any moment.
"""

import re
import secrets

ALPHABET = "ACDEFGHJKMNPQRTUVWXY34679"
LENGTH = 6

_CODE_RE = re.compile(f"^[{ALPHABET}]{{{LENGTH}}}$")


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def normalize(raw: str) -> str:
    """What a student typed, as a code - or "" if it cannot be one."""
    code = re.sub(r"[\s\-_.]", "", (raw or "")).upper()
    return code if _CODE_RE.fullmatch(code) else ""
