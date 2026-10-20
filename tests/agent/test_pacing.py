"""One thing at a time, at a speed a person can read.

Two complaints from watching the videos, and they turn out to be the same
sentence in the prompt.

SLOW. Rule 15 required `run_time=tracker.duration` on every animation, so each
one was stretched across its whole spoken sentence. A five-second sentence
bought a five-second fade. It was never needed for synchronisation:
manim-voiceover's `voiceover` block calls wait_for_voiceover() when it exits,
so the block already lasts exactly as long as its audio whatever happened
inside it.

MUSH. Rule L1 swapped captions with `Transform(caption, Text(...))`, which
morphs the letter shapes of one string into the letter shapes of another - and
did it over five seconds. L2's fallback was
`self.play(FadeOut(old), FadeIn(new))`, which plays both at once, so the old
caption is still half on screen while the new one is being drawn over it.

The prompt now says the opposite. This guard is the half that does not depend
on the model reading it: a script is rewritten so that what leaves the screen
leaves first, and no animation is stretched.
"""

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))

from anyq.script_guard import _pace_animations  # noqa: E402

CAP = 1.0
EXIT = 0.35


def pace(script: str):
    return _pace_animations(script, CAP, EXIT)


def wrap(body: str) -> str:
    """A minimal valid script around one construct() body."""
    lines = "\n".join(f"        {ln}" if ln.strip() else "" for ln in body.splitlines())
    return (
        "from manim import *\n"
        "from anyq_narration import VoiceoverScene\n\n"
        "class Demo(VoiceoverScene):\n"
        "    def construct(self):\n" + lines + "\n"
    )


def plays(script: str):
    """Every self.play(...) call in the script, in source order."""
    tree = ast.parse(script)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "play"
    ]


# --------------------------------------------------- what leaves, leaves first --


class TestNothingOverlaps:
    def test_a_fadeout_and_a_fadein_become_two_calls(self):
        out, changed = pace(wrap("self.play(FadeOut(old), FadeIn(new))"))
        assert changed
        assert len(plays(out)) == 2, out

    def test_the_departure_comes_first(self):
        out, _ = pace(wrap("self.play(FadeOut(old), FadeIn(new))"))
        first, second = plays(out)
        assert first.args[0].func.id == "FadeOut"
        assert second.args[0].func.id == "FadeIn"

    def test_the_departure_is_the_quicker_of_the_two(self):
        """A thing leaving is not information; it is the room being cleared."""
        out, _ = pace(wrap(
            "with self.voiceover(text='a') as tracker:\n"
            "    self.play(FadeOut(old), FadeIn(new), run_time=tracker.duration)"
        ))
        assert f"run_time={EXIT}" in out, out

    def test_every_departure_goes_in_the_first_call(self):
        out, _ = pace(wrap("self.play(FadeOut(a), FadeOut(b), Write(c))"))
        first, second = plays(out)
        assert [x.func.id for x in first.args] == ["FadeOut", "FadeOut"]
        assert [x.func.id for x in second.args] == ["Write"]

    @pytest.mark.parametrize("enter", ["FadeIn", "Write", "Create",
                                       "DrawBorderThenFill", "GrowFromCenter"])
    def test_it_is_not_only_fadein_that_counts_as_arriving(self, enter):
        out, changed = pace(wrap(f"self.play(FadeOut(old), {enter}(new))"))
        assert changed, out
        assert len(plays(out)) == 2

    def test_something_that_is_neither_rides_with_the_arrival(self):
        """A shift or a highlight is not a departure; splitting it off would
        invent a step that was not in the script."""
        out, _ = pace(wrap("self.play(FadeOut(old), FadeIn(new), Indicate(c))"))
        _, second = plays(out)
        assert {x.func.id for x in second.args} == {"FadeIn", "Indicate"}


class TestWhatIsLeftAlone:
    def test_a_call_that_only_removes_is_untouched(self):
        script = wrap("self.play(FadeOut(a), FadeOut(b))")
        assert pace(script) == (script, False)

    def test_a_call_that_only_adds_is_untouched(self):
        script = wrap("self.play(Create(axes), Write(label))")
        assert pace(script) == (script, False)

    def test_a_deliberate_fixed_run_time_is_untouched(self):
        """MoveAlongPath over three seconds is a choice, not an accident."""
        script = wrap("self.play(MoveAlongPath(dot, circle), run_time=3)")
        assert pace(script) == (script, False)

    def test_a_script_that_does_not_parse_is_handed_on_unchanged(self):
        """The validator reports the syntax error; this must not mask it."""
        broken = "class Demo(:\n    pass"
        assert pace(broken) == (broken, False)

    def test_an_empty_script_is_survivable(self):
        assert pace("") == ("", False)


