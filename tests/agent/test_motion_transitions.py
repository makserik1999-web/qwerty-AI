"""Changes of step morph instead of fading to an empty frame (motion layer, L8).

Under MOTION_LAYER=1 the prompt asks for TransformMatchingTex between two
forms of a formula and ReplacementTransform between two shapes, and
_morph_transitions rewrites the plain "fade the old one out, write the new
one in" pairs the model still writes. These tests hold its one promise: it
only ever changes a script into the same script plus motion - never into one
that shows something different, loses an object, or does not parse.
"""

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "agent", REPO_ROOT / "tests" / "stubs",
              REPO_ROOT / "agent" / "manim-mcp-server" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from anyq.prompts import build_manim_system_prompt  # noqa: E402
from anyq.script_guard import (  # noqa: E402
    _morph_transitions,
    _pace_animations,
    validate_manim_script,
)


def wrap(body: str) -> str:
    lines = "\n".join(f"        {ln}" if ln.strip() else "" for ln in body.splitlines())
    return (
        "from manim import *\n"
        "from anyq_narration import MotionScene\n\n"
        "class Demo(MotionScene):\n"
        "    def construct(self):\n" + lines + "\n"
    )


def plays(script: str):
    tree = ast.parse(script)
    return [ast.get_source_segment(script, n) for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "play"]


FORMULAS = (
    'eq1 = MathTex("F", "=", "m", "a")\n'
    "self.play(Write(eq1), run_time=0.8)\n"
    "self.play(FadeOut(eq1), run_time=0.35)\n"
    'eq2 = MathTex("a", "=", "F", "/", "m").move_to(eq1)\n'
    "self.play(Write(eq2), run_time=0.8)\n"
)


class TestWhatItMorphs:
    def test_a_formula_becomes_the_next_one(self):
        out, morphs, clears = _morph_transitions(wrap(FORMULAS))

        assert morphs == 1 and clears == 0
        assert "self.play(TransformMatchingTex(eq1, eq2), run_time=0.8)" in out
        assert "FadeOut(eq1)" not in out
        assert validate_manim_script(out) == (True, "")

    def test_a_shape_becomes_the_next_one(self):
        out, morphs, _ = _morph_transitions(wrap(
            "sq = Square(side_length=2).shift(LEFT)\n"
            "self.play(Create(sq))\n"
            "self.play(FadeOut(sq), run_time=0.35)\n"
            "c = Circle(radius=1).shift(RIGHT)\n"
            "self.play(Create(c))\n"
        ))

        assert morphs == 1
        assert "ReplacementTransform(sq, c)" in out

    def test_the_rest_of_a_departure_still_leaves_first(self):
        """A caption leaving with the formula keeps leaving, on its own,
        before anything arrives (L1); only the formula morphs."""
        out, morphs, _ = _morph_transitions(wrap(
            'cap = Text("Бір")\n'
            'eq1 = MathTex("x", "=", "1")\n'
            "self.play(FadeIn(cap), Write(eq1))\n"
            "self.play(FadeOut(cap), FadeOut(eq1), run_time=0.35)\n"
            'eq2 = MathTex("x", "=", "2")\n'
            'cap2 = Text("Екі")\n'
            "self.play(Write(eq2), FadeIn(cap2))\n"
        ))

        assert morphs == 1
        assert "self.play(FadeOut(cap), run_time=0.35)" in out
        assert "self.play(TransformMatchingTex(eq1, eq2), FadeIn(cap2))" in out

    def test_it_finishes_what_pacing_split(self):
        """`self.play(FadeOut(a), Write(b))` is split by the pacing guard into
        out-then-in; the morph pass then makes the pair one change."""
        script = wrap(
            'eq1 = MathTex("v", "=", "s", "/", "t")\n'
            "self.play(Write(eq1))\n"
            'eq2 = MathTex("s", "=", "v", "t")\n'
            "self.play(FadeOut(eq1), Write(eq2))\n"
        )
        paced, _ = _pace_animations(script, 1.0, 0.35)
        out, morphs, _ = _morph_transitions(paced)

        assert morphs == 1
        assert plays(out)[-1] == "self.play(TransformMatchingTex(eq1, eq2))"

    def test_inside_a_voiceover_block(self):
        script = wrap(
            'eq1 = MathTex("F", "=", "m", "a")\n'
            'with self.voiceover(text="Бір.") as tracker:\n'
            "    self.play(Write(eq1), run_time=0.8)\n"
            'with self.voiceover(text="Екі.") as tracker:\n'
            "    self.play(FadeOut(eq1), run_time=0.35)\n"
            '    eq2 = MathTex("a", "=", "F", "/", "m")\n'
            "    self.play(Write(eq2), run_time=0.8)\n"
        )
        out, morphs, _ = _morph_transitions(script)

        assert morphs == 1
        assert "TransformMatchingTex(eq1, eq2)" in out
        assert validate_manim_script(out) == (True, "")

    def test_a_departure_in_several_plays_is_one_departure(self):
        """Seen in real scripts: the diagram leaves in one play, the caption
        in the next, then the new picture arrives. Same empty frame."""
        script = wrap(
            "sq = Square()\n"
            'cap = Text("Бір")\n'
            "self.play(Create(sq), FadeIn(cap))\n"
            "self.play(FadeOut(sq), run_time=0.5)\n"
            "self.play(FadeOut(cap), run_time=0.3)\n"
            "c = Circle()\n"
            'cap2 = Text("Екі")\n'
            "self.play(Create(c), FadeIn(cap2))\n"
        )
        out, morphs, clears = _morph_transitions(script)

        assert morphs == 1
        assert "self.play(ReplacementTransform(sq, c), FadeIn(cap2))" in out
        assert "self.play(FadeOut(cap), run_time=0.3)" in out
        assert "FadeOut(sq)" not in out
        assert clears == 0, "one caption leaving alone is not a clear"
        assert validate_manim_script(out) == (True, "")

    def test_running_it_twice_changes_nothing_more(self):
        once, _, _ = _morph_transitions(wrap(FORMULAS))
        twice, morphs, _ = _morph_transitions(once)

        assert twice == once and morphs == 0


