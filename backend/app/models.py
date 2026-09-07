"""Request bodies accepted by the HTTP endpoints."""

from typing import Any, Dict, List, Optional

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


class AssessmentRequest(BaseModel):
    """What paper to write. Every field is checked against a closed set in the
    endpoint before it goes anywhere near a prompt - the topic is the only free
    text, and it is wrapped as untrusted data in the agent."""

    subject: str
    grade: int
    topic: str
    type: str
    difficulty: str
    lang: str
    count: int = 5


class QuestionsUpdate(BaseModel):
    """The paper as the teacher edited it: reworded, reordered or shortened."""

    questions: List[Dict[str, Any]]


class SaveRequest(BaseModel):
    """Save an answer to my library, addressed by the message that carried it.

    `question`, `subject` and `lang` are labels for the card. The body of the
    explanation is never taken from here - it is read from the message, so a
    saved answer is a record of what the agent replied rather than of what a
    browser said it replied.
    """

    message_id: str
    question: Optional[str] = None
    subject: Optional[str] = None
    lang: Optional[str] = None


class RenameRequest(BaseModel):
    question: str
