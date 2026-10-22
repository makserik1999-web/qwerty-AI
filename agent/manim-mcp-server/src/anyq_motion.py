"""The motion layer: what keeps a generated video from standing still.

Behind MOTION_LAYER=1. With it on, a generated script subclasses MotionScene
(`from anyq_narration import MotionScene`) instead of VoiceoverScene, and the
guard in anyq/script_guard.py makes sure it does. MotionScene IS the narrated
or the silent VoiceoverScene - whichever anyq_narration would have handed out -
with a background layer added: drifting particles, a slow "breath" of the
backdrop, a progress bar along the top.

The layer is drawn by the camera before the scene's own mobjects on every
frame, and is never one of them. So nothing a script does to self.mobjects -
FadeOut(*self.mobjects), self.clear(), bring_to_back - can fade it, remove it
or put something behind it.

Everything in it is a function of self.renderer.time, recomputed on every
frame. That is the point: the video used to stand still for three quarters of
its length - each sentence a frozen frame while the teacher talked - and a
frame drawn from the clock cannot freeze. It is also why the layer is wired as
a scene updater: manim then knows no wait is static, and draws every frame of
every pause instead of repeating one.

Why the measurements matter: ffmpeg's freezedetect at -66 dB calls a 0.3 s
window frozen when the frame changes by less than about a seventh of a grey
level on average. The two reference videos in reference/manim_showcase never
drop below it (their quietest window is right at the threshold); our own
videos were below it 76% of the time. The particle settings below are what it
takes to stay above it on a frame where nothing else moves.

The pure helpers at the top need no manim, so the agent's tests can import
them; the scene class is built on first use, like the ones in anyq_narration.
"""

from __future__ import annotations

import ast
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Sequence

# Colours sampled from the reference frames (reference/manim_showcase).
BACKGROUND = "#131E39"
PARTICLE = "#8596B5"
TRACK = "#344058"
AMBER = "#F0B54B"

# ---------------------------------------------------------------- particles
# Per 14.2 x 8 units of frame (the landscape frame); a portrait frame gets the
# same density. Measured on a frame where nothing else moves, as freezedetect
# sees it (the motion over a 0.3 s window against its threshold):
#     80 particles, radius 0.018-0.05, opacity 0.22-0.6     0.67 - frozen
#     the same, half again as fast                          0.73 - frozen
#     80 particles, radius 0.025-0.06, opacity 0.3-0.7      1.22
# Speed hardly matters - in 0.3 s a particle already moves further than its
# own width - so it is size, brightness and count. These settings are the
# third row with more particles, for a margin over the threshold.
PARTICLES_PER_LANDSCAPE_FRAME = 92
PARTICLE_RADIUS = (0.025, 0.06)
PARTICLE_SPEED = (0.16, 0.34)        # units per second
PARTICLE_OPACITY = (0.3, 0.7)
PARTICLE_TWINKLE_PERIOD = (2.5, 5.5)  # seconds

# The breath: the whole backdrop slowly lightens and darkens again. Even,
# across the frame - a glow made of rings showed every ring as a step.
BREATH = "#1B2B55"
BREATH_OPACITY = 0.6
BREATH_PERIOD = 10.0                  # seconds


# ---------------------------------------------------------------- pure helpers

def progress(t: float, total: float) -> float:
    """How full the bar is at `t` seconds, 0..1, never quite reaching 1 early.

    The total is an estimate made before the first frame (estimate_total), and
    a bar that hits the end ten seconds before the video does is worse than
    one that slows down: past 92% it eases towards the end instead of
    stopping there.
    """
    if total <= 0:
        return 0.0
    knee = 0.92 * total
    if t <= knee:
        return max(0.0, t / total)
    return 0.92 + 0.075 * (1.0 - math.exp(-(t - knee) / (0.15 * total)))


def spoken_lines(source: str) -> List[str]:
    """Every literal `self.voiceover(text=...)` line, in order, repeats kept.

    The script's own source is the only place the whole narration is written
    down before the render starts, and the progress bar needs its length.
    """
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return []
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "voiceover":
            text = None
            for kw in node.keywords:
                if kw.arg == "text" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    text = kw.value.value
            if text is None and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                text = node.args[0].value
            if text and text.strip():
                calls.append((node.lineno, node.col_offset, text))
    return [text for _, _, text in sorted(calls)]


def estimate_total(durations: Sequence[float]) -> float:
    """The video's length from its sentences, before it is rendered.

    Each voiceover block lasts as long as its sentence, so the sentences are
    nearly the whole video; the rest is animations outside any block, which
    the small margin stands for.
    """
    return sum(durations) * 1.04 + 0.8 if durations else 45.0


# ---------------------------------------------------------------- the scene

