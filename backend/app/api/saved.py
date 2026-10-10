"""The Library screen: a person's own saved explanations.

The name is a trap, so it is worth being loud about it. `/api/admin/cache/stats`
in api/library.py reports on `library_entries`, which is the GLOBAL answer
cache - other people's questions, one row serving everybody. This module is
the other thing entirely: private rows, one per person, that a person made by
pressing Save.

Nothing here touches the cache, and nothing in the cache is reachable from
here. Confusing them would mean "remove from my library" deleting an answer
for strangers, and a search showing them other people's questions.
"""

from typing import Any, Dict

from fastapi import APIRouter, Request

from app.config import CONTENT_LANGUAGES, CONTENT_SUBJECTS
from app.errors import HTTPExceptionJson
from app.models import RenameRequest, SaveRequest
from app.repositories import messages as messages_repo
from app.repositories import saved as repo
from app.security.roles import require_user

router = APIRouter()


def _label(value: str, allowed: tuple, fallback: str) -> str:
    """A badge on a card, checked against the set the interface offers.

    Wrong here costs a mislabelled card and nothing else - the subject is a
    guess even when the interface is right - but free text would still be free
    text arriving in a filter, so it is checked anyway.
    """
    value = (value or "").strip().lower()
    return value if value in allowed else fallback


@router.get("/api/library")
async def list_saved(request: Request):
    user = await require_user(request)
    return {"items": await repo.list_saved(str(user["_id"]))}


@router.post("/api/library", status_code=201)
async def save(body: SaveRequest, request: Request):
    """Save an answer by its message id.

    The id, not the answer. The client has the text on screen and could send
    it, but then a library row would be whatever the browser said it was -
    and the point of saving is that it is a record of what the agent actually
    replied.
    """
    user = await require_user(request)
    user_id = str(user["_id"])

    message: Dict[str, Any] | None = await messages_repo.owned_message(
        body.message_id, user_id
    )
    if not message or message.get("role") != "assistant":
        # Same answer for "no such message", "not yours" and "that is your own
        # question, not an answer".
        raise HTTPExceptionJson(404, "Not found")

    existing = await repo.already_saved(user_id, body.message_id)
    if existing:
        # Not an error: the button was pressed twice, or in two tabs. Hand
        # back the card that is already there.
        return existing

    if await repo.count_for(user_id) >= repo.MAX_SAVED:
        raise HTTPExceptionJson(
            409, f"A library holds {repo.MAX_SAVED} explanations. Remove one first."
        )

    question = (body.question or "").strip()
    if not question:
        # The question this answer replies to, when the client did not say.
        # Read from the chat rather than from the answer: a card titled with
        # the first line of the explanation is a card nobody recognises.
        question = await messages_repo.question_before(message)

    return await repo.save(
        user_id,
        message,
        question,
        _label(body.subject, CONTENT_SUBJECTS, "physics"),
        _label(body.lang, CONTENT_LANGUAGES, "kk"),
    )


@router.patch("/api/library/{saved_id}")
async def rename(saved_id: str, body: RenameRequest, request: Request):
    user = await require_user(request)
    question = (body.question or "").strip()
    if not question:
        raise HTTPExceptionJson(400, "A title cannot be empty")

    renamed = await repo.rename(saved_id, str(user["_id"]), question)
    if not renamed:
        raise HTTPExceptionJson(404, "Not found")
    return renamed


@router.delete("/api/library/{saved_id}")
async def remove(saved_id: str, request: Request):
    """Removes the card. The video is shared and stays where it is."""
    user = await require_user(request)
    if not await repo.remove(saved_id, str(user["_id"])):
        raise HTTPExceptionJson(404, "Not found")
    return {"ok": True}
