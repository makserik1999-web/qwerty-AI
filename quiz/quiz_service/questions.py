"""What a question is, what makes one playable, and how an answer is marked.

Two kinds, the two the classroom actually uses:

  choice - two to four options, one of them right. Each wrong option may carry
           a `note`: why a student would pick it. That note is what turns a
           result into something a teacher can act on - "most of the class
           chose 20 m/s², they multiplied instead of dividing" - and it is
           never sent to a student.
  short  - a typed answer, checked against the answer and its accepted
           variants. Numbers are compared as numbers, so "0,5", "0.5" and
           "0.50" are one answer, and a unit typed after the number is
           allowed when it is the question's unit.

SAVING IS NOT JUDGING. The editor saves as the teacher types, and a question
halfway through being written - an empty option, no right answer marked yet -
has to survive a save. So `clean_question` only fixes the shape, and
`problems` says separately what would stop the question being played. A
session refuses to open while any question has one.
"""

import random
import re
import secrets
import unicodedata
from typing import Any, Dict, List, Optional

TYPES = ("choice", "short")

MAX_TEXT = 600
MAX_OPTION = 200
MAX_NOTE = 300
MAX_EXPLANATION = 600
MAX_TOPIC = 80
MAX_ANSWER = 60
MAX_UNIT = 16
MAX_ACCEPT = 8
MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_TITLE = 120

_ID_RE = re.compile(r"^[qo]-[0-9a-f]{6,16}$")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "timeLimitMin": 15,
    "shuffleQuestions": True,
    # Different letters on neighbouring phones, so "it's B" stops working.
    "shuffleOptions": True,
    "showResults": True,
    "leaderboard": True,
    "lateJoin": True,
}


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(5)}"


def _text(value: Any, limit: int) -> str:
    """A string, cut to size. Not stripped: the editor saves mid-sentence."""
    return value[:limit] if isinstance(value, str) else ""


def _own_id(value: Any, prefix: str, taken: set) -> str:
    if isinstance(value, str) and _ID_RE.fullmatch(value) and value[0] == prefix \
            and value not in taken:
        return value
    return new_id(prefix)


def clean_question(raw: Any, taken_ids: Optional[set] = None) -> Optional[Dict[str, Any]]:
    """A question in the stored shape, or None if it is not one at all.

    Ids the client sent are kept when they are well formed and unique - the
    editor finds the card being edited by them - and replaced otherwise, so a
    pasted duplicate cannot make two questions answer to one id.
    """
    if not isinstance(raw, dict):
        return None
    taken = taken_ids if taken_ids is not None else set()

    kind = raw.get("type") if raw.get("type") in TYPES else "choice"
    question: Dict[str, Any] = {
        "id": _own_id(raw.get("id"), "q", taken),
        "type": kind,
        "text": _text(raw.get("text"), MAX_TEXT),
        "explanation": _text(raw.get("explanation"), MAX_EXPLANATION),
        "topic": _text(raw.get("topic"), MAX_TOPIC),
    }
    taken.add(question["id"])

    if kind == "choice":
        options: List[Dict[str, str]] = []
        option_ids: set = set()
        raw_options = raw.get("options") if isinstance(raw.get("options"), list) else []
        for item in raw_options[:MAX_OPTIONS]:
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict):
                continue
            option = {
                "id": _own_id(item.get("id"), "o", option_ids),
                "text": _text(item.get("text"), MAX_OPTION),
                "note": _text(item.get("note"), MAX_NOTE),
            }
            option_ids.add(option["id"])
            options.append(option)
        question["options"] = options

        correct = raw.get("correct")
        # The generator names the right option by position, the editor by id.
        if isinstance(correct, int) and not isinstance(correct, bool) \
                and 0 <= correct < len(options):
            correct = options[correct]["id"]
        question["correct"] = correct if correct in option_ids else ""
    else:
        question["answer"] = _text(raw.get("answer"), MAX_ANSWER)
        question["unit"] = _text(raw.get("unit"), MAX_UNIT)
        accept = raw.get("accept")
        if isinstance(accept, str):
            accept = re.split(r"[·|;\n]", accept)
        variants: List[str] = []
        for item in accept if isinstance(accept, list) else []:
            text = _text(item, MAX_ANSWER).strip()
            if text and text not in variants:
                variants.append(text)
        question["accept"] = variants[:MAX_ACCEPT]

    return question


def clean_questions(raw: Any, limit: int) -> List[Dict[str, Any]]:
    taken: set = set()
    out = []
    for item in raw if isinstance(raw, list) else []:
        question = clean_question(item, taken)
        if question is not None:
            out.append(question)
        if len(out) >= limit:
            break
    return out


