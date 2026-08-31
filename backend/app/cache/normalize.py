"""Turning a typed question into a stable cache key.

The normaliser is deliberately CONSERVATIVE. This is the exact-match layer, so
a false hit means a user is handed an answer to a different question - much
worse than a miss, which only costs what the system already costs today.
So it removes noise (case, spacing, punctuation, emoji, politeness) and
nothing that carries meaning: interrogatives like "почему" / "как" / "what is"
are kept, because "почему небо голубое" and "что такое небо" are not the same
question. Recall across phrasings is the semantic layer's job, not this one.
"""

import hashlib
import re
import unicodedata

# Polite framing and imperatives that add no subject matter. Ordered longest
# first so "расскажи мне про" is consumed before "расскажи".
_LEAD_INS = (
    # Russian
    "расскажи мне про", "расскажи мне о", "расскажи про", "расскажи о",
    "расскажите про", "расскажите о", "объясни мне", "объясните мне",
    "объясни", "объясните", "расскажи", "расскажите", "покажи мне",
    "покажите мне", "покажи", "покажите", "пожалуйста",
    # Kazakh
    "маған түсіндіріп бер", "түсіндіріп бер", "түсіндіріңізші",
    "түсіндіріңіз", "түсіндір", "көрсет",
    # English
    "can you explain", "could you explain", "please explain",
    "tell me about", "tell me", "show me", "explain to me", "explain",
    "please",
)

_TRAILING_POLITENESS = ("пожалуйста", "please", "өтінемін")

# Keep letters, digits, whitespace and the few symbols that carry meaning in a
# science question (formulas, units, ranges).
_KEEP = re.compile(r"[^\w\s+\-*/=^<>%°]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_question(text: str) -> str:
    """Collapse a question to its comparable form.

    Returns "" for input that carries nothing to match on, which the caller
    treats as "not cacheable".
    """
    if not text:
        return ""

    # NFKC folds full-width and compatibility forms onto their plain
    # equivalents, so "ｇｒａｖｉｔｙ" and "gravity" agree.
    result = unicodedata.normalize("NFKC", text).lower().strip()
    result = _KEEP.sub(" ", result)
    result = _WHITESPACE.sub(" ", result).strip()

    # Strip lead-ins repeatedly: "пожалуйста объясни гравитацию" has two.
    changed = True
    while changed:
        changed = False
        for lead in _LEAD_INS:
            if result.startswith(lead + " "):
                result = result[len(lead) + 1:].strip()
                changed = True
                break
            if result == lead:
                return ""

    for tail in _TRAILING_POLITENESS:
        if result.endswith(" " + tail):
            result = result[: -(len(tail) + 1)].strip()

    return result


def cache_key(normalized: str, pipeline_version: str) -> str:
    """The lookup id for a normalised question under a given pipeline.

    The output language is NOT part of the key on purpose: the agent derives
    it from the question text itself, so it is already a function of what is
    hashed here. Should an explicit language selector ever reach the backend,
    it must be added to this key - otherwise a Kazakh answer would be served
    to someone who asked for English.
    """
    return hashlib.sha256(f"{normalized}|{pipeline_version}".encode()).hexdigest()
