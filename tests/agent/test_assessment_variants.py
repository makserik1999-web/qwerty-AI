"""1-нұсқа and 2-нұсқа: one generation, two papers marked on one scale.

The model is asked for both variants in one reply. What comes back is held to
the first variant's shape - no more questions, each for the marks of its twin
- because two variants with different totals cannot be marked side by side.
A second variant that came back broken is dropped, not an error: the first is
a whole paper on its own.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "agent", REPO_ROOT / "tests" / "stubs"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from anyq import assessments as a  # noqa: E402

SPEC = {"subject": "physics", "grade": 8, "topic": "Ньютон заңдары",
        "type": "sor", "difficulty": "medium", "language": "kk", "count": 2}


def _q(text, marks):
    return {"text": text, "marks": marks}


def test_the_prompt_asks_for_both_variants_only_when_told():
    assert "1-нұсқа" in a._system_prompt({**SPEC, "variants": 2})
    assert '"variants"' in a._system_prompt({**SPEC, "variants": 2})
    assert "1-нұсқа" not in a._system_prompt(SPEC)
    assert '"variants"' not in a._system_prompt(SPEC)


def test_two_variants_come_back_parallel():
    payload = {"variants": [
        {"questions": [_q("A1", 2), _q("A2", 3)]},
        # The model drifted: different marks and one question too many.
        {"questions": [_q("B1", 4), _q("B2", 1), _q("B3", 5)]},
    ]}

    result = a._validate_paper(payload, 2, two=True)

    assert [q["text"] for q in result["questions"]] == ["A1", "A2"]
    assert result["variant2"] == [_q("B1", 2), _q("B2", 3)]


def test_a_broken_second_variant_leaves_the_first():
    payload = {"variants": [{"questions": [_q("A1", 2)]}, {"questions": []}]}
    result = a._validate_paper(payload, 1, two=True)
    assert result["questions"] == [_q("A1", 2)] and "variant2" not in result


def test_one_variant_back_when_two_were_asked_is_still_a_paper():
    result = a._validate_paper({"questions": [_q("A1", 2)]}, 1, two=True)
    assert result["questions"] == [_q("A1", 2)] and "variant2" not in result


def test_a_broken_first_variant_is_the_error():
    result = a._validate_paper({"variants": [{"questions": []}, {"questions": [_q("B1", 1)]}]}, 1, two=True)
    assert result.get("error")
