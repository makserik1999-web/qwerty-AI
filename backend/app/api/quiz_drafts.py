"""Quiz questions written by the agent, for the quiz service to keep.

The quiz service is a service of its own and holds no model key, so it never
asks for generation itself. The editor asks here, gets questions back, and
saves them there. Nothing is stored on this side: a draft that is not saved
is a draft the teacher decided against.
"""

from fastapi import APIRouter, Request

from app.config import (
    QUIZ_DRAFT_DIFFICULTIES,
    QUIZ_DRAFT_GRADES,
    QUIZ_DRAFT_LANGUAGES,
    QUIZ_DRAFT_MAX_AVOID,
    QUIZ_DRAFT_MAX_COUNT,
    QUIZ_DRAFT_MAX_PER_HOUR,
    QUIZ_DRAFT_MIXES,
    QUIZ_DRAFT_SUBJECTS,
    QUIZ_DRAFT_TIMEOUT_SEC,
    QUIZ_DRAFT_TOPIC_MAX_LEN,
)
from app.errors import HTTPExceptionJson
from app.models import QuizDraftRequest
from app.security.ratelimit import LoginLimiter
from app.security.roles import require_teacher
from app.ws.manager import agent_manager

router = APIRouter()

# Per teacher, per hour - the same rolling window the other documents use.
draft_limiter = LoginLimiter(QUIZ_DRAFT_MAX_PER_HOUR, 3600)

_FAILURES = {
    "agent_unavailable": (503, "The generator is unavailable. Please try again shortly."),
    "timeout": (504, "The generator took too long. Please try again."),
}


@router.post("/api/quiz-drafts")
async def draft(body: QuizDraftRequest, request: Request):
    user = await require_teacher(request)

    topic = (body.topic or "").strip()
    if not topic:
        raise HTTPExceptionJson(400, "Topic is required")
    if len(topic) > QUIZ_DRAFT_TOPIC_MAX_LEN:
        raise HTTPExceptionJson(400, f"Topic must be under {QUIZ_DRAFT_TOPIC_MAX_LEN} characters")
    if body.subject not in QUIZ_DRAFT_SUBJECTS:
        raise HTTPExceptionJson(400, "Unknown subject")
    if body.lang not in QUIZ_DRAFT_LANGUAGES:
        raise HTTPExceptionJson(400, "Unsupported language")
    if body.grade not in QUIZ_DRAFT_GRADES:
        raise HTTPExceptionJson(400, "Unsupported grade")
    if body.mix not in QUIZ_DRAFT_MIXES:
        raise HTTPExceptionJson(400, "Unknown question mix")
    if body.difficulty not in QUIZ_DRAFT_DIFFICULTIES:
        raise HTTPExceptionJson(400, "Unknown difficulty")
    if not 1 <= body.count <= QUIZ_DRAFT_MAX_COUNT:
        raise HTTPExceptionJson(400, f"Between 1 and {QUIZ_DRAFT_MAX_COUNT} questions")

    if not draft_limiter.allow(f"quiz:{user['_id']}"):
        raise HTTPExceptionJson(
            429, f"That is {QUIZ_DRAFT_MAX_PER_HOUR} drafts this hour. Try again later."
        )

    avoid = [a.strip()[:400] for a in body.avoid[:QUIZ_DRAFT_MAX_AVOID]
             if isinstance(a, str) and a.strip()]
    result = await agent_manager.request_quiz(
        {
            "subject": body.subject,
            "grade": body.grade,
            "topic": topic,
            "language": body.lang,
            "count": body.count,
            "mix": body.mix,
            "difficulty": body.difficulty,
            "avoid": avoid,
        },
        QUIZ_DRAFT_TIMEOUT_SEC,
    )

    error = str(result.get("error") or "")
    if error:
        status, message = _FAILURES.get(error, (502, "Could not write the questions."))
        raise HTTPExceptionJson(status, message)
    questions = result.get("questions")
    if not isinstance(questions, list) or not questions:
        raise HTTPExceptionJson(502, "Could not write the questions.")
    return {"questions": questions, "requested": int(result.get("requested") or body.count)}
