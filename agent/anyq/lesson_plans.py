"""Қысқа мерзімді жоспар: the short-term lesson plan a teacher has to submit.

Not a summary of a lesson - a document with a fixed shape that schools in
Kazakhstan require, and that a teacher writes for every lesson they give. The
sections below are that shape, not an arrangement chosen here: a plan missing
`саралау` or `бағалау критерийлері` is a plan that gets handed back.

Text, not video, so like assessments this does not go through the graph, and
it lives in the agent for the same one reason: the API keys are here and
nowhere else.

WHAT THE MODEL DOES NOT WRITE. The teacher's name, the date, who was present,
and the reflection written after the lesson are all left out. A model cannot
know them, and a document that arrives with them already filled in invites
somebody to submit a plausible-looking lie about their own classroom.

WHAT IS CHECKED MECHANICALLY, because a plan is judged on its shape:

  - Objective codes. The curriculum codes them `grade.section.subsection.item`
    - 8.2.1.4 is a grade-8 objective - so a code whose first number is not the
    grade is wrong, and a model that invents codes gets this wrong first. The
    objective's TEXT is kept and the bad code dropped: a teacher can look up a
    code, and cannot un-submit a document that carried a made-up one.
  - Time. The stages have to add up to the lesson. A forty-minute lesson
    planned in sixty-three minutes of stages is not a plan, and the teacher
    finds out in front of a class.
  - Both columns of every stage. `Оқушының әрекеті` left empty is the single
    most common way one of these documents is useless - it becomes a lecture
    plan with a column for decoration.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from spoon_ai.schema import Message

from anyq import telemetry
from anyq.language import _language_name
from anyq.llm_client import _llm_chat
from anyq.nodes import USER_CONTENT_NOTICE, _wrap
from anyq.script_guard import _safe_json_loads

# The three parts of the lesson, in the order the form has them, with the
# share of the lesson each one normally gets. The shares are what the model is
# asked for; the total is what gets checked.
PHASES: Tuple[str, ...] = ("start", "middle", "end")
_PHASE_SHARE: Dict[str, float] = {"start": 0.12, "middle": 0.75, "end": 0.13}

# Lesson lengths a school timetable actually uses.
DURATIONS: Tuple[int, ...] = (40, 45)
DEFAULT_DURATION = 40

MIN_STAGES = 4
MAX_STAGES = 12
MAX_OBJECTIVES = 6
MAX_CRITERIA = 6
MAX_TOPIC_CHARS = 200
MAX_SECTION_CHARS = 200
MAX_FIELD_CHARS = 1200
MAX_STAGE_FIELD_CHARS = 900

# How far the planned minutes may be from the lesson before the plan is
# refused. Ten per cent of forty minutes is four - close enough that a teacher
# absorbs it, far enough that a plan built for the wrong lesson is caught.
DURATION_TOLERANCE = 0.10

# grade.section.subsection.item - four numbers, the first of which is the year.
_CODE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{1,2})\.(\d{1,2})$")


def _clamp_duration(value: Any) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DURATION
    return minutes if minutes in DURATIONS else DEFAULT_DURATION


def _text(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    return str(value or "").strip()[:limit]


def _system_prompt(spec: Dict[str, Any]) -> str:
    language = _language_name(str(spec.get("language") or "kk"))
    grade = spec.get("grade")
    duration = _clamp_duration(spec.get("duration"))
    section = _text(spec.get("section"), MAX_SECTION_CHARS)

    start = max(3, round(duration * _PHASE_SHARE["start"]))
    end = max(3, round(duration * _PHASE_SHARE["end"]))
    middle = duration - start - end

    return (
        "You write Қысқа мерзімді жоспар - the short-term lesson plan that "
        "schools in Kazakhstan require for every lesson.\n\n"
        f"SUBJECT: {spec.get('subject') or 'science'}\n"
        f"GRADE: {grade}\n"
        f"LESSON LENGTH: {duration} minutes\n"
        + (f"SECTION (бөлім): {section}\n" if section else
           "SECTION (бөлім): decide which section of the syllabus this topic "
           "belongs to and name it.\n")
        + "\n"
        "THE LESSON IS THE POINT. Plan what the class actually does, minute by "
        "minute, so another teacher could pick this up and teach from it. "
        "Every stage says what the TEACHER does and what the STUDENTS do - "
        "both, always. A stage where the students only listen is a stage that "
        "needs rewriting.\n\n"
        f"TIME: the stages must add up to {duration} minutes. Roughly "
        f"{start} at the start, {middle} in the middle, {end} at the end. Give "
        "each stage whole minutes.\n\n"
        f"OBJECTIVES: take them from the Kazakhstan curriculum for grade "
        f"{grade}. Each has a code written grade.section.subsection.item - the "
        f"FIRST number is the grade, so every code here begins with {grade}. "
        "If you are not certain of a code, leave it empty and write the "
        "objective anyway: a teacher can look a code up, and cannot take back "
        "a document that carried an invented one.\n\n"
        "SUCCESS CRITERIA: written from the student's side - 'can explain', "
        "'can calculate' - and checkable during the lesson.\n\n"
        "DIFFERENTIATION (саралау): name what is done for students who need "
        "more support AND for those who finish early. Not a sentence about "
        "differentiation - the actual thing you do.\n\n"
        f"LANGUAGE: write EVERY field in {language}, in natural, fluent "
        "wording. Keep formulas, symbols, units and variable names in standard "
        "notation; translate only the words.\n\n"
        "Return ONLY a JSON object, no markdown, no explanation:\n"
        "{\n"
        '  "section": "...",\n'
        '  "objectives": [{"code": "8.2.1.4", "text": "..."}],\n'
        '  "lesson_goal": "...",\n'
        '  "success_criteria": ["..."],\n'
        '  "values": "...",\n'
        '  "cross_curricular": "...",\n'
        '  "prior_knowledge": "...",\n'
        '  "stages": [\n'
        '    {"phase": "start", "title": "...", "minutes": 5,\n'
        '     "teacher": "...", "student": "...",\n'
        '     "assessment": "...", "resources": "..."}\n'
        "  ],\n"
        '  "differentiation": "...",\n'
        '  "assessment_plan": "...",\n'
        '  "health_safety": "..."\n'
        "}\n"
        'phase is one of "start", "middle", "end", in that order.\n'
    )


def _clean_objectives(raw: Any, grade: Any) -> Tuple[List[Dict[str, str]], int]:
    """Objectives, with codes that do not belong to this grade removed.

    Returns the objectives and how many codes were dropped - the second number
    is worth recording: a model that keeps inventing codes for the wrong year
    is a model whose objectives should be read with suspicion.
    """
    try:
        grade_number = int(grade)
    except (TypeError, ValueError):
        grade_number = 0

    objectives: List[Dict[str, str]] = []
    dropped = 0
    for item in (raw if isinstance(raw, list) else [])[:MAX_OBJECTIVES]:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = _text(item.get("text"), MAX_FIELD_CHARS)
        if not text:
            continue

        code = _text(item.get("code"), 20)
        match = _CODE_RE.match(code) if code else None
        if code and (not match or int(match.group(1)) != grade_number):
            # Keep the objective, drop the claim about where it comes from.
            dropped += 1
            code = ""
        objectives.append({"code": code, "text": text})
    return objectives, dropped


def _clean_stages(raw: Any) -> List[Dict[str, Any]]:
    """The lesson itself: stages in phase order, each with both columns."""
    stages: List[Dict[str, Any]] = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_STAGES]:
        if not isinstance(item, dict):
            continue
        teacher = _text(item.get("teacher"), MAX_STAGE_FIELD_CHARS)
        student = _text(item.get("student"), MAX_STAGE_FIELD_CHARS)
        # Both columns or none. A stage with an empty student column is the
        # thing this document exists to prevent.
        if not teacher or not student:
            continue
        phase = str(item.get("phase") or "").strip().lower()
        if phase not in PHASES:
            phase = "middle"
        try:
            minutes = int(item.get("minutes"))
        except (TypeError, ValueError):
            minutes = 0
        stages.append({
            "phase": phase,
            "title": _text(item.get("title"), 200),
            "minutes": max(0, min(120, minutes)),
            "teacher": teacher,
            "student": student,
            "assessment": _text(item.get("assessment"), MAX_STAGE_FIELD_CHARS),
            "resources": _text(item.get("resources"), MAX_STAGE_FIELD_CHARS),
        })

    # Phase order, keeping the model's order inside each phase: the form reads
    # top to bottom as the lesson runs.
    order = {phase: index for index, phase in enumerate(PHASES)}
    stages.sort(key=lambda s: order[s["phase"]])
    return stages


def _clean_list(raw: Any, limit: int) -> List[str]:
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for item in (raw if isinstance(raw, list) else [])[:limit]:
        text = _text(item, MAX_FIELD_CHARS)
        if text:
            out.append(text)
    return out


def _validate(payload: Any, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Turn whatever the model returned into a plan, or say why not.

    Shape checks, not judgement: a pedagogically weak stage is for the teacher
    to rewrite, and the interface lets them. What must not get through is a
    document that cannot be submitted - no stages, a lesson planned for the
    wrong length, objectives carrying codes from another year.
    """
    if not isinstance(payload, dict):
        return {"error": "model did not return an object"}

    duration = _clamp_duration(spec.get("duration"))
    stages = _clean_stages(payload.get("stages"))
    if len(stages) < MIN_STAGES:
        return {"error": "model returned too few usable stages"}

    planned = sum(stage["minutes"] for stage in stages)
    if not planned:
        return {"error": "model gave the stages no time"}
    if abs(planned - duration) > duration * DURATION_TOLERANCE:
        # Refused rather than rescaled. Stretching somebody's stages to fit is
        # a different lesson than the one that was written, and the teacher
        # would have no way to know it happened.
        return {
            "error": f"stages add up to {planned} minutes, not {duration}",
            "minutes_planned": planned,
        }

    objectives, dropped_codes = _clean_objectives(payload.get("objectives"),
                                                  spec.get("grade"))
    if not objectives:
        return {"error": "model returned no learning objectives"}

    return {
        "plan": {
            "section": _text(payload.get("section"), MAX_SECTION_CHARS),
            "objectives": objectives,
            "lesson_goal": _text(payload.get("lesson_goal")),
            "success_criteria": _clean_list(payload.get("success_criteria"),
                                            MAX_CRITERIA),
            "values": _text(payload.get("values")),
            "cross_curricular": _text(payload.get("cross_curricular")),
            "prior_knowledge": _text(payload.get("prior_knowledge")),
            "stages": stages,
            "differentiation": _text(payload.get("differentiation")),
            "assessment_plan": _text(payload.get("assessment_plan")),
            "health_safety": _text(payload.get("health_safety")),
        },
        "minutes_planned": planned,
        "dropped_codes": dropped_codes,
    }


