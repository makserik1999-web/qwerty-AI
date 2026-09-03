"""Request bodies accepted by the HTTP endpoints."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ChatCreate(BaseModel):
    title: Optional[str] = None


class SignupRequest(BaseModel):
    username: str
    email: Optional[str] = None
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ExportRequest(BaseModel):
    """What to export, and from which message.

    `params` is left loose here and validated per type in the endpoint: a gif
    needs a time range, a frame needs a timestamp, and a shared pydantic model
    for both would have to make every field optional anyway.
    """

    type: str
    message_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
