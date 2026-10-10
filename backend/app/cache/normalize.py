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


def cache_key(normalized: str, pipeline_version: str, variant: str = "") -> str:
    """The lookup id for a normalised question under a given pipeline.

    The output language is NOT part of the key on purpose: the agent derives
    it from the question text itself, so it is already a function of what is
    hashed here.

    `variant` is for everything the request chooses that the question text
    cannot imply. Narration is the first: the same question asked with the
    voice on and with it off produces two different videos, and without this
    the second asker would be handed the first one's - silent when they wanted
    sound, or spoken by a voice they did not pick. The docstring used to warn
    about exactly this for an explicit language selector; the warning stands
    for anything else added later.

    Callers must pass a value from a closed set. A variant taken straight from
    a client would let anyone mint unlimited distinct keys, which is a cache
    that never hits and a collection that never stops growing.
    """
    material = f"{normalized}|{pipeline_version}"
    if variant:
        material = f"{material}|{variant}"
    return hashlib.sha256(material.encode()).hexdigest()
