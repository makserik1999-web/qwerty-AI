"""Whether an account may start a generation, as far as its email goes.

With REQUIRE_VERIFIED_EMAIL=1 an account must have confirmed its address
before it spends anything: a video, a paper, a lesson plan, a quiz draft.
Signing in, reading and watching what the library already has stay open -
the person needs to be able to reach the "send the link again" button.

Off by default, and it should stay off until mail actually leaves the server:
switched on earlier, nobody could get the link that unlocks them.
"""

from typing import Any, Dict

from app import config
from app.errors import HTTPExceptionJson

EMAIL_UNVERIFIED = "email_unverified"
MESSAGE = "Confirm your email address first - we sent you a link."


def email_confirmed(user: Dict[str, Any]) -> bool:
    return bool(user.get("email") and user.get("email_verified_at"))


def may_generate(user: Dict[str, Any]) -> bool:
    return not config.REQUIRE_VERIFIED_EMAIL or email_confirmed(user)


def require_may_generate(user: Dict[str, Any]) -> None:
    if not may_generate(user):
        raise HTTPExceptionJson(403, MESSAGE, code=EMAIL_UNVERIFIED)