class TestWhatItLeavesAlone:
    def test_captions(self):
        """Text into other text is L2's garbled mush - never morphed."""
        script = wrap(
            'cap = Text("Бір").to_edge(DOWN)\n'
            "self.play(FadeIn(cap))\n"
            "self.play(FadeOut(cap), run_time=0.35)\n"
            'cap = Text("Екі").to_edge(DOWN)\n'
            "self.play(FadeIn(cap))\n"
        )
        assert _morph_transitions(script) == (script, 0, 0)

    def test_an_old_object_that_comes_back(self):
        """After a morph the old object is gone; fading it in again later
        would bring back a broken copy."""
        script = wrap(FORMULAS + "self.play(FadeIn(eq1))\n")
        out, morphs, _ = _morph_transitions(script)

        assert morphs == 0 and out == script

    def test_an_old_name_reused_for_something_new_is_fine(self):
        script = wrap(FORMULAS + 'eq1 = MathTex("y")\nself.play(Write(eq1))\n')
        _, morphs, _ = _morph_transitions(script)

        assert morphs == 1

    def test_a_shape_does_not_become_a_formula(self):
        script = wrap(
            "sq = Square()\n"
            "self.play(Create(sq))\n"
            "self.play(FadeOut(sq), run_time=0.35)\n"
            'eq = MathTex("a", "^2")\n'
            "self.play(Write(eq))\n"
        )
        assert _morph_transitions(script)[:2] == (script, 0)

    def test_something_played_in_between(self):
        script = wrap(
            'eq1 = MathTex("x")\n'
            "self.play(Write(eq1))\n"
            "self.play(FadeOut(eq1), run_time=0.35)\n"
            "self.wait(1)\n"
            'eq2 = MathTex("y")\n'
            "self.play(Write(eq2))\n"
        )
        assert _morph_transitions(script)[:2] == (script, 0)

    def test_objects_whose_origin_is_unknown(self):
        script = wrap(
            "self.play(FadeOut(group), run_time=0.35)\n"
            "self.play(Write(other))\n"
        )
        assert _morph_transitions(script)[:2] == (script, 0)

    def test_broken_code(self):
        assert _morph_transitions("def (") == ("def (", 0, 0)


class TestClearsAreCounted:
    def test_fading_several_things_to_an_empty_frame(self):
        script = wrap(
            "a = Text('a')\nb = Text('b')\n"
            "self.play(FadeIn(a), FadeIn(b))\n"
            "self.play(FadeOut(a), FadeOut(b))\n"
            "c = Text('c')\n"
            "self.play(FadeIn(c))\n"
        )
        assert _morph_transitions(script)[2] == 1

    def test_a_clear_spread_over_several_plays(self):
        script = wrap(
            "self.play(FadeOut(group), FadeOut(t1), FadeOut(t2))\n"
            "self.play(FadeOut(cap))\n"
            'eq = MathTex("v", "=", "s", "/", "t")\n'
            "self.play(Write(eq))\n"
        )
        assert _morph_transitions(script)[2] == 1

    def test_a_change_of_scene_that_carries_something_over_is_not_one(self):
        """The book and the table leave, the velocity label becomes the
        "v = const" of the next scene: a morph, not a cut to empty."""
        script = wrap(
            "self.play(FadeOut(book), FadeOut(table))\n"
            "self.play(Create(probe), TransformMatchingTex(lbl_v, v_const))\n"
        )
        assert _morph_transitions(script)[2] == 0

    def test_fading_out_everything_on_screen(self):
        script = wrap(
            "self.play(*[FadeOut(m) for m in self.mobjects])\n"
            "c = Square()\n"
            "self.play(Create(c))\n"
        )
        assert _morph_transitions(script)[2] == 1

    def test_the_last_fade_of_the_video_is_not_a_clear(self):
        """Fading out at the very end is an ending, not a change of step."""
        script = wrap(
            "c = Square()\n"
            "self.play(Create(c))\n"
            "self.play(*[FadeOut(m) for m in self.mobjects])\n"
        )
        assert _morph_transitions(script)[2] == 0


class TestThePrompt:
    def test_without_the_layer_l8_still_says_clear_then_draw(self):
        plain = build_manim_system_prompt(True, "Kazakh")
        assert "first a\n    self.play(FadeOut(...))" in plain
        assert "TransformMatchingTex" not in plain

    def test_with_it_l8_says_morph(self):
        motion = build_manim_system_prompt(True, "Kazakh", motion=True)
        assert "NEVER CLEAR THE SCREEN" in motion
        assert "TransformMatchingTex(eq1, eq2)" in motion
        assert "ReplacementTransform(square, circle)" in motion
        assert "first a\n    self.play(FadeOut(...))" not in motion
