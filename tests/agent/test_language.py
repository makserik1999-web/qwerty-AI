"""Which language a question is answered in.

This decides the educator text, every word on screen in the animation, and the
wording of a refusal. Getting it wrong is not a cosmetic slip - a Kazakh
student gets a Russian video and the product simply does not work for them.

Two failures lived here, both silent:

- Kazakh was detected only by its unique letters (ә ғ қ ң ө ұ ү һ і), so
  "фотосинтез деген не" - the ordinary way to ask "what is photosynthesis" -
  has no such letter and was answered in Russian.
- Latin text was not detected at all, and the fallback is Kazakh, so an
  English question came back in Kazakh.
"""

import pytest


@pytest.fixture(scope="session")
def detect(agent_import_path):
    from anyq.language import _detect_language

    return _detect_language


# ------------------------------------------------------------------ Kazakh --


@pytest.mark.parametrize(
    "question",
    [
        "ауырлық күші дегеніміз не",       # has ү, і
        "электр тогы қалай жұмыс істейді",  # has қ, ұ, і
    ],
)
def test_kazakh_with_its_own_letters(detect, question):
    assert detect(question) == "kk"


@pytest.mark.parametrize(
    "question",
    [
        "гравитация деген не",
        "фотосинтез деген не",
        "атом деген не",
        "молекула туралы",
        "бұл неге болады",
    ],
)
def test_kazakh_without_any_kazakh_specific_letter(detect, question):
    """The case that was broken: every letter is shared with Russian."""
    assert detect(question) == "kk"


# ----------------------------------------------------------------- Russian --


@pytest.mark.parametrize(
    "question",
    [
        "что такое гравитация",
        "почему небо голубое",
        "объясни фотосинтез",
        "как работает электрический ток",
    ],
)
def test_russian(detect, question):
    assert detect(question) == "ru"


@pytest.mark.parametrize(
    "question",
    [
        "почему у людей выпадают волосы",   # "осы" hides inside "волосы"
        "что такое колосья",
        "как измеряют покосы травы",
    ],
)
def test_a_kazakh_marker_hidden_inside_a_russian_word_is_ignored(detect, question):
    """Word boundaries, not substrings - otherwise hair questions turn Kazakh."""
    assert detect(question) == "ru"


# ----------------------------------------------------------------- English --


@pytest.mark.parametrize(
    "question",
    ["what is gravity", "explain photosynthesis", "how do plants grow"],
)
def test_english(detect, question):
    assert detect(question) == "en"


def test_a_stray_latin_word_does_not_override_cyrillic(detect):
    """Order matters: Cyrillic is decided before Latin is even considered."""
    assert detect("что такое DNA") == "ru"
    assert detect("фотосинтез деген не, photosynthesis") == "kk"


# ------------------------------------------------------------- no language --


@pytest.mark.parametrize("question", ["E = mc^2", "H2O", "2 + 2", "   "])
def test_text_without_words_has_no_language(detect, question):
    """A bare formula is not English; the caller falls back to the default."""
    assert detect(question) is None


# --------------------------------------------------------------- resolving --


def test_an_explicit_choice_wins_over_detection(agent_import_path):
    from anyq.language import _resolve_output_language

    state = {"user_message": "что такое гравитация", "output_language": "kk"}
    assert _resolve_output_language(state) == "kk"


def test_detection_is_used_when_nothing_was_chosen(agent_import_path):
    from anyq.language import _resolve_output_language

    assert _resolve_output_language({"user_message": "фотосинтез деген не"}) == "kk"
    assert _resolve_output_language({"user_message": "what is gravity"}) == "en"
    assert _resolve_output_language({"user_message": "что такое атом"}) == "ru"
