"""Who may use /api/admin, decided by the account and nothing else.

`staff_role` is its own field, not a third value of `role`. `role` (student or
teacher) is picked by the person at signup; `staff_role` is written only by
`python -m app.staff` on the server. No HTTP route sets it - not signup, not
the profile, not the admin panel itself - so becoming staff takes a shell on
the server or the database, never a request.

Hiding the admin link from everyone else is the interface's business and
protects nothing. Every /api/admin route goes through `require_staff` below,
attached to the router so a new route cannot be added without it, and
tests/backend/test_admin.py calls every such route as a stranger to prove it.

The role is read from the database on each request (the session lookup
returns the account), so taking it away works on the next request rather than
at the next sign-in.
"""

from typing import Any, Dict, Optional

from fastapi import Depends, Request

from app.config import STAFF_ROLES
from app.errors import HTTPExceptionJson
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token

ADMIN = "admin"
SUPPORT = "support"


def staff_role_of(user: Optional[Dict[str, Any]]) -> Optional[str]:
    """The account's staff role, or None. Anything outside the set is None."""
    if not user:
        return None
    role = user.get("staff_role")
    return role if role in STAFF_ROLES else None


async def require_staff(request: Request) -> Dict[str, Any]:
    """Any staff role, or a 404.

    404 for everyone else, signed in or not: an endpoint you may not use
    should not confirm it exists.
    """
    user = await _user_from_token(_cookie_token(request))
    if not staff_role_of(user):
        raise HTTPExceptionJson(404, "Not found")
    return user


async def require_admin(user: Dict[str, Any] = Depends(require_staff)) -> Dict[str, Any]:
    """The admin role. Support gets 403: they know the panel exists."""
    if staff_role_of(user) != ADMIN:
        raise HTTPExceptionJson(403, "This needs the admin role")
    return user
