"""Normalisation decides what counts as "the same question".

Over-normalising is the dangerous direction: it hands one question's answer to
a different question. These tests pin both what must collide and what must not.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest
from app.cache.normalize import cache_key, normalize_question


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Explain gravity", "gravity"),
        ("explain    gravity", "gravity"),
        ("  Explain gravity!!!  ", "gravity"),
        ("EXPLAIN GRAVITY", "gravity"),
        ("Please explain gravity", "gravity"),
        ("Tell me about gravity", "gravity"),
        ("Объясни гравитацию", "гравитацию"),
        ("ПОЖАЛУЙСТА объясни гравитацию", "гравитацию"),
        ("Расскажи мне про гравитацию", "гравитацию"),
        ("Түсіндір гравитация", "гравитация"),
        ("gravity 🚀", "gravity"),
    ],
)
def test_noise_is_removed(raw, expected):
    assert normalize_question(raw) == expected


def test_phrasings_of_the_same_request_collide():
    forms = ["Explain gravity", "explain  GRAVITY", "Please explain gravity!", "Tell me about gravity"]
    assert len({normalize_question(f) for f in forms}) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # Interrogatives carry meaning and must NOT be normalised away.
        ("что такое сила", "почему сила"),
        ("what is gravity", "how does gravity work"),
        ("как работает двигатель", "что такое двигатель"),
        # Different subjects, obviously.
        ("explain gravity", "explain entropy"),
    ],
)
def test_different_questions_stay_different(first, second):
    assert normalize_question(first) != normalize_question(second)


def test_formula_characters_survive():
    # Losing these would merge genuinely different problems.
    assert normalize_question("solve x^2 + 3x - 4 = 0") == "solve x^2 + 3x - 4 = 0"
    assert "%" in normalize_question("what is 15% of 80")
    assert "°" in normalize_question("convert 90° to radians")


def test_empty_and_pure_politeness_are_not_cacheable():
    assert normalize_question("") == ""
    assert normalize_question("   ") == ""
    assert normalize_question("please") == ""
    assert normalize_question("объясни") == ""


def test_key_changes_with_the_pipeline_version():
    a = cache_key("gravity", "v1")
    b = cache_key("gravity", "v2")
    assert a != b, "a prompt/model change must invalidate old entries"
    assert a == cache_key("gravity", "v1"), "the key must be stable"
    assert len(a) == 64
