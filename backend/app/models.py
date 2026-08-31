"""Request bodies accepted by the HTTP endpoints."""

from typing import Optional

from pydantic import BaseModel


class ChatCreate(BaseModel):
    title: Optional[str] = None


class SignupRequest(BaseModel):
    username: str
    email: Optional[str] = None
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str