def problems(question: Dict[str, Any]) -> List[str]:
    """What stops this question being played, as stable codes.

    Codes rather than sentences: the editor shows them in the teacher's
    language, which this service does not know.
    """
    found: List[str] = []
    if not question.get("text", "").strip():
        found.append("no_text")
    if question.get("type") == "choice":
        options = question.get("options") or []
        filled = [o for o in options if o.get("text", "").strip()]
        if len(options) < MIN_OPTIONS:
            found.append("few_options")
        elif len(filled) < len(options):
            found.append("empty_option")
        if not question.get("correct"):
            found.append("no_correct")
        texts = [_norm(o["text"]) for o in filled]
        if len(set(texts)) < len(texts):
            found.append("duplicate_options")
    elif not question.get("answer", "").strip():
        found.append("no_answer")
    return found


def clean_settings(raw: Any, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from quiz_service.config import TIME_LIMITS

    settings = dict(base or DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return settings
    limit = raw.get("timeLimitMin")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit in TIME_LIMITS:
        settings["timeLimitMin"] = limit
    for key in ("shuffleQuestions", "shuffleOptions", "showResults",
                "leaderboard", "lateJoin"):
        if isinstance(raw.get(key), bool):
            settings[key] = raw[key]
    return settings


def clean_title(value: Any) -> str:
    title = value.strip()[:MAX_TITLE] if isinstance(value, str) else ""
    return title or "Квиз"


# ----------------------------------------------------------------- marking --

_DIGIT_GROUP = re.compile(r"(?<=\d)[\s  ](?=\d{3}(?!\d))")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def _norm(value: str) -> str:
    """The form two answers are compared in.

    NFKC first, which is what makes "м/с²" and "м/с2" the same string; then
    case, the minus signs people actually type, decimal commas, and the space
    some write inside a thousand.
    """
    text = unicodedata.normalize("NFKC", value or "").strip().lower()
    text = text.replace("−", "-").replace("–", "-")
    text = _DIGIT_GROUP.sub("", text)
    text = _DECIMAL_COMMA.sub(".", text)
    text = re.sub(r"\s+", " ", text)
    return text.rstrip(".!")


def _number(text: str) -> Optional[float]:
    try:
        return float(text.replace(" ", ""))
    except ValueError:
        return None


def _without_unit(text: str, unit: str) -> str:
    if unit and text.endswith(unit):
        return text[: -len(unit)].strip()
    return text


def is_correct_short(value: str, question: Dict[str, Any]) -> bool:
    given = _norm(value)
    if not given:
        return False
    unit = _norm(question.get("unit", ""))
    accepted = [_norm(a) for a in [question.get("answer", ""), *question.get("accept", [])]]
    accepted = [a for a in accepted if a]
    if given in accepted:
        return True

    bare = _without_unit(given, unit)
    if bare in accepted or bare in [_without_unit(a, unit) for a in accepted]:
        return True

    number = _number(bare)
    if number is None:
        return False
    for candidate in accepted:
        expected = _number(_without_unit(candidate, unit))
        if expected is not None and abs(number - expected) <= 1e-9 * max(1.0, abs(expected)):
            return True
    return False


def mark(question: Dict[str, Any], option_id: Optional[str], text: Optional[str]) -> bool:
    if question.get("type") == "choice":
        return bool(option_id) and option_id == question.get("correct")
    return is_correct_short(text or "", question)


# ------------------------------------------------------------------- views --


def option_order(question: Dict[str, Any], shuffle: bool) -> List[str]:
    ids = [o["id"] for o in question.get("options") or []]
    if shuffle:
        random.SystemRandom().shuffle(ids)
    return ids


def student_view(question: Dict[str, Any], order: Optional[List[str]],
                 index: int, total: int) -> Dict[str, Any]:
    """The question as a student's phone receives it: never with the answer."""
    view: Dict[str, Any] = {
        "id": question["id"],
        "type": question["type"],
        "text": question["text"],
        "index": index,
        "total": total,
    }
    if question["type"] == "choice":
        by_id = {o["id"]: o for o in question.get("options") or []}
        ids = [i for i in (order or []) if i in by_id] or list(by_id)
        view["options"] = [{"id": i, "text": by_id[i]["text"]} for i in ids]
    else:
        view["unit"] = question.get("unit", "")
    return view


def reveal(question: Dict[str, Any]) -> Dict[str, Any]:
    """What a student may see once they have answered."""
    out: Dict[str, Any] = {"explanation": question.get("explanation", "")}
    if question["type"] == "choice":
        out["correctOptionId"] = question.get("correct", "")
    else:
        unit = question.get("unit", "")
        out["answer"] = f"{question.get('answer', '')} {unit}".strip()
    return out
