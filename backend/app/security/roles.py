"""Who is allowed into the teacher's half of the product.

Ф1 put the role on the account and stopped the browser being the authority on
it. This is the other half: something that actually refuses. Until now nothing
did, because none of the teacher screens had a server behind them - assessments
are the first.

The check reads the account, not the request. A role that arrived in a body or
a header would be the same thing the browser used to decide for itself, only
further from home.
"""

from typing import Any, Dict

from fastapi import Request

from app.config import USER_ROLE_DEFAULT
from app.errors import HTTPExceptionJson
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token


async def require_user(request: Request) -> Dict[str, Any]:
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    return user


async def require_teacher(request: Request) -> Dict[str, Any]:
    """A signed-in teacher, or a refusal.

    403 rather than 404: a student knows perfectly well that the teacher
    screens exist - they are described on the landing page and the sign-up form
    offers the role - so hiding the endpoint protects nothing and only makes
    the refusal harder to understand. That is the opposite of the admin cache
    endpoint, which 404s because its existence is not public.
    """
    user = await require_user(request)
    if (user.get("role") or USER_ROLE_DEFAULT) != "teacher":
        raise HTTPExceptionJson(403, "This is available to teacher accounts")
    return user
