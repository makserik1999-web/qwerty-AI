"""Quiz questions: the kind a class answers on its phones in ten minutes.

Text, not video, so like assessments and lesson plans this skips the graph and
lives in the agent only because the API keys are here. The quiz service never
talks to a model; the editor asks the backend for a draft, the backend asks
this, and the teacher saves what comes back.

WHAT MAKES A QUIZ QUESTION WORTH ASKING is its wrong answers. A distractor
nobody would pick teaches the teacher nothing; one that a student who
multiplied instead of divided WILL pick tells them exactly what to re-teach.
So every wrong option comes with a `note` naming the misunderstanding behind
it, written for the teacher. Results group answers by option, and when a
third of the class lands on the same wrong one, that note is what the teacher
reads.

CHECKED MECHANICALLY, because these are the ways a model gets it wrong:

  - Exactly one right option, and four distinct options. Two options that
    differ only in case or spacing are one option offered twice.
  - No "all of the above" / "none of the above". On a phone with shuffled
    options, "all of the above" is not even above anything.
  - The right answer is not always first. Models put it first; options are
    shuffled here - or sorted, when they are all numbers, because a column of
    numbers reads in order and a shuffled one only adds noise.
  - A typed answer is short enough to be typed, and its unit is kept apart
    from it so "600" and "600 Н" are the same answer.
"""

from __future__ import annotations

import math
import random
import re
from typing import Any, Dict, List, Optional

from spoon_ai.schema import Message

from anyq import telemetry
from anyq.language import _language_name
from anyq.llm_client import _llm_chat
from anyq.nodes import USER_CONTENT_NOTICE, _wrap
from anyq.script_guard import _safe_json_loads

MIN_COUNT = 1
MAX_COUNT = 20
DEFAULT_COUNT = 8
MAX_TOPIC_CHARS = 200
MAX_TEXT = 400
MAX_OPTION = 120
MAX_NOTE = 200
MAX_EXPLANATION = 400
MAX_ANSWER = 40
MAX_UNIT = 12
MAX_ACCEPT = 6
MAX_AVOID = 40

MIXES = ("choice", "mixed", "short")
DIFFICULTIES = ("easy", "medium", "hard")

_DIFFICULTY_TEXT = {
    "easy": "recall and one-step application - a student who did the reading gets these",
    "medium": "mostly application, a few that need a second step of reasoning",
    "hard": "multi-step reasoning and application to unfamiliar situations",
}

# Options that are not an answer to anything once the order is shuffled.
_BANNED_OPTION = re.compile(
    r"(all of the above|none of the above|both a and b|"
    r"барлығы дұрыс|барлық жауап дұрыс|дұрыс жауап жоқ|жоғарыдағылардың бәрі|"
    r"все ответы верны|все перечисленное|все вышеперечисленн|нет правильного|"
    r"ни один из)",
    re.IGNORECASE,
)
# A number, optionally followed by a unit and nothing else: "0,2 м/с²", "600 Н",
# "-3". Superscripts are not \d, so "м/с²" counts as a unit.
_NUMBER = re.compile(r"^\s*([-−]?\d+(?:[.,]\d+)?)\s*(?:[^\d\s][^\d]{0,11})?\s*$")


def _text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _key(value: str) -> str:
    return re.sub(r"[\s.,;:!?]+", " ", value.casefold()).strip()


def _clamp_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return DEFAULT_COUNT
    return max(MIN_COUNT, min(MAX_COUNT, count))


def _mix(value: Any) -> str:
    return value if value in MIXES else "mixed"


def _difficulty(value: Any) -> str:
    return value if value in DIFFICULTIES else "medium"


def _split(count: int, mix: str) -> Dict[str, int]:
    """How many of each kind. Mixed is mostly choice: typed answers are slower
    to take and fussier to mark, so they are the seasoning, not the meal."""
    if mix == "choice":
        return {"choice": count, "short": 0}
    if mix == "short":
        return {"choice": 0, "short": count}
    short = max(1, round(count * 0.25)) if count >= 3 else 0
    return {"choice": count - short, "short": short}