async def generate_lesson_plan(spec: Dict[str, Any]) -> Dict[str, Any]:
    """One lesson plan, or {"error": ...}.

    Never raises: the caller is a socket handler, and a traceback there would
    take down the connection for every other request on it.
    """
    topic = _text(spec.get("topic"), MAX_TOPIC_CHARS)
    if not topic:
        telemetry.record(error_type="no_topic")
        return {"error": "topic is required"}

    duration = _clamp_duration(spec.get("duration"))
    telemetry.record(
        subject=_text(spec.get("subject"), 40),
        language=_text(spec.get("language"), 8),
        items_requested=duration,
    )

    try:
        response = await _llm_chat(
            [
                Message(role="system", content=_system_prompt(spec)),
                Message(
                    role="user",
                    content=(
                        USER_CONTENT_NOTICE
                        + "\n\nPlan the lesson on this topic:\n"
                        + _wrap("topic", topic)
                    ),
                ),
            ]
        )
    except Exception as exc:  # noqa: BLE001 - reported, never raised at a socket
        telemetry.record(error_type=type(exc).__name__)
        return {"error": f"{type(exc).__name__}"}

    result = _validate(_safe_json_loads(response.content), spec)

    if result.get("error"):
        telemetry.record(error_type=str(result["error"])[:60])
        content = response.content or ""
        print(
            f"[lesson_plan] unusable reply: {result['error']} | "
            f"finish_reason={getattr(response, 'finish_reason', None)!r} "
            f"content={len(content)} chars",
            flush=True,
        )
    else:
        # items_produced is the planned minutes, against items_requested which
        # is the lesson length: one subtraction in the log says whether the
        # time actually adds up, without a field of its own.
        telemetry.record(
            items_produced=result["minutes_planned"],
            status="complete",
        )
        if result["dropped_codes"]:
            print(
                f"[lesson_plan] dropped {result['dropped_codes']} objective "
                f"code(s) that did not belong to grade {spec.get('grade')}",
                flush=True,
            )
    return result
