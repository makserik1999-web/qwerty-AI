"""Output language, fonts and the user-facing message dictionaries.

Moved here from science_manim_graph_agent.py (language, fonts, reject and
render-fallback messages) and agent_ws_client.py (generic failure message).
"""

import re
from typing import Optional

from anyq.config import DEFAULT_OUTPUT_LANGUAGE, MANIM_TEXT_FONT

# ============== Output language ==============
_LANGUAGE_NAMES = {
    "kk": "Kazakh (қазақ тілі)",
    "ru": "Russian (русский язык)",
    "en": "English",
}

# Letters unique to Kazakh Cyrillic - the cheapest signal when present.
_KAZAKH_ONLY_CHARS = set("әғқңөұүһі")

# Kazakh words that carry NO Kazakh-specific letter, so the character test
# above misses them entirely. This matters more than it sounds: "X деген не?"
# is the ordinary way to ask "what is X" in Kazakh, and for a topic like
# "фотосинтез деген не" every letter is shared with Russian - so the question
# was answered in Russian.
#
# Every word here is Kazakh and not a Russian word, which is what keeps the
# test from firing on Russian input.
#
# Anchored on word boundaries, which is not cosmetic: without them "осы"
# matches inside the Russian "волосы", and every question about hair
# would be answered in Kazakh.
_KAZAKH_MARKERS = re.compile(
    r"\b(деген|дегенде|дегендер|немесе|болып|болады|болса|болу|керек|неге"
    r"|туралы|осы|емес|сияқты|қалай|нешеу)\b",
    re.IGNORECASE | re.UNICODE,
)

_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
# Three letters, not one: "E = mc^2" is a formula, not an English question,
# and a single stray Latin character should not decide the answer language.
_LATIN_WORD = re.compile(r"[A-Za-z]{3,}")


def _detect_language(text: str) -> Optional[str]:
    """Which of the three languages this text is written in, if any.

    Order matters: Kazakh is checked before Russian because the two share an
    alphabet and Kazakh is the narrower case, and Latin is checked last so a
    stray English word inside a Cyrillic question does not flip the answer.

    Returns None only when there are no letters at all - a bare formula, say -
    and the caller then falls back to the configured default.
    """
    low = (text or "").lower()
    if any(ch in _KAZAKH_ONLY_CHARS for ch in low):
        return "kk"
    if _KAZAKH_MARKERS.search(low):
        return "kk"
    if _CYRILLIC.search(low):
        return "ru"
    if _LATIN_WORD.search(low):
        # Previously fell through to None, and the default is Kazakh - so an
        # English question came back in Kazakh.
        return "en"
    return None


def _resolve_output_language(state: "ScienceVideoState") -> str:
    """Explicit choice > language of the question > configured default."""
    explicit = str(state.get("output_language") or "").strip().lower()
    if explicit in _LANGUAGE_NAMES:
        return explicit
    detected = _detect_language(str(state.get("user_message") or ""))
    if detected:
        return detected
    return DEFAULT_OUTPUT_LANGUAGE if DEFAULT_OUTPUT_LANGUAGE in _LANGUAGE_NAMES else "kk"


def _language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code, _LANGUAGE_NAMES["kk"])


# ============== Fonts ==============
# Manim's default font does not reliably cover Kazakh Cyrillic (ә ғ қ ң ө ұ ү һ і),
# which renders as missing-glyph boxes. Pick a font that does.
_FONT_PREFERENCES = (
    "Arial Unicode MS",
    "Noto Sans",
    "DejaVu Sans",
    "PT Sans",
    "Helvetica",
    "Arial",
    "Verdana",
)

_cached_font: Optional[str] = None


def _pick_unicode_font() -> str:
    global _cached_font
    if _cached_font:
        return _cached_font

    override = MANIM_TEXT_FONT
    if override:
        _cached_font = override
        return _cached_font

    available = set()
    try:
        import manimpango

        available = set(manimpango.list_fonts())
    except Exception:
        pass

    for font in _FONT_PREFERENCES:
        if font in available:
            _cached_font = font
            return _cached_font

    _cached_font = "DejaVu Sans"
    return _cached_font


# ============== Messages ==============
_REJECT_MESSAGES = {
    "kk": (
        "Мен тек ғылыми тақырыптар бойынша оқу бейнелерін жасай аламын "
        "(математика, физика, химия, биология, информатика, инженерия, статистика).\n\n"
        "Сұрауыңызды ғылыми ұғым ретінде қайта тұжырымдаңыз."
    ),
    "ru": (
        "Я могу создавать обучающие видео только по научным темам "
        "(математика, физика, химия, биология, информатика, инженерия, статистика).\n\n"
        "Пожалуйста, переформулируйте запрос как научное понятие."
    ),
    "en": (
        "I can help create educational videos only for scientific topics "
        "(math, physics, chemistry, biology, CS, engineering, statistics).\n\n"
        "Please rephrase your request as a scientific concept."
    ),
}


# Shown when rendering fails even after repair - the user must never see a
# traceback.
_RENDER_FALLBACK_MESSAGES = {
    "kk": (
        "😔 Кешіріңіз, бұл тақырып бойынша анимацияны әзірге жасай алмадым. "
        "Басқа тақырыпты байқап көріңізші."
    ),
    "ru": (
        "😔 Модель пока не поддерживает эту тему для анимации. "
        "Попробуйте, пожалуйста, другую тему."
    ),
    "en": (
        "😔 Sorry, I couldn't animate this topic yet. Please try another one."
    ),
}


# Shown if the pipeline fails for a reason other than rendering (network,
# quota, upstream outage). The real error goes to the log, never to the user.
_GENERIC_FAILURE_MESSAGES = {
    "kk": (
        "Сәтсіз болды :( Жауапты дәл қазір дайындай алмадым. "
        "Сәл кейінірек қайта байқап көріңізші."
    ),
    "ru": (
        "Не получилось :( Сейчас не удалось подготовить ответ. "
        "Попробуйте, пожалуйста, ещё раз чуть позже."
    ),
    "en": (
        "Sorry, I could not prepare an answer right now. "
        "Please try again in a moment."
    ),
}


def _friendly_failure_text(user_text: str) -> str:
    try:
        lang = _detect_language(user_text) or DEFAULT_OUTPUT_LANGUAGE
    except Exception:
        lang = "kk"
    return _GENERIC_FAILURE_MESSAGES.get(lang, _GENERIC_FAILURE_MESSAGES["kk"])
