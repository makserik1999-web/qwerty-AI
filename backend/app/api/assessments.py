"""Writing, keeping and editing assessment papers.

The first part of the product that only teachers can reach, and therefore the
first place the role is enforced rather than merely stored. Ф1 moved the role
onto the account and out of the browser; this is where that starts refusing
somebody.

Generation itself happens in the agent - it holds the API keys, and the
backend deliberately holds none - but not through the graph the videos go
through. A paper is one text call: no animation to decide on, no script to
guard, no render. It travels on the agent's fast lane beside embeddings, so a
teacher waiting on a СОР is not queued behind somebody else's ninety-second
animation.
"""

import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.api.plan import refusal
from app.config import (
    ASSESSMENT_DIFFICULTIES,
    ASSESSMENT_GRADES,
    ASSESSMENT_LANGUAGES,
    ASSESSMENT_MAX_PER_HOUR,
    ASSESSMENT_MAX_QUESTIONS,
    ASSESSMENT_SUBJECTS,
    ASSESSMENT_TIMEOUT_SEC,
    ASSESSMENT_TOPIC_MAX_LEN,
    ASSESSMENT_TYPES,
)
from app.errors import HTTPExceptionJson
from app.models import AssessmentRequest, QuestionsUpdate
from app.repositories import assessments as repo
from app.security.ratelimit import LoginLimiter
from app.security.roles import require_teacher
from app.security.verified import require_may_generate
from app.services import docx_export, jobs, plans, usage_log
from app.services.export_naming import content_disposition, download_filename
from app.ws.manager import agent_manager

router = APIRouter()

# Per teacher, per hour. Reuses the limiter the login path uses: the shape is
# the same - a rolling window over one key - and a second implementation would
# be a second thing to get wrong.
assessment_limiter = LoginLimiter(ASSESSMENT_MAX_PER_HOUR, 3600)

# What the agent's failures mean to somebody looking at the screen. Anything
# unrecognised is reported as a generic failure rather than passed through:
# the agent's wording is for a log, not for a teacher.
_FAILURES = {
    "agent_unavailable": (503, "The generator is unavailable. Please try again shortly."),
    "timeout": (504, "The generator took too long. Please try again."),
}


def _validated_spec(body: AssessmentRequest) -> Dict[str, Any]:
    """Every field against its closed set, before any of it reaches a prompt."""
    topic = (body.topic or "").strip()
    if not topic:
        raise HTTPExceptionJson(400, "Topic is required")
    if len(topic) > ASSESSMENT_TOPIC_MAX_LEN:
        raise HTTPExceptionJson(400, f"Topic must be under {ASSESSMENT_TOPIC_MAX_LEN} characters")

    if body.subject not in ASSESSMENT_SUBJECTS:
        raise HTTPExceptionJson(400, "Unknown subject")
    if body.type not in ASSESSMENT_TYPES:
        raise HTTPExceptionJson(400, "Unknown assessment type")
    if body.difficulty not in ASSESSMENT_DIFFICULTIES:
        raise HTTPExceptionJson(400, "Unknown difficulty")
    if body.lang not in ASSESSMENT_LANGUAGES:
        raise HTTPExceptionJson(400, "Unsupported language")
    if body.grade not in ASSESSMENT_GRADES:
        raise HTTPExceptionJson(400, "Unsupported grade")

    count = max(1, min(ASSESSMENT_MAX_QUESTIONS, int(body.count or 5)))
    return {
        "subject": body.subject,
        "grade": body.grade,
        "topic": topic,
        "type": body.type,
        "difficulty": body.difficulty,
        "lang": body.lang,
        "count": count,
        "variants": 2 if int(body.variants or 1) >= 2 else 1,
    }