def _system_prompt(spec: Dict[str, Any]) -> str:
    language = _language_name(str(spec.get("language") or "kk"))
    count = _clamp_count(spec.get("count"))
    split = _split(count, _mix(spec.get("mix")))
    difficulty = _difficulty(spec.get("difficulty"))

    return (
        "You write quiz questions for a classroom in Kazakhstan. Students "
        "answer on their phones, one question at a time, about a minute each.\n\n"
        f"SUBJECT: {spec.get('subject') or 'science'}\n"
        f"GRADE: {spec.get('grade') or 'any'}\n"
        f"WRITE: {split['choice']} multiple-choice and {split['short']} "
        f"short-answer questions, {count} in total.\n"
        f"LEVEL: {_DIFFICULTY_TEXT[difficulty]}.\n\n"
        "MULTIPLE CHOICE: exactly four options, exactly one right. The three "
        "wrong ones are the heart of the question: each must be an answer a "
        "real student WOULD give, produced by one specific, common "
        "misunderstanding - multiplying instead of dividing, confusing mass "
        "with weight, dropping a sign. For every wrong option write a note, "
        "for the teacher, naming that misunderstanding in a few words. The "
        "right option's note is empty.\n"
        "Options are short (a number, a word or a phrase), grammatically "
        "parallel, and the right one is not the longest. Never 'all of the "
        "above', 'none of the above' or anything that refers to other "
        "options - their order is shuffled.\n\n"
        "SHORT ANSWER: the answer is a number or one to three words, so it "
        "can be typed on a phone. Put the unit in `unit`, not in `answer`. "
        "List other correct ways to write it in `accept` - another unit, a "
        "decimal comma, a synonym.\n\n"
        "EVERY QUESTION: stands on its own; tests understanding, not the "
        "wording of a textbook; has a one-sentence `explanation` of why the "
        "answer is right, shown to the student after they answer; and a "
        "`topic` of two or three words.\n\n"
        "NOTATION: units and formulas in plain Unicode - м/с², H₂O, √2, "
        "10⁵ Па, F = m·a. Use $...$ LaTeX only for a formula that cannot be "
        "written that way.\n\n"
        f"LANGUAGE: write every question, option, note and explanation in "
        f"{language}, natural and fluent. Keep symbols, units and variable "
        "names in standard notation.\n\n"
        "Return ONLY a JSON object, no markdown:\n"
        "{\n"
        '  "questions": [\n'
        '    {"type": "choice", "text": "...", "options": ["...", "...", "...", "..."],\n'
        '     "correct": 0, "notes": ["", "...", "...", "..."],\n'
        '     "explanation": "...", "topic": "..."},\n'
        '    {"type": "short", "text": "...", "answer": "600", "unit": "Н",\n'
        '     "accept": ["0,6 кН"], "explanation": "...", "topic": "..."}\n'
        "  ]\n"
        "}\n"
        "`correct` is the index of the right option in `options`.\n"
    )


def _numeric(text: str) -> Optional[float]:
    match = _NUMBER.match(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ".").replace("−", "-"))
    except ValueError:
        return None


def _arrange(options: List[str], notes: List[str], correct: int,
             rng: random.Random) -> Dict[str, Any]:
    """Shuffle, or sort numbers, keeping the right answer and notes attached."""
    items = [(text, note, i == correct)
             for i, (text, note) in enumerate(zip(options, notes, strict=True))]
    numbers = [_numeric(text) for text, _, _ in items]
    if all(n is not None for n in numbers):
        items = [item for _, item in sorted(zip(numbers, items, strict=True),
                                            key=lambda pair: pair[0])]
    else:
        rng.shuffle(items)
    return {
        "options": [{"text": text, "note": "" if right else note} for text, note, right in items],
        "correct": next(i for i, (_, _, right) in enumerate(items) if right),
    }


def _clean_choice(raw: Dict[str, Any], rng: random.Random) -> Optional[Dict[str, Any]]:
    options_raw = raw.get("options")
    if not isinstance(options_raw, list):
        return None
    options = [_text(o, MAX_OPTION) for o in options_raw[:4]]
    if len(options) != 4 or not all(options):
        return None
    if len({_key(o) for o in options}) != 4:
        return None
    if any(_BANNED_OPTION.search(o) for o in options):
        return None
    correct = raw.get("correct")
    if isinstance(correct, bool) or not isinstance(correct, int) or not 0 <= correct < 4:
        return None
    notes_raw = raw.get("notes") if isinstance(raw.get("notes"), list) else []
    notes = [_text(n, MAX_NOTE) for n in (notes_raw + [""] * 4)[:4]]
    return {"type": "choice", **_arrange(options, notes, correct, rng)}


