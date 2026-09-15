"""Writing, keeping and editing Қысқа мерзімді жоспар.

The short-term lesson plan a teacher in Kazakhstan submits for every lesson.
Teachers only, like assessments, and enforced here rather than merely stored.

Generation happens in the agent - it holds the API keys and the backend
deliberately holds none - and, like a paper, not through the graph the videos
go through: a plan is one text call, with no animation to decide on and
nothing to render. It travels the agent's fast lane, so a teacher waiting on a
plan is not queued behind somebody else's ninety-second animation.

WHAT THIS ENDPOINT DOES NOT DO is re-judge the plan. The agent owns the
document's shape and the checks that matter - that the stages add up to the
lesson, that an objective code belongs to the grade it claims, that every
stage says what the students do and not only the teacher. Repeating those here
would be two rules to keep in step and one of them would drift.
"""

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Request

from app.config import (
    LESSON_PLAN_DURATIONS,
    LESSON_PLAN_GRADES,
    LESSON_PLAN_LANGUAGES,
    LESSON_PLAN_MAX_PER_HOUR,
    LESSON_PLAN_SECTION_MAX_LEN,
    LESSON_PLAN_SUBJECTS,
    LESSON_PLAN_TIMEOUT_SEC,
    LESSON_PLAN_TOPIC_MAX_LEN,
)
from app.errors import HTTPExceptionJson
from app.models import LessonPlanRequest, PlanUpdate
from app.repositories import lesson_plans as repo
from app.security.ratelimit import LoginLimiter
from app.security.roles import require_teacher
from app.ws.manager import agent_manager

router = APIRouter()

# Per teacher, per hour. Reuses the limiter the login path uses, for the same
# reason assessments do: the shape is one rolling window over one key, and a
# second implementation would be a second thing to get wrong.
plan_limiter = LoginLimiter(LESSON_PLAN_MAX_PER_HOUR, 3600)

# What the agent's failures mean to somebody looking at the screen. Anything
# unrecognised is reported generically: the agent's wording is for a log.
_FAILURES = {
    "agent_unavailable": (503, "The generator is unavailable. Please try again shortly."),
    "timeout": (504, "The generator took too long. Please try again."),
}


def _validated_spec(body: LessonPlanRequest) -> Dict[str, Any]:
    """Every field against its closed set, before any of it reaches a prompt."""
    topic = (body.topic or "").strip()
    if not topic:
        raise HTTPExceptionJson(400, "Topic is required")
    if len(topic) > LESSON_PLAN_TOPIC_MAX_LEN:
        raise HTTPExceptionJson(
            400, f"Topic must be under {LESSON_PLAN_TOPIC_MAX_LEN} characters"
        )

    section = (body.section or "").strip()[:LESSON_PLAN_SECTION_MAX_LEN]

    if body.subject not in LESSON_PLAN_SUBJECTS:
        raise HTTPExceptionJson(400, "Unknown subject")
    if body.lang not in LESSON_PLAN_LANGUAGES:
        raise HTTPExceptionJson(400, "Unsupported language")
    if body.grade not in LESSON_PLAN_GRADES:
        raise HTTPExceptionJson(400, "Unsupported grade")
    if body.duration not in LESSON_PLAN_DURATIONS:
        raise HTTPExceptionJson(400, "Unsupported lesson length")

    return {
        "subject": body.subject,
        "grade": body.grade,
        "topic": topic,
        "lang": body.lang,
        "duration": body.duration,
        "section": section,
    }


def _with_ids(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Give each stage a stable id.

    Position is not an identity: a teacher who deletes the second stage must
    not thereby rename the third, and an edit opened on one stage has to land
    on that stage even if the plan was reordered underneath it.
    """
    stages = plan.get("stages") or []
    plan["stages"] = [
        {**stage, "id": f"s-{uuid.uuid4().hex[:12]}"} for stage in stages
    ]
    return plan


async def _ask_agent(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The plan, or an HTTP failure that says what to do about it."""
    result = await agent_manager.request_lesson_plan(
        {
            "subject": spec["subject"],
            "grade": spec["grade"],
            "topic": spec["topic"],
            "language": spec["lang"],
            "duration": spec["duration"],
            "section": spec["section"],
        },
        LESSON_PLAN_TIMEOUT_SEC,
    )

    error = str(result.get("error") or "")
    if error:
        status, message = _FAILURES.get(error, (502, "Could not write the plan."))
        raise HTTPExceptionJson(status, message)

    plan = result.get("plan") or {}
    if not plan.get("stages"):
        raise HTTPExceptionJson(502, "Could not write the plan.")
    return result


@router.post("/api/lesson-plans", status_code=201)
async def generate(body: LessonPlanRequest, request: Request):
    user = await require_teacher(request)
    user_id = str(user["_id"])

    if not plan_limiter.allow(f"plan:{user_id}"):
        raise HTTPExceptionJson(
            429,
            f"That is {LESSON_PLAN_MAX_PER_HOUR} plans this hour. Try again later.",
        )

    spec = _validated_spec(body)
    result = await _ask_agent(spec)
    return await repo.create_lesson_plan(
        user_id,
        spec,
        _with_ids(result["plan"]),
        int(result.get("minutes_planned") or 0),
    )


@router.get("/api/lesson-plans")
async def list_plans(request: Request):
    user = await require_teacher(request)
    return {"items": await repo.list_lesson_plans(str(user["_id"]))}


@router.get("/api/lesson-plans/{plan_id}")
async def read_plan(plan_id: str, request: Request):
    user = await require_teacher(request)
    plan = await repo.get_lesson_plan(plan_id, str(user["_id"]))
    if not plan:
        raise HTTPExceptionJson(404, "Lesson plan not found")
    return plan


@router.put("/api/lesson-plans/{plan_id}")
async def update_plan(plan_id: str, body: PlanUpdate, request: Request):
    """The plan as the teacher edited it.

    Stored as given. A plan is a document somebody is about to submit under
    their own name, so the teacher's wording wins over anything this endpoint
    might think about it - what is checked is that it is still a plan, not
    whether it is a good one.
    """
    user = await require_teacher(request)

    plan = body.plan
    if not isinstance(plan, dict) or not isinstance(plan.get("stages"), list):
        raise HTTPExceptionJson(400, "A plan must have stages")
    if not plan["stages"]:
        raise HTTPExceptionJson(400, "A plan must have at least one stage")

    updated = await repo.replace_plan(plan_id, str(user["_id"]), plan)
    if not updated:
        raise HTTPExceptionJson(404, "Lesson plan not found")
    return updated


@router.delete("/api/lesson-plans/{plan_id}")
async def remove_plan(plan_id: str, request: Request):
    user = await require_teacher(request)
    if not await repo.delete_lesson_plan(plan_id, str(user["_id"])):
        raise HTTPExceptionJson(404, "Lesson plan not found")
    return {"id": plan_id, "deleted": True}
