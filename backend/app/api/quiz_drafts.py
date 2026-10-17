"""Quiz questions written by the agent, for the quiz service to keep.

The quiz service is a service of its own and holds no model key, so it never
asks for generation itself. The editor asks here, gets questions back, and
saves them there. Nothing is kept on this side: a draft that is not saved is
a draft the teacher decided against. A draft written in the background waits
in its job until the page collects it, an hour at most, and is gone after.
"""

import uuid

from fastapi import APIRouter, Request, Response

from app.api.plan import refusal
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
from app.security.verified import require_may_generate
from app.services import jobs, plans, usage_log
from app.ws.manager import agent_manager

router = APIRouter()

# Per teacher, per hour - the same rolling window the other documents use.
draft_limiter = LoginLimiter(QUIZ_DRAFT_MAX_PER_HOUR, 3600)

# An edit replaces or adds a few questions; a whole quiz is a "new" draft.
EDIT_MAX_COUNT = 5

_FAILURES = {
    "agent_unavailable": (503, "The generator is unavailable. Please try again shortly."),
    "timeout": (504, "The generator took too long. Please try again."),
}


@router.post("/api/quiz-drafts")
async def draft(body: QuizDraftRequest, request: Request, response: Response):
    """Questions for the editor. `Prefer: respond-async` makes it a job to poll,
    for the same reason as a lesson plan: two minutes is past Cloudflare's 100 s."""
    user = await require_teacher(request)
    require_may_generate(user)

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
    if body.purpose not in ("new", "edit"):
        raise HTTPExceptionJson(400, "Unknown purpose")
    if body.purpose == "edit" and body.count > EDIT_MAX_COUNT:
        raise HTTPExceptionJson(400, f"Editing writes at most {EDIT_MAX_COUNT} questions at a time")

    if not draft_limiter.allow(f"quiz:{user['_id']}"):
        raise HTTPExceptionJson(
            429, f"That is {QUIZ_DRAFT_MAX_PER_HOUR} drafts this hour. Try again later."
        )

    avoid = [a.strip()[:400] for a in body.avoid[:QUIZ_DRAFT_MAX_AVOID]
             if isinstance(a, str) and a.strip()]

    # A new quiz is one of the plan's quizzes. Editing one that exists is
    # not counted, but still needs a plan: it is a model call all the same.
    ref = f"quiz_draft:{uuid.uuid4().hex}"
    try:
        if body.purpose == "new":
            await plans.reserve(user, "quiz_drafts", ref)
        elif (await plans.resolve(user)).kind == plans.FREE:
            raise plans.PlanRefusal("plan_required", "quiz_drafts")
    except plans.PlanRefusal as exc:
        raise refusal(exc) from None

    user_id = str(user["_id"])
    job_id = await jobs.start("quiz_draft", user_id, ref, spec={
        "topic": topic, "subject": body.subject, "grade": body.grade, "lang": body.lang,
        "count": body.count, "purpose": body.purpose})
    if job_id and jobs.wants_background(request):
        jobs.spawn(_produce(user_id, body, topic, avoid, ref, background=True))
        response.status_code = 202
        return {"job_id": job_id, "status": "queued"}
    return await _produce(user_id, body, topic, avoid, ref)


async def _produce(user_id: str, body: QuizDraftRequest, topic: str, avoid: list, ref: str,
                   background: bool = False):
    await jobs.running(ref)
    try:
        result = await _draft(body, topic, avoid)
    except BaseException as exc:
        await plans.release(ref)
        await jobs.failed(ref, exc)
        raise
    await plans.commit(ref)
    if body.purpose == "new":
        await usage_log.log(user_id, "quiz_draft")
    # Kept only when nobody is waiting on this response to hand it over.
    await jobs.finish(ref, ok=True, **({"result": result} if background else {}))
    return result


async def _draft(body: QuizDraftRequest, topic: str, avoid: list):
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
