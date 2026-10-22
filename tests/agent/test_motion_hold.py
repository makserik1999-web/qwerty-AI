"""Active hold: a formula's terms light up as the narrator says them.

Two halves. The agent asks Azure for word boundaries along with the audio and
leaves them in the manifest (narration._synthesise_with_words_sync, only under
MOTION_LAYER=1). The renderer matches each term of the formula to a spoken
word and schedules the highlight (anyq_motion: words_match, match_terms,
schedule). When nothing can be matched the terms take turns, evenly.

What must never happen: narration failing because the timings could not be
had. Timings are a nicety; the audio is the product.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "agent", REPO_ROOT / "tests" / "stubs",
              REPO_ROOT / "agent" / "manim-mcp-server" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import anyq_motion  # noqa: E402
from anyq import narration  # noqa: E402
from anyq.prompts import build_manim_system_prompt  # noqa: E402

# What Azure returned for this sentence (measured, kk-KZ-AigulNeural, -8%).
SPOKEN = [
    (0.054, 0.244, "Күш"),
    (0.272, 0.801, "массаның"),
    (0.842, 1.277, "үдеуге"),
    (1.304, 2.146, "көбейтіндісіне"),
    (2.160, 2.527, "тең"),
]


class TestWordsMatch:
    @pytest.mark.parametrize("term, spoken", [
        ("масса", "массаның"),       # Kazakh case ending
        ("үдеу", "үдеуге"),
        ("сила", "силу"),            # Russian, last letter changes
        ("ускорение", "ускорения"),
        ("Күш", "күш,"),             # case and punctuation
        ("F", "F"),
    ])
    def test_the_same_word_inflected_matches(self, term, spoken):
        assert anyq_motion.words_match(term, spoken)

    @pytest.mark.parametrize("term, spoken", [
        ("a", "ал"),                 # a letter is not the start of a word
        ("m", "м"),
        ("масса", "мастер"),         # three letters in common is not enough
        ("күш", "көп"),
        ("", "күш"),
    ])
    def test_different_words_do_not(self, term, spoken):
        assert not anyq_motion.words_match(term, spoken)


class TestMatchTerms:
    def test_each_term_gets_its_words_start(self):
        times = anyq_motion.match_terms(["Күш", "масса", "үдеу"], SPOKEN)
        assert times == [0.054, 0.272, 0.842]

    def test_the_search_goes_left_to_right(self):
        """The second "масса" is looked for after the first term's word."""
        spoken = [(0.0, 0.1, "масса"), (1.0, 1.1, "күш"), (2.0, 2.1, "масса")]
        assert anyq_motion.match_terms(["күш", "масса"], spoken) == [1.0, 2.0]

    def test_a_word_not_said_is_none(self):
        assert anyq_motion.match_terms(["Күш", "жылдамдық", "үдеу"], SPOKEN) == [0.054, None, 0.842]


class TestSchedule:
    def test_nothing_matched_means_even_turns(self):
        assert anyq_motion.schedule([None, None, None, None], 10.0, 14.0) == [10, 11, 12, 13]

    def test_matched_terms_keep_their_moment(self):
        assert anyq_motion.schedule([10.5, 11.2, 12.9], 10.0, 14.0) == [10.5, 11.2, 12.9]

    def test_the_gaps_between_anchors_are_shared_evenly(self):
        assert anyq_motion.schedule([None, 12.0, None, None], 10.0, 14.0) == \
            pytest.approx([11.0, 12.0, 12.6667, 13.3333], abs=1e-3)

    def test_words_said_before_the_hold_light_at_its_start(self):
        """Said while the formula was still being written."""
        assert anyq_motion.schedule([9.0, 9.5, 11.0], 10.0, 14.0) == [10.0, 10.0, 11.0]

    def test_it_never_runs_backwards_or_past_the_end(self):
        out = anyq_motion.schedule([12.0, 11.0, 20.0], 10.0, 14.0)
        assert out == sorted(out) and out[-1] <= 14.0

    def test_no_terms_no_schedule(self):
        assert anyq_motion.schedule([], 0, 1) == []


