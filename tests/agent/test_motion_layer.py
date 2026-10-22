"""The motion layer (MOTION_LAYER=1): the scene every generated video stands on.

What has to hold, in order of how badly it would go wrong:

1. With the flag off nothing changes - the prompt is byte for byte the old
   one (scripts/check.sh pins its hash) and a script keeps VoiceoverScene.
2. With it on, the scene the renderer runs subclasses MotionScene, whatever
   base the model wrote, and a script that cannot be made to is stopped
   rather than shipped without the layer.
3. The layer's own arithmetic - the progress bar, the narration it is
   measured from - behaves at the edges.

The scene itself needs manim and is exercised by rendering, inside the agent
image; these tests need neither.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "agent",
              REPO_ROOT / "tests" / "stubs",
              REPO_ROOT / "agent" / "manim-mcp-server" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import anyq_motion  # noqa: E402
from anyq.nodes import script as nodes_script  # noqa: E402
from anyq.prompts import (  # noqa: E402
    _L8_CLEAR_THEN_DRAW,
    _L8_MORPH,
    _MOTION_RULES,
    build_manim_system_prompt,
)
from anyq.script_guard import (  # noqa: E402
    _ensure_motion_base,
    _ensure_narration_base,
    _inherits_motion_scene,
    validate_manim_script,
)


def _script(base: str = "VoiceoverScene", narration: str = "Сөйлем.") -> str:
    return (
        "from manim import *\n"
        f"from anyq_narration import {base}\n\n"
        f"class Demo({base}):\n"
        "    def construct(self):\n"
        "        t = Text('x')\n"
        f'        with self.voiceover(text="{narration}") as tracker:\n'
        "            self.play(FadeIn(t), run_time=0.5)\n"
    )


# ----------------------------------------------------------------- the prompt


class TestThePrompt:
    def test_without_the_flag_it_never_mentions_the_layer(self):
        prompt = build_manim_system_prompt(True, "Kazakh")
        assert "MotionScene" not in prompt
        assert "=== MOTION" not in prompt

    def test_with_it_only_the_base_class_l8_and_the_motion_rules_change(self):
        """Everything else the prompt says - the layout rules, the narration
        rules, the length budget - is the same text either way."""
        plain = build_manim_system_prompt(True, "Kazakh", "19. budget", portrait=True)
        motion = build_manim_system_prompt(True, "Kazakh", "19. budget", portrait=True,
                                           motion=True)

        expected = (plain.replace("VoiceoverScene", "MotionScene")
                    .replace(_L8_CLEAR_THEN_DRAW, _L8_MORPH) + _MOTION_RULES)
        assert motion == expected

    def test_it_says_the_background_is_already_drawn(self):
        motion = build_manim_system_prompt(True, "Kazakh", motion=True)
        assert "class Demo(MotionScene):" in motion
        assert "from anyq_narration import MotionScene" in motion
        assert "Do NOT draw a background" in motion


# ------------------------------------------------------------------ the guard


class TestTheBaseClass:
    @pytest.mark.parametrize("base", ["Scene", "VoiceoverScene", "MovingCameraScene",
                                      "ThreeDScene", "ZoomedScene"])
    def test_every_base_a_model_writes_becomes_motion_scene(self, base):
        script = _ensure_motion_base(_script(base))

        assert "class Demo(MotionScene):" in script
        assert _inherits_motion_scene(script)
        assert validate_manim_script(script) == (True, "")

    def test_the_narration_import_is_replaced_not_doubled(self):
        script = _ensure_motion_base(_script("VoiceoverScene"))

        assert script.count("from anyq_narration import") == 1
        assert "from anyq_narration import MotionScene" in script

    def test_a_script_with_no_narration_import_gets_one(self):
        bare = "from manim import *\n\nclass Demo(Scene):\n    def construct(self):\n        pass\n"
        script = _ensure_motion_base(_ensure_narration_base(bare))

        assert _inherits_motion_scene(script)

    def test_it_is_idempotent(self):
        once = _ensure_motion_base(_script("Scene"))
        assert _ensure_motion_base(once) == once

    def test_helper_classes_are_left_alone(self):
        script = _script("VoiceoverScene").replace(
            "class Demo(", "class Marker(VGroup):\n    pass\n\nclass Demo(")
        script = _ensure_motion_base(script)

        assert "class Marker(VGroup):" in script
        assert _inherits_motion_scene(script)


class TestTheCheck:
    def test_a_plain_scene_is_not_a_motion_scene(self):
        assert not _inherits_motion_scene(_script("VoiceoverScene"))

    def test_the_import_must_be_there(self):
        script = _ensure_motion_base(_script()).replace(
            "from anyq_narration import MotionScene\n", "")
        assert not _inherits_motion_scene(script)

    def test_a_renamed_import_does_not_count(self):
        """`import MotionScene as X` then `class Demo(MotionScene)` would be
        some other MotionScene - or a NameError."""
        script = _ensure_motion_base(_script()).replace(
            "import MotionScene", "import MotionScene as M")
        assert not _inherits_motion_scene(script)

    def test_a_scene_on_a_base_the_guard_does_not_know_fails_it(self):
        """The guard rewrites the bases it knows; the check is what catches
        one it does not."""
        script = _ensure_motion_base(_script() + "\nclass Other(GraphScene):\n    pass\n")

        assert "class Other(GraphScene):" in script
        assert not _inherits_motion_scene(script)

    def test_no_scene_at_all_fails_it(self):
        assert not _inherits_motion_scene("from anyq_narration import MotionScene\n")

    def test_broken_code_fails_it(self):
        assert not _inherits_motion_scene("class Demo(MotionScene:\n")


# ------------------------------------------------------------------- the node


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


# Inside the "short" budget (430-500 characters), so no length rewrite is asked
# for and the only call the node makes is the one that writes the script.
_NARRATION = "Бұл сөйлем видеоның ұзындығын қысқа аралыққа сыйғызу үшін жазылды. " * 7


@pytest.fixture
def node(monkeypatch):
    """generate_manim_script with the model and the toolchain faked."""
    calls = []

    async def chat(messages, **kwargs):
        calls.append(messages)
        return _Reply(_script("VoiceoverScene", _NARRATION.strip()))

    monkeypatch.setattr(nodes_script, "_llm_chat", chat)
    monkeypatch.setattr(nodes_script, "_latex_toolchain_healthy", lambda: True)
    monkeypatch.setattr(nodes_script, "_ensure_unicode_font", lambda s: s)
    return calls


class TestTheNode:
    async def test_without_the_flag_the_script_keeps_its_base(self, node, monkeypatch):
        monkeypatch.setattr(nodes_script, "MOTION_LAYER", False)

        out = await nodes_script.generate_manim_script(
            {"user_message": "q", "video_length": "short", "output_language": "kk"})

        assert "class Demo(VoiceoverScene):" in out["manim_script"]
        assert "MotionScene" not in node[0][0].content

    async def test_with_it_the_script_becomes_a_motion_scene(self, node, monkeypatch):
        monkeypatch.setattr(nodes_script, "MOTION_LAYER", True)

        out = await nodes_script.generate_manim_script(
            {"user_message": "q", "video_length": "short", "output_language": "kk"})

        assert _inherits_motion_scene(out["manim_script"])
        assert "class Demo(MotionScene):" in node[0][0].content

    async def test_a_script_that_cannot_be_fixed_is_stopped(self, node, monkeypatch):
        monkeypatch.setattr(nodes_script, "MOTION_LAYER", True)
        monkeypatch.setattr(nodes_script, "_ensure_motion_base", lambda s: s)

        with pytest.raises(RuntimeError, match="MotionScene"):
            await nodes_script.generate_manim_script(
                {"user_message": "q", "video_length": "short", "output_language": "kk"})


# --------------------------------------------------------- the layer's numbers


class TestTheProgressBar:
    def test_it_starts_empty_and_follows_the_clock(self):
        assert anyq_motion.progress(0, 40) == 0
        assert anyq_motion.progress(20, 40) == pytest.approx(0.5)

    def test_it_never_runs_backwards_and_never_overflows(self):
        values = [anyq_motion.progress(t / 10, 40) for t in range(0, 2000)]
        assert values == sorted(values)
        assert max(values) < 1.0

    def test_running_long_it_slows_down_instead_of_stopping(self):
        """The total is a guess. A video longer than guessed keeps moving the
        bar - the alternative is a full bar with ten seconds still to go."""
        at_end = anyq_motion.progress(40, 40)
        later = anyq_motion.progress(48, 40)
        assert 0.92 < at_end < later < 1.0

    def test_no_total_means_no_bar(self):
        assert anyq_motion.progress(5, 0) == 0.0


class TestTheNarrationItIsMeasuredFrom:
    def test_lines_come_in_the_order_they_are_spoken_with_repeats(self):
        source = (
            "class Demo(MotionScene):\n"
            "    def construct(self):\n"
            "        with self.voiceover(text='бір') as t:\n"
            "            pass\n"
            "        with self.voiceover('екі') as t:\n"
            "            pass\n"
            "        with self.voiceover(text='бір') as t:\n"
            "            pass\n"
            "        with self.voiceover(text=f'{x}') as t:\n"
            "            pass\n"
        )
        assert anyq_motion.spoken_lines(source) == ["бір", "екі", "бір"]

    def test_broken_source_is_no_lines_not_a_crash(self):
        assert anyq_motion.spoken_lines("def (") == []

    def test_the_total_is_the_sentences_plus_a_margin(self):
        assert anyq_motion.estimate_total([10.0, 20.0]) == pytest.approx(30 * 1.04 + 0.8)
        assert anyq_motion.estimate_total([]) > 0


# ------------------------------------------------------------- idle motion


class TestIdleMotion:
    def test_it_starts_where_the_shape_is(self):
        """Whatever the scene clock says, a shape that has just appeared is
        where the script put it."""
        for t in (0.0, 3.3, 17.0):
            assert anyq_motion.idle_offset(t, 0.0, 0.05) == (0.0, 0.0)

    def test_it_stays_within_its_amplitude(self):
        amp = 0.05
        for i in range(400):
            x, y = anyq_motion.idle_offset(i / 30, i / 30, amp)
            assert (x * x + (y / 0.8) ** 2) ** 0.5 <= amp + 1e-9

    def test_shapes_that_appeared_at_different_times_float_in_step(self):
        """A square drawn inside another, a play later, stays inside it."""
        t = 20.0
        first = anyq_motion.idle_offset(t, t - 2.0, 0.04)
        later = anyq_motion.idle_offset(t, t - 9.0, 0.04)
        assert first == pytest.approx(later)

    def test_once_going_it_never_stands_still(self):
        """A bob up and down stops twice a cycle; a circle never does - and a
        stop is exactly what freezedetect would find."""
        amp, dt = 0.05, 1 / 30
        start = anyq_motion.IDLE_RAMP
        speeds = []
        for i in range(300):
            t = start + i * dt
            a = anyq_motion.idle_offset(t, t, amp)
            b = anyq_motion.idle_offset(t + dt, t + dt, amp)
            speeds.append(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 / dt)
        assert min(speeds) > 0.5 * max(speeds)

    def test_its_size_follows_the_shape_within_bounds(self):
        assert anyq_motion.idle_amplitude(2.0) == pytest.approx(0.03)
        assert anyq_motion.idle_amplitude(0.1) == anyq_motion.IDLE_MIN
        assert anyq_motion.idle_amplitude(50.0) == anyq_motion.IDLE_MAX

    def test_the_prompt_says_not_to_animate_it_by_hand(self):
        motion = build_manim_system_prompt(True, "Kazakh", motion=True)
        assert "M2." in motion and "stay perfectly" in motion
