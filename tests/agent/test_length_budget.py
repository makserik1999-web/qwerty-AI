"""The length budget: asking for it, checking it, and never failing over it.

A video lasts as long as its narration, and the narration is readable from
the script before a single frame is rendered. That is the whole design: the
model is asked for a character budget, and what it wrote is measured while a
correction still costs one model call instead of ninety seconds of rendering.

The rule these tests exist to hold is the last one. Length is a preference.
A person who asked a question and got a fifty-second video instead of a
forty-second one has been mildly disappointed; a person who got an error
because the video would have been the wrong length has been failed.
"""

import sys
from pathlib import Path

import pytest

# The conftest fixture that puts `agent/` on sys.path is autouse, but it runs
# after this module is imported - and parametrize needs the closed set at
# COLLECTION time. So the same paths are added here, before the imports.
REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "agent",
              REPO_ROOT / "tests" / "stubs",
              REPO_ROOT / "agent" / "manim-mcp-server" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from anyq import nodes  # noqa: E402
from anyq.config import (  # noqa: E402
    VIDEO_LENGTH_BUDGETS,
    VIDEO_LENGTH_DEFAULT,
    VIDEO_LENGTHS,
)
from anyq.prompts import (  # noqa: E402
    build_manim_system_prompt,
    narration_budget_rule,
)


def _script(*lines: str) -> str:
    """A minimal narrated script that says exactly these lines."""
    blocks = "\n".join(
        f'        with self.voiceover(text="{line}") as tracker:\n'
        f"            self.play(FadeIn(t), run_time=tracker.duration)"
        for line in lines
    )
    return (
        "from manim import *\n\n"
        "class Demo(VoiceoverScene):\n"
        "    def construct(self):\n"
        "        t = Text('x')\n" + blocks
    )


class TestTheBudgetIsAsked:
    def test_every_bucket_has_a_budget(self):
        """A name the interface offers with no budget behind it does nothing."""
        assert set(VIDEO_LENGTHS) == set(VIDEO_LENGTH_BUDGETS)

    def test_the_buckets_do_not_overlap_and_go_up(self):
        low_s, high_s = VIDEO_LENGTH_BUDGETS["short"]
        low_m, high_m = VIDEO_LENGTH_BUDGETS["medium"]
        low_l, high_l = VIDEO_LENGTH_BUDGETS["long"]

        assert low_s < high_s < low_m < high_m < low_l < high_l

    def test_the_numbers_reach_the_prompt(self):
        rule = narration_budget_rule(380, 510)

        assert "380" in rule and "510" in rule

    def test_the_default_prompt_is_untouched(self):
        """scripts/check.sh pins its sha256; the parameter must be optional.

        Not a formality: the pin is what proves the Manim instructions did not
        drift while something else was being changed, and a signature change
        that quietly moved it would retire that guarantee.
        """
        with_budget = build_manim_system_prompt(True, "Russian",
                                                narration_budget_rule(380, 510))

        assert build_manim_system_prompt(True, "Russian") != with_budget
        assert "under 2000" in build_manim_system_prompt(True, "Russian")


class TestOnlyRealLengthsGetThrough:
    @pytest.mark.parametrize("nonsense", ["", "tiny", "42", None, "30s", "../x"])
    def test_nonsense_becomes_the_default(self, nonsense):
        """This value picks a budget and reaches a cache key upstream."""
        assert nodes._resolve_video_length({"video_length": nonsense}) == (
            VIDEO_LENGTH_DEFAULT
        )

    @pytest.mark.parametrize("name", VIDEO_LENGTHS)
    def test_a_real_length_is_kept(self, name):
        assert nodes._resolve_video_length({"video_length": name}) == name

    @pytest.mark.parametrize("cased", ["SHORT", " Short ", "LoNg"])
    def test_casing_and_spacing_are_forgiven(self, cased):
        """A real choice, typed differently, is still that choice.

        Substituting the default here would be worse than rejecting: the
        person picked a length, the video comes back another length, and
        nothing anywhere says why. The backend normalises the same way before
        its own closed-set check, so the two ends cannot disagree.
        """
        assert nodes._resolve_video_length({"video_length": cased}) == cased.strip().lower()


class TestMeasuringWhatWillBeSpoken:
    def test_it_counts_the_narration(self):
        script = _script("Небо голубое.", "Свет рассеивается.")

        assert nodes._narration_chars(script) == len("Небо голубое.") + len(
            "Свет рассеивается."
        )

    def test_a_silent_script_counts_zero(self):
        assert nodes._narration_chars("from manim import *\n") == 0

    def test_captions_do_not_count(self):
        """Only what is SPOKEN sets the duration.

        Text on screen appears inside an animation that is already timed by
        the sentence being said, so counting it would inflate the estimate and
        make every video come out short.
        """
        spoken = _script("Небо голубое.")
        with_caption = spoken.replace(
            "t = Text('x')", "t = Text('очень длинная подпись на экране')"
        )

        assert nodes._narration_chars(with_caption) == nodes._narration_chars(spoken)