def build_motion_scene(base: type, manifest_path: str) -> type:
    """MotionScene on top of `base` (the narrated or the silent scene)."""
    from manim import Dot, Line, Rectangle, VGroup, VMobject, config

    import anyq_narration as narration_shim

    manifest: Dict[str, Any] = {}
    if manifest_path:
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    audio_root = Path(manifest_path).parent if manifest_path else None

    def line_duration(text: str) -> float:
        """How long one sentence will be spoken: its audio, or the silent pace."""
        key = narration_shim.narration_key(text)
        source = (manifest.get("lines") or {}).get(key)
        if source and audio_root is not None:
            try:
                from mutagen.mp3 import MP3

                return float(MP3(str(audio_root / source)).info.length)
            except Exception:  # noqa: BLE001 - an estimate is all this needs
                pass
        seconds = len(narration_shim.normalise_line(text)) / narration_shim._SILENT_CHARS_PER_SEC
        return min(narration_shim._SILENT_MAX_SEC, max(narration_shim._SILENT_MIN_SEC, seconds))

    class MotionScene(base):  # type: ignore[misc, valid-type]
        """What a generated script inherits from under MOTION_LAYER=1."""

        def setup(self) -> None:
            super().setup()
            self._anyq_frame = (float(config.frame_width), float(config.frame_height))
            self._anyq_total = self._anyq_estimate_total()
            self._anyq_layer = self._anyq_build_layer()

            # Drawn first on every frame, under everything, by the camera
            # itself - not added to the scene (see the module docstring).
            camera = self.renderer.camera
            capture = camera.capture_mobjects

            def capture_with_layer(mobjects: Any, **kwargs: Any) -> None:
                capture([self._anyq_layer, *mobjects], **kwargs)

            camera.capture_mobjects = capture_with_layer
            self.add_updater(self._anyq_tick)
            self._anyq_tick(0.0)

        def get_moving_and_static_mobjects(self, animations: Any) -> Any:
            """Everything is redrawn on every frame.

            Manim paints the mobjects that do not move once, into a still
            image, and draws only the moving ones over it. With a layer that
            changes on every frame underneath, that still image would hold
            the layer as it was when the animation began - and the live layer
            would be drawn on top of the "still" mobjects. Same order, nothing
            cached.
            """
            moving, static = super().get_moving_and_static_mobjects(animations)
            return [*static, *moving], []

        def _anyq_estimate_total(self) -> float:
            try:
                import inspect

                source = Path(inspect.getfile(type(self))).read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001 - the bar then just guesses
                return estimate_total([])
            return estimate_total([line_duration(t) for t in spoken_lines(source)])

        def _anyq_build_layer(self) -> Any:
            fw, fh = self._anyq_frame
            # Seeded: the same script renders the same video twice.
            rng = random.Random(20261022)

            breath = Rectangle(width=fw + 0.4, height=fh + 0.4, stroke_width=0)
            breath.set_fill(BREATH, opacity=0.0)

            count = round(PARTICLES_PER_LANDSCAPE_FRAME * (fw * fh) / (14.222 * 8.0))
            particles = VGroup()
            self._anyq_particles: List[Dict[str, float]] = []
            for _ in range(count):
                angle = rng.uniform(0, math.tau)
                speed = rng.uniform(*PARTICLE_SPEED)
                self._anyq_particles.append({
                    "x": rng.uniform(-fw / 2, fw / 2),
                    "y": rng.uniform(-fh / 2, fh / 2),
                    "vx": speed * math.cos(angle),
                    "vy": speed * math.sin(angle),
                    "wobble": rng.uniform(0.05, 0.18),
                    "wobble_w": math.tau / rng.uniform(5.0, 11.0),
                    "phase": rng.uniform(0, math.tau),
                    "opacity": rng.uniform(*PARTICLE_OPACITY),
                    "twinkle_w": math.tau / rng.uniform(*PARTICLE_TWINKLE_PERIOD),
                })
                particles.add(Dot(radius=rng.uniform(*PARTICLE_RADIUS), color=PARTICLE,
                                  stroke_width=0))

            left, right = -fw / 2 + 0.35, fw / 2 - 0.35
            y = fh / 2 - 0.16
            track = Line([left, y, 0], [right, y, 0], color=TRACK, stroke_width=3)
            bar = VMobject(stroke_color=AMBER, stroke_width=3.5)
            bar.set_points_as_corners([[left, y, 0], [left + 1e-3, y, 0]])
            self._anyq_bar = (bar, left, right, y)
            return VGroup(breath, particles, track, bar)

        def _anyq_time(self) -> float:
            return float(getattr(self.renderer, "time", 0.0) or 0.0)

        def _anyq_tick(self, dt: float) -> None:
            t = self._anyq_time()
            fw, fh = self._anyq_frame
            breath, particles, _, _ = self._anyq_layer.submobjects

            # Particles: a straight drift with a slow wobble, wrapping round
            # just outside the frame so nobody sees one jump.
            margin = 0.3
            span_x, span_y = fw + 2 * margin, fh + 2 * margin
            for dot, p in zip(particles.submobjects, self._anyq_particles, strict=True):
                wob = p["wobble"] * math.sin(p["wobble_w"] * t + p["phase"])
                x = (p["x"] + p["vx"] * t + wob + fw / 2 + margin) % span_x - fw / 2 - margin
                y = (p["y"] + p["vy"] * t - wob + fh / 2 + margin) % span_y - fh / 2 - margin
                dot.move_to([x, y, 0])
                twinkle = 0.65 + 0.35 * math.sin(p["twinkle_w"] * t + p["phase"])
                dot.set_fill(opacity=p["opacity"] * twinkle)

            breath.set_fill(opacity=BREATH_OPACITY * 0.5
                            * (1.0 - math.cos(math.tau * t / BREATH_PERIOD)))

            bar, left, right, y = self._anyq_bar
            x = left + (right - left) * progress(t, self._anyq_total)
            bar.set_points_as_corners([[left, y, 0], [max(x, left + 1e-3), y, 0]])

    MotionScene.__name__ = "MotionScene"
    MotionScene.__qualname__ = "MotionScene"
    return MotionScene