def _with_ids(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Give each question a stable id.

    Position is not an identity: a teacher who deletes the second question
    must not thereby rename the third, and an edit in flight must land on the
    question it was opened from.
    """
    return [
        {"id": f"q-{uuid.uuid4().hex[:12]}", "text": q["text"], "marks": q["marks"]}
        for q in questions
    ]


async def _ask_agent_paper(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The agent's paper - `questions`, and `variant2` if two were asked for
    and both came - or an HTTP failure that says what to do about it."""
    result = await agent_manager.request_assessment(
        {
            "subject": spec["subject"],
            "grade": spec["grade"],
            "topic": spec["topic"],
            "type": spec["type"],
            "difficulty": spec["difficulty"],
            "language": spec["lang"],
            "count": spec["count"],
            "variants": spec.get("variants", 1),
        },
        ASSESSMENT_TIMEOUT_SEC,
    )

    error = str(result.get("error") or "")
    if error:
        status, message = _FAILURES.get(error, (502, "Could not write the paper."))
        raise HTTPExceptionJson(status, message)

    if not result.get("questions"):
        raise HTTPExceptionJson(502, "Could not write the paper.")
    return result


async def _ask_agent(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The questions, or an HTTP failure that says what to do about it."""
    return (await _ask_agent_paper({**spec, "variants": 1}))["questions"]


@router.post("/api/assessments", status_code=201)
async def generate(body: AssessmentRequest, request: Request):
    user = await require_teacher(request)
    require_may_generate(user)
    user_id = str(user["_id"])

    if not assessment_limiter.allow(f"assess:{user_id}"):
        raise HTTPExceptionJson(
            429,
            f"That is {ASSESSMENT_MAX_PER_HOUR} papers this hour. Try again later.",
        )

    spec = _validated_spec(body)
    # One paper off the plan; given back if no paper comes of it.
    ref = f"assessment:{uuid.uuid4().hex}"
    try:
        await plans.reserve(user, "assessments", ref)
    except plans.PlanRefusal as exc:
        raise refusal(exc) from None
    await jobs.start("assessment", user_id, ref, spec=spec)
    await jobs.running(ref)
    try:
        # Two variants are one paper, so one off the plan, not two.
        paper = await _ask_agent_paper(spec)
        second = paper.get("variant2") if spec["variants"] == 2 else None
        created = await repo.create_assessment(user_id, spec, _with_ids(paper["questions"]),
                                               _with_ids(second) if second else None)
    except BaseException as exc:
        await plans.release(ref)
        await jobs.failed(ref, exc)
        raise
    await plans.commit(ref)
    await usage_log.log(user_id, "assessment")
    await jobs.finish(ref, ok=True, output_id=created["id"])
    return created


@router.get("/api/assessments")
async def list_papers(request: Request):
    user = await require_teacher(request)
    return {"items": await repo.list_assessments(str(user["_id"]))}


@router.get("/api/assessments/{assessment_id}")
async def read_paper(assessment_id: str, request: Request):
    user = await require_teacher(request)
    found = await repo.get_assessment(assessment_id, str(user["_id"]))
    if not found:
        raise HTTPExceptionJson(404, "Not found")
    return found


DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/api/assessments/{assessment_id}/docx")
async def paper_docx(assessment_id: str, request: Request):
    """The paper as a Word file. Anyone who has the paper may download it;
    the plan only decides whether "Akron арқылы жасалды" is in the footer."""
    user = await require_teacher(request)
    found = await repo.get_assessment(assessment_id, str(user["_id"]))
    if not found:
        raise HTTPExceptionJson(404, "Not found")
    entitlement = await plans.resolve(user, activate=False)
    signature = not (entitlement.kind == plans.ON_USTAZ
                     and not (entitlement.plan or {}).get("docx_signature"))
    content = docx_export.assessment_docx(found, signature=signature)
    name = download_filename(f"{docx_export.title_of(found)} {found.get('topic', '')}", ".docx")
    return Response(content, media_type=DOCX_TYPE,
                    headers={"Content-Disposition": content_disposition(name)})


@router.put("/api/assessments/{assessment_id}/questions")
async def save_questions(assessment_id: str, body: QuestionsUpdate, request: Request):
    """The paper as edited. Text and marks only - ids and order come from here.

    The whole list is replaced rather than patched question by question. A
    paper is a document: what is printed has to be what was on screen, and a
    sequence of per-question patches can interleave into something that was
    never either.
    """
    user = await require_teacher(request)

    cleaned: List[Dict[str, Any]] = []
    for item in body.questions[:ASSESSMENT_MAX_QUESTIONS]:
        text = str(item.get("text") or "").strip()[:600]
        if not text:
            continue
        try:
            marks = int(item.get("marks"))
        except (TypeError, ValueError):
            marks = 1
        cleaned.append({
            "id": str(item.get("id") or f"q-{uuid.uuid4().hex[:12]}")[:32],
            "text": text,
            "marks": max(1, min(20, marks)),
        })

    if not cleaned:
        raise HTTPExceptionJson(400, "A paper needs at least one question")

    variant = _variant(body.variant)
    if variant == 2:
        paper = await repo.get_assessment(assessment_id, str(user["_id"]))
        if not paper:
            raise HTTPExceptionJson(404, "Not found")
        if not paper.get("variant2"):
            raise HTTPExceptionJson(404, "This paper has one variant")
    saved = await repo.replace_questions(assessment_id, str(user["_id"]), cleaned, variant=variant)
    if not saved:
        raise HTTPExceptionJson(404, "Not found")
    return saved


def _variant(value: Any) -> int:
    try:
        return 2 if int(value) == 2 else 1
    except (TypeError, ValueError):
        return 1


@router.post("/api/assessments/{assessment_id}/questions/{question_id}/regenerate")
async def regenerate_question(assessment_id: str, question_id: str, request: Request, variant: int = 1):
    """Swap one question for another on the same paper.

    Asks for a small batch and takes the first one whose text is not already
    on the paper, so pressing the button twice does not hand back what is
    there. Falls back to the first if they all collide - a repeat is a worse
    answer than a failure here, but not by much, and the teacher can press it
    again.

    In 2-нұсқа the new question keeps the old one's marks: the two variants
    are marked on one scale, and a swap must not tip one of them.
    """
    user = await require_teacher(request)
    require_may_generate(user)
    user_id = str(user["_id"])

    if not assessment_limiter.allow(f"assess:{user_id}"):
        raise HTTPExceptionJson(
            429,
            f"That is {ASSESSMENT_MAX_PER_HOUR} papers this hour. Try again later.",
        )

    paper = await repo.get_assessment(assessment_id, user_id)
    if not paper:
        raise HTTPExceptionJson(404, "Not found")

    variant = _variant(variant)
    questions: List[Dict[str, Any]] = paper["variant2"] if variant == 2 else paper["questions"]
    index = next((i for i, q in enumerate(questions) if q.get("id") == question_id), -1)
    if index < 0:
        raise HTTPExceptionJson(404, "No such question on this paper")

    spec = {
        "subject": paper["subject"],
        "grade": paper["grade"],
        "topic": paper["topic"],
        "type": paper["type"],
        "difficulty": paper["difficulty"],
        "lang": paper["lang"],
        "count": 3,
    }
    candidates = await _ask_agent(spec)

    # Neither variant's questions: a swap that copies the other variant's
    # question undoes the point of having two.
    existing = {q["text"].strip().lower() for q in paper["questions"] + paper["variant2"]}
    fresh = next(
        (c for c in candidates if c["text"].strip().lower() not in existing),
        candidates[0],
    )

    questions[index] = {
        # The id stays: the interface has this question open, and changing it
        # would leave whatever it does next pointing at nothing.
        "id": question_id,
        "text": fresh["text"],
        "marks": questions[index]["marks"] if variant == 2 else fresh["marks"],
    }
    saved = await repo.replace_questions(assessment_id, user_id, questions, variant=variant)
    if not saved:
        raise HTTPExceptionJson(404, "Not found")
    return saved


@router.delete("/api/assessments/{assessment_id}")
async def delete_paper(assessment_id: str, request: Request):
    user = await require_teacher(request)
    if not await repo.delete_assessment(assessment_id, str(user["_id"])):
        raise HTTPExceptionJson(404, "Not found")
    return {"ok": True}