# ------------------------------------------------------ nothing is stretched --


class TestSpeed:
    def test_a_tracker_length_run_time_is_capped(self):
        out, changed = pace(wrap(
            "with self.voiceover(text='a') as tracker:\n"
            "    self.play(FadeIn(earth), run_time=tracker.duration)"
        ))
        assert changed
        assert f"run_time=min({CAP}, tracker.duration)" in out, out

    def test_a_fraction_of_the_tracker_is_capped_too(self):
        """`tracker.duration * 0.4` is still a share of a whole sentence."""
        out, changed = pace(wrap(
            "with self.voiceover(text='a') as tracker:\n"
            "    self.play(FadeIn(e), run_time=tracker.duration * 0.4)"
        ))
        assert changed
        assert f"min({CAP}, tracker.duration * 0.4)" in out, out

    def test_the_cap_is_a_ceiling_and_not_a_replacement(self):
        """A short sentence keeps its short animation - min(), not a constant."""
        out, _ = pace(wrap(
            "with self.voiceover(text='a') as tracker:\n"
            "    self.play(FadeIn(e), run_time=tracker.duration)"
        ))
        assert "min(" in out and "tracker.duration" in out


# ------------------------------------------------- it must not break scripts --


class TestTheRewriteIsSafe:
    def test_the_result_still_parses(self):
        out, _ = pace(wrap(
            "with self.voiceover(text='bir') as tracker:\n"
            "    self.play(FadeOut(caption), FadeIn(new), run_time=tracker.duration)"
        ))
        ast.parse(out)

    def test_a_multi_line_call_is_rewritten_correctly(self):
        out, changed = pace(wrap(
            "self.play(\n"
            "    FadeOut(old),\n"
            "    FadeIn(new),\n"
            ")"
        ))
        assert changed
        ast.parse(out)
        assert len(plays(out)) == 2

    def test_indentation_inside_a_with_block_survives(self):
        out, _ = pace(wrap(
            "with self.voiceover(text='a') as tracker:\n"
            "    self.play(FadeOut(old), FadeIn(new))"
        ))
        tree = ast.parse(out)
        withs = [n for n in ast.walk(tree) if isinstance(n, ast.With)]
        assert len(withs) == 1
        assert len(withs[0].body) == 2, "the split calls fell out of the block"

    def test_the_spoken_lines_are_untouched(self):
        """The manifest is keyed on these exactly; a changed byte is a silent
        video. Nothing outside the rewritten statements may move."""
        script = wrap(
            "with self.voiceover(text='Жер денелерді өзіне тартады.') as tracker:\n"
            "    self.play(FadeOut(old), FadeIn(new), run_time=tracker.duration)"
        )
        out, _ = pace(script)
        assert "text='Жер денелерді өзіне тартады.'" in out

    def test_comments_elsewhere_survive(self):
        out, _ = pace(wrap(
            "# build-up\n"
            "self.play(Create(axes))\n"
            "self.play(FadeOut(axes), FadeIn(graph))"
        ))
        assert "# build-up" in out


# --------------------------------------------------------- the prompt agrees --


class TestThePromptNoLongerAsksForTheBug:
    @pytest.fixture(scope="class")
    def prompt(self) -> str:
        from anyq.prompts import build_manim_system_prompt

        return build_manim_system_prompt(True, "Kazakh")

    def test_it_no_longer_demands_the_stretched_run_time(self, prompt):
        """The one mention left is the rule forbidding it."""
        assert prompt.count("run_time=tracker.duration") == 1
        assert "NEVER write run_time=tracker.duration" in prompt

    def test_it_forbids_transforming_text_into_other_text(self, prompt):
        assert "NEVER Transform() ONE PIECE OF TEXT INTO A DIFFERENT PIECE OF TEXT" in prompt

    def test_it_forbids_a_departure_and_an_arrival_in_one_call(self, prompt):
        assert "NEVER put a disappearance and an appearance in the SAME self.play" in prompt

    def test_the_length_rewrite_no_longer_restores_it(self, prompt):
        """A rewrite pass that says "keep run_time=tracker.duration" would put
        the slowness back on every length correction."""
        from anyq.prompts import (
            REWRITE_NARRATION_LENGTH_SYSTEM_PROMPT,
            REWRITE_VOICEOVER_LITERALS_SYSTEM_PROMPT,
        )

        assert "tracker.duration" not in REWRITE_NARRATION_LENGTH_SYSTEM_PROMPT
        assert "tracker.duration" not in REWRITE_VOICEOVER_LITERALS_SYSTEM_PROMPT