def _clean_short(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    answer = _text(raw.get("answer"), MAX_ANSWER)
    if not answer or len(answer.split()) > 4:
        return None
    unit = _text(raw.get("unit"), MAX_UNIT)
    accept: List[str] = []
    for item in raw.get("accept") if isinstance(raw.get("accept"), list) else []:
        text = _text(item, MAX_ANSWER)
        if text and _key(text) != _key(answer) and text not in accept:
            accept.append(text)
    return {"type": "short", "answer": answer, "unit": unit, "accept": accept[:MAX_ACCEPT]}


def _validate(payload: Any, spec: Dict[str, Any],
              rng: Optional[random.Random] = None) -> Dict[str, Any]:
    """Whatever the model returned, as questions - or why there are none."""
    rng = rng or random.Random()
    if not isinstance(payload, dict) or not isinstance(payload.get("questions"), list):
        return {"error": "model did not return a list of questions"}

    count = _clamp_count(spec.get("count"))
    mix = _mix(spec.get("mix"))
    seen = {_key(_text(a, MAX_TEXT)) for a in (spec.get("avoid") or [])[:MAX_AVOID]
            if isinstance(a, str)}

    questions: List[Dict[str, Any]] = []
    dropped = 0
    for raw in payload["questions"]:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        text = _text(raw.get("text"), MAX_TEXT)
        kind = raw.get("type")
        if not text or _key(text) in seen or kind not in ("choice", "short") \
                or (mix == "choice" and kind == "short") \
                or (mix == "short" and kind == "choice"):
            dropped += 1
            continue
        body = _clean_choice(raw, rng) if kind == "choice" else _clean_short(raw)
        if body is None:
            dropped += 1
            continue
        seen.add(_key(text))
        questions.append({
            "text": text,
            **body,
            "explanation": _text(raw.get("explanation"), MAX_EXPLANATION),
            "topic": _text(raw.get("topic"), 60),
        })
        if len(questions) >= count:
            break

    # A short quiz is still a quiz; a quarter of one is a model that did not
    # follow the format, and a teacher should be told rather than handed it.
    needed = max(1, math.ceil(count * 0.6))
    if len(questions) < needed:
        return {"error": f"only {len(questions)} usable questions of {count}",
                "dropped": dropped}
    return {"questions": questions, "requested": count, "dropped": dropped}


async def generate_quiz(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Quiz questions, or {"error": ...}. Never raises - see lesson_plans."""
    topic = _text(spec.get("topic"), MAX_TOPIC_CHARS)
    if not topic:
        telemetry.record(error_type="no_topic")
        return {"error": "topic is required"}

    count = _clamp_count(spec.get("count"))
    telemetry.record(
        subject=_text(spec.get("subject"), 40),
        language=_text(spec.get("language"), 8),
        items_requested=count,
    )

    avoid = [a for a in (spec.get("avoid") or [])[:MAX_AVOID] if isinstance(a, str)]
    user = USER_CONTENT_NOTICE + "\n\nWrite the quiz on this topic:\n" + _wrap("topic", topic)
    if avoid:
        # The questions already in the quiz, so "add more" adds different ones.
        user += "\n\nDo not repeat or rephrase these, already in the quiz:\n" + _wrap(
            "existing_questions", "\n".join(f"- {_text(a, MAX_TEXT)}" for a in avoid)
        )

    try:
        response = await _llm_chat([
            Message(role="system", content=_system_prompt(spec)),
            Message(role="user", content=user),
        ])
    except Exception as exc:  # noqa: BLE001 - reported, never raised at a socket
        telemetry.record(error_type=type(exc).__name__)
        return {"error": f"{type(exc).__name__}"}

    result = _validate(_safe_json_loads(response.content), spec)
    if result.get("error"):
        telemetry.record(error_type=str(result["error"])[:60])
        content = response.content or ""
        print(
            f"[quiz] unusable reply: {result['error']} | "
            f"finish_reason={getattr(response, 'finish_reason', None)!r} "
            f"content={len(content)} chars",
            flush=True,
        )
    else:
        telemetry.record(items_produced=len(result["questions"]), status="complete")
        if result["dropped"]:
            print(f"[quiz] dropped {result['dropped']} question(s) that failed the checks",
                  flush=True)
    return result