class TestOperators:
    @pytest.mark.parametrize("tex", ["=", "+", "-", "/", r"\cdot", r"\times", "{=}", " = ", r"\\"])
    def test_punctuation_of_a_formula_is_not_a_term(self, tex):
        assert anyq_motion.is_operator(tex)

    @pytest.mark.parametrize("tex", ["F", "m", "a^2", r"\frac{F}{m}", "v_0", r"\Delta t"])
    def test_symbols_are_terms(self, tex):
        assert not anyq_motion.is_operator(tex)


# ---------------------------------------------------------------- the agent


def _script(*lines: str) -> str:
    blocks = "".join(f'        with self.voiceover(text="{line}") as t:\n'
                     "            self.play(FadeIn(Circle()), run_time=0.5)\n" for line in lines)
    return ("from manim import *\nfrom anyq_narration import MotionScene\n\n"
            "class Demo(MotionScene):\n    def construct(self):\n" + blocks)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(narration, "AZURE_SPEECH_KEY", "k")
    monkeypatch.setattr(narration, "AZURE_SPEECH_REGION", "r")
    monkeypatch.setattr(narration, "NARRATION_ENABLED", True)
    calls = {"sdk": 0, "rest": 0}

    def sdk(text, voice, locale):
        calls["sdk"] += 1
        return b"mp3-sdk", [[0.05, 0.3, text.split()[0]]]

    def rest(text, voice, locale):
        calls["rest"] += 1
        return b"mp3-rest"

    monkeypatch.setattr(narration, "_synthesise_with_words_sync", sdk)
    monkeypatch.setattr(narration, "_synthesise_sync", rest)
    return calls


def _manifest(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestWordTimingsReachTheManifest:
    async def test_under_the_layer_they_do(self, configured, monkeypatch):
        monkeypatch.setattr(narration, "MOTION_LAYER", True)
        path = await narration.prepare(_script("Күш массаның.", "Үдеу тең."), "kk")
        try:
            data = _manifest(path)
            assert len(data["words"]) == 2
            assert configured == {"sdk": 2, "rest": 0}
            first = narration._shim().narration_key("Күш массаның.")
            assert data["words"][first] == [[0.05, 0.3, "Күш"]]
            assert (Path(path).parent / data["lines"][first]).read_bytes() == b"mp3-sdk"
        finally:
            narration.cleanup(path)

    async def test_without_it_nothing_changes(self, configured, monkeypatch):
        monkeypatch.setattr(narration, "MOTION_LAYER", False)
        path = await narration.prepare(_script("Күш массаның."), "kk")
        try:
            assert "words" not in _manifest(path)
            assert configured == {"sdk": 0, "rest": 1}
        finally:
            narration.cleanup(path)

    async def test_a_failing_sdk_falls_back_to_plain_speech(self, configured, monkeypatch):
        """No timings is a formula lit evenly; no audio would be a silent video."""
        monkeypatch.setattr(narration, "MOTION_LAYER", True)

        def broken(*a, **k):
            raise RuntimeError("azure sdk ResultReason.Canceled: websocket refused")

        monkeypatch.setattr(narration, "_synthesise_with_words_sync", broken)
        path = await narration.prepare(_script("Күш массаның."), "kk")
        try:
            data = _manifest(path)
            assert "words" not in data
            assert configured["rest"] == 1
            assert (Path(path).parent / next(iter(data["lines"].values()))).read_bytes() == b"mp3-rest"
        finally:
            narration.cleanup(path)


class TestThePrompt:
    def test_it_asks_for_formulas_in_parts_and_read_along(self):
        motion = build_manim_system_prompt(True, "Kazakh", motion=True)
        assert "M3." in motion and "self.read_formula(formula" in motion
        assert 'never MathTex("F = ma")' in motion

    def test_without_the_layer_it_does_not(self):
        assert "read_formula" not in build_manim_system_prompt(True, "Kazakh")