class TestItNeverFailsTheRequest:
    """The rule that matters most, held against the ways it could break."""

    async def test_a_script_inside_the_budget_is_returned_untouched(self, monkeypatch):
        low, _ = VIDEO_LENGTH_BUDGETS["medium"]
        script = _script("а" * (low + 20))

        async def explode(*args, **kwargs):
            raise AssertionError("no rewrite should have been requested")

        monkeypatch.setattr(nodes, "_llm_chat", explode)

        out = await nodes._fit_narration_budget(
            script, {"video_length": "medium"}, "Russian", True
        )

        assert out == script

    async def test_a_failing_rewrite_call_keeps_the_original(self, monkeypatch):
        script = _script("коротко")

        async def explode(*args, **kwargs):
            raise RuntimeError("upstream is down")

        monkeypatch.setattr(nodes, "_llm_chat", explode)

        out = await nodes._fit_narration_budget(
            script, {"video_length": "long"}, "Russian", True
        )

        assert out == script, "a length correction must never fail the request"

    async def test_an_unsafe_rewrite_is_refused(self, monkeypatch):
        """The rewrite goes through the safety validator like anything else."""
        script = _script("коротко")

        class _Resp:
            content = "import os\nos.system('rm -rf /')\n"

        async def rewrite(*args, **kwargs):
            return _Resp()

        monkeypatch.setattr(nodes, "_llm_chat", rewrite)

        out = await nodes._fit_narration_budget(
            script, {"video_length": "long"}, "Russian", True
        )

        assert out == script

    async def test_a_rewrite_that_moved_further_away_is_refused(self, monkeypatch):
        """A model that "fixed" the length by making it worse is not a fix.

        Without this the correction could make the video less like what was
        asked for while reporting that it had helped.
        """
        low, high = VIDEO_LENGTH_BUDGETS["short"]
        script = _script("а" * (high + 50))  # a little over

        class _Resp:
            content = _script("а" * (high + 4000))  # far further over

        async def rewrite(*args, **kwargs):
            return _Resp()

        monkeypatch.setattr(nodes, "_llm_chat", rewrite)

        out = await nodes._fit_narration_budget(
            script, {"video_length": "short"}, "Russian", True
        )

        assert out == script

    async def test_a_rewrite_that_helped_is_taken(self, monkeypatch):
        low, high = VIDEO_LENGTH_BUDGETS["short"]
        script = _script("а" * (high + 800))
        better = _script("а" * ((low + high) // 2))

        class _Resp:
            content = better

        async def rewrite(*args, **kwargs):
            return _Resp()

        monkeypatch.setattr(nodes, "_llm_chat", rewrite)

        out = await nodes._fit_narration_budget(
            script, {"video_length": "short"}, "Russian", True
        )

        assert nodes._narration_chars(out) == nodes._narration_chars(better)

    async def test_a_silent_script_is_left_alone(self, monkeypatch):
        """Nothing spoken means nothing this can control - and no call made."""
        script = "from manim import *\n\nclass Demo(Scene):\n    def construct(self):\n        pass\n"

        async def explode(*args, **kwargs):
            raise AssertionError("no rewrite should have been requested")

        monkeypatch.setattr(nodes, "_llm_chat", explode)

        assert await nodes._fit_narration_budget(
            script, {"video_length": "short"}, "Russian", True
        ) == script


class TestItTriesTwiceAndStops:
    """One pass was measurably not enough, and unbounded passes are a bill.

    Measured live: asked for 1090-1165, the model wrote 675 and the single
    rewrite reached only 868 - closer, accepted, and still a 62-second video
    where 85 was chosen. It closes roughly 60% of the gap per pass, so the
    second one lands; a third would be paying to find that out.
    """

    async def test_a_second_pass_finishes_what_the_first_started(self, monkeypatch):
        low, high = VIDEO_LENGTH_BUDGETS["long"]
        calls = []
        # 60% of the gap per pass, the way the real model behaves.
        steps = [_script("a" * (low - 200)), _script("a" * ((low + high) // 2))]

        class _Resp:
            def __init__(self, body):
                self.content = body

        async def rewrite(messages, **kwargs):
            calls.append(1)
            return _Resp(steps[len(calls) - 1])

        monkeypatch.setattr(nodes, "_llm_chat", rewrite)

        out = await nodes._fit_narration_budget(
            _script("a" * 300), {"video_length": "long"}, "Russian", True
        )

        assert len(calls) == 2, "one pass left it outside the window"
        assert low <= nodes._narration_chars(out) <= high

    async def test_it_stops_once_inside_the_window(self, monkeypatch):
        """No call is made for a length that is already right."""
        low, high = VIDEO_LENGTH_BUDGETS["medium"]
        calls = []

        class _Resp:
            content = _script("a" * ((low + high) // 2))

        async def rewrite(messages, **kwargs):
            calls.append(1)
            return _Resp()

        monkeypatch.setattr(nodes, "_llm_chat", rewrite)

        await nodes._fit_narration_budget(
            _script("a" * 200), {"video_length": "medium"}, "Russian", True
        )

        assert len(calls) == 1, "it kept asking after the length was correct"

    async def test_it_never_asks_more_than_twice(self, monkeypatch):
        """A model that never complies must not be asked forever."""
        calls = []

        class _Resp:
            content = ""

        async def rewrite(messages, **kwargs):
            calls.append(1)
            return _Resp()

        monkeypatch.setattr(nodes, "_llm_chat", rewrite)

        out = await nodes._fit_narration_budget(
            _script("a" * 100), {"video_length": "long"}, "Russian", True
        )

        assert len(calls) <= nodes._LENGTH_REWRITE_ATTEMPTS
        assert out  # and a script still comes back


def _computed_script(*lines: str) -> str:
    """A script whose spoken lines are f-strings - unreadable before a render."""
    blocks = "\n".join(
        f'        with self.voiceover(text=f"{line}{{1 + 1}}") as tracker:\n'
        f"            self.play(FadeIn(t), run_time=tracker.duration)"
        for line in lines
    )
    return (
        "from manim import *\n\n"
        "class Demo(VoiceoverScene):\n"
        "    def construct(self):\n"
        "        t = Text('x')\n" + blocks
    )


class TestSpeechThatCannotBeRead:
    """Voiceover blocks whose text is assembled at runtime.

    The manifest is built from the AST before the render, so a computed line
    cannot be synthesised. ONE such line is handled by design - left out, and
    the renderer raises loudly, which is the documented intent. ALL of them was
    the gap: the manifest comes out empty, which is indistinguishable from
    "this video has no narration", and it renders in silence instead. Seen
    twice in about fifteen live renders, and it takes the length control down
    with it, because the length follows the speech.
    """

    def test_the_fixture_really_is_unreadable(self):
        """Otherwise every test below would pass for the wrong reason."""
        script = _computed_script("Небо голубое.")

        assert script.count("self.voiceover") == 1
        assert nodes._narration_chars(script) == 0

    async def test_a_readable_script_is_never_touched(self, monkeypatch):
        script = _script("Небо голубое.")

        async def explode(*args, **kwargs):
            raise AssertionError("a working script was sent for rewriting")

        monkeypatch.setattr(nodes, "_llm_chat", explode)

        assert await nodes._ensure_spoken_lines_are_literal(script) == script

    async def test_a_silent_script_is_never_touched(self, monkeypatch):
        """No blocks means no narration was wanted - nothing to recover."""

        async def explode(*args, **kwargs):
            raise AssertionError("a silent script was sent for rewriting")

        monkeypatch.setattr(nodes, "_llm_chat", explode)

        script = "from manim import *\n\nclass Demo(Scene):\n    pass\n"
        assert await nodes._ensure_spoken_lines_are_literal(script) == script

    async def test_recovered_lines_are_taken(self, monkeypatch):
        class _Resp:
            content = _script("Небо голубое.", "Свет рассеивается.")

        async def rewrite(*args, **kwargs):
            return _Resp()

        monkeypatch.setattr(nodes, "_llm_chat", rewrite)

        out = await nodes._ensure_spoken_lines_are_literal(
            _computed_script("Небо голубое.", "Свет рассеивается.")
        )

        assert nodes._narration_chars(out) > 0

    async def test_a_rewrite_that_is_still_unreadable_is_refused(self, monkeypatch):
        """Changing the script for nothing is worse than leaving it alone."""
        script = _computed_script("Небо голубое.")

        class _Resp:
            content = _computed_script("Небо голубое.")

        async def rewrite(*args, **kwargs):
            return _Resp()

        monkeypatch.setattr(nodes, "_llm_chat", rewrite)

        assert await nodes._ensure_spoken_lines_are_literal(script) == script

    async def test_an_unsafe_rewrite_is_refused(self, monkeypatch):
        script = _computed_script("Небо голубое.")

        class _Resp:
            content = "import os\nos.system('rm -rf /')\n"

        async def rewrite(*args, **kwargs):
            return _Resp()

        monkeypatch.setattr(nodes, "_llm_chat", rewrite)

        assert await nodes._ensure_spoken_lines_are_literal(script) == script

    async def test_a_failing_call_keeps_the_original(self, monkeypatch):
        """Narration is never fatal, and neither is trying to rescue it."""
        script = _computed_script("Небо голубое.")

        async def explode(*args, **kwargs):
            raise RuntimeError("upstream is down")

        monkeypatch.setattr(nodes, "_llm_chat", explode)

        assert await nodes._ensure_spoken_lines_are_literal(script) == script
