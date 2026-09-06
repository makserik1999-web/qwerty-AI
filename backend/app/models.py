"""Request bodies accepted by the HTTP endpoints."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ChatCreate(BaseModel):
    title: Optional[str] = None


class SignupRequest(BaseModel):
    """Both identifiers are optional, but at least one has to be there.

    The interface asks for a name, an email and a role, and never for a
    username - so one is derived from the email. The field stays because it is
    the account's stable handle: chats, sessions and the admin allowlist are
    all keyed on it, and a person changing their email must not change who they
    are. Requests that do carry a username still work, which is what keeps the
    existing tests and the old sign-in screen honest.
    """

    username: Optional[str] = None
    email: Optional[str] = None
    password: str
    name: Optional[str] = None
    role: Optional[str] = None


class LoginRequest(BaseModel):
    """Sign in with either identifier; the new interface sends the email."""

    username: Optional[str] = None
    email: Optional[str] = None
    password: str


class ProfileRequest(BaseModel):
    """A partial update: only the fields present are touched."""

    name: Optional[str] = None
    email: Optional[str] = None


class ExportRequest(BaseModel):
    """What to export, and from which message.

    `params` is left loose here and validated per type in the endpoint: a gif
    needs a time range, a frame needs a timestamp, and a shared pydantic model
    for both would have to make every field optional anyway.
    """

    type: str
    message_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
