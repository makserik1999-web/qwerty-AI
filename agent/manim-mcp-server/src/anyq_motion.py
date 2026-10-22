"""The motion layer: what keeps a generated video from standing still.

Behind MOTION_LAYER=1. With it on, a generated script subclasses MotionScene
(`from anyq_narration import MotionScene`) instead of VoiceoverScene, and the
guard in anyq/script_guard.py makes sure it does. MotionScene IS the narrated
or the silent VoiceoverScene - whichever anyq_narration would have handed out -
with three things added:

1. A background layer: drifting particles, a slow "breath" of the backdrop, a
   progress bar along the top.
2. Idle motion: once a shape is on screen it floats on a small circle (1-2%
   of its size) and, if it is round, pulses. Every shape floats in step with
   every other - one phase, taken from the scene clock - so a diagram built
   from several shapes moves as one piece. Text and formulas never move -
   they have to be read - and neither does anything whose place means
   something next to another object: a line, an arrow, an axis, a graph, a
   dot marking a point (a dot only pulses, in place).
3. Active hold: while a sentence is spoken about a formula, the term being
   said lights up and an underline is drawn beneath the formula up to it.
   Word timings come from Azure's word boundaries, which the agent leaves in
   the manifest; without them the terms light up in turn, evenly across the
   rest of the sentence.

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
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

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

# Idle motion of shapes. A narrow range on purpose: shapes that fit together -
# a square inside a square - float in step, and only the difference between
# their amplitudes can pull them apart.
IDLE_SHARE = 0.015                     # of the shape's larger side
IDLE_MIN, IDLE_MAX = 0.02, 0.05        # units
IDLE_PERIOD = 4.2                      # seconds per circle
PULSE_SHARE = 0.018                    # of the size, for round shapes
PULSE_PERIOD = 2.6                     # seconds
IDLE_RAMP = 1.0                        # seconds to reach full amplitude
# A shape wider or taller than this share of the frame is a floor, a wall or a
# container, and a floor that bobs looks broken rather than alive.
IDLE_MAX_FRAME_SHARE = 0.6

# Active hold.
HOLD_MIN_SECONDS = 0.6     # less than this left of the sentence: not worth it
HOLD_FADE = 0.18           # seconds for a term to light up or go out
HOLD_MIN_TERM = 0.25       # a term lit for less than this is not lit at all
HOLD_SWEEP = 0.35          # seconds for the underline to reach the next term
HOLD_TAIL = 0.3            # the end of the sentence, spent fading back
UNDERLINE_GAP = 0.14       # below the formula


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


def smooth(x: float) -> float:
    """0 to 1 with no jolt at either end (smoothstep)."""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def idle_offset(t: float, tau: float, amp: float) -> Tuple[float, float]:
    """Where a floating shape is at scene time `t`, `tau` seconds after it
    started floating.

    A circle rather than a bob: the speed never drops to zero, so there is no
    moment in each cycle where the shape stands still. The phase is the scene
    clock's, not the shape's own, so two shapes that appeared at different
    moments still float in step - a square drawn inside another stays inside
    it. It eases out from the shape's own place over IDLE_RAMP, so nothing
    jumps when the motion begins.
    """
    ramp = smooth(tau / IDLE_RAMP)
    w = math.tau / IDLE_PERIOD
    return (amp * ramp * math.sin(w * t),
            amp * ramp * math.cos(w * t) * 0.8)


def idle_amplitude(size: float) -> float:
    """1.5% of a shape's size, kept between a visible and a calm amount."""
    return min(IDLE_MAX, max(IDLE_MIN, IDLE_SHARE * size))


def norm_word(word: str) -> str:
    """Lower case, letters and digits only - how two words are compared."""
    return "".join(ch for ch in (word or "").casefold() if ch.isalnum())


def words_match(term_word: str, spoken: str) -> bool:
    """Whether a spoken word is the word a term was announced with.

    Kazakh and Russian inflect: the script names the term "масса" and the
    narrator says "массаның", or "сила" and then "силу". So beyond an exact
    match, two words of three letters or more match when they share all but
    the last letter of the shorter one. Shorter words - a letter like "F" -
    must match exactly, or every "a" in a sentence would be the acceleration.
    """
    a, b = norm_word(term_word), norm_word(spoken)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter = min(len(a), len(b))
    if shorter < 3:
        return False
    common = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        common += 1
    return common >= max(3, shorter - 1)


def match_terms(term_words: Sequence[str],
                spoken: Sequence[Tuple[float, float, str]]) -> List[Optional[float]]:
    """When each term's word is said - its start time - or None if it is not.

    Searched in order, each term after the previous one's word, because a
    formula is read left to right and the "m" at the end of a sentence is not
    the "m" at its start.
    """
    times: List[Optional[float]] = []
    cursor = 0
    for wanted in term_words:
        found = None
        if wanted:
            for i in range(cursor, len(spoken)):
                if words_match(wanted, spoken[i][2]):
                    found, cursor = spoken[i][0], i + 1
                    break
        times.append(found)
    return times


def schedule(matched: Sequence[Optional[float]], start: float, end: float) -> List[float]:
    """When each term lights up, given the ones whose word was found.

    No word found: the terms take turns, evenly from `start` to `end`. Some
    found: those keep their word's moment and the rest are spread evenly
    between their neighbours. Never before `start` - a word said while the
    formula was still being written lights its term the moment the hold
    begins - never after `end`, and always in order.
    """
    n = len(matched)
    if n == 0:
        return []
    anchors = [(i, min(max(t, start), end)) for i, t in enumerate(matched) if t is not None]
    if not anchors:
        return [start + (end - start) * i / n for i in range(n)]

    # Fixed points: the start (as term -1), every anchor, the end (as term n).
    points = [(-1, start)] + anchors + [(n, end)]
    out = [start] * n
    for (i0, t0), (i1, t1) in zip(points, points[1:], strict=False):
        if 0 <= i0 < n:
            out[i0] = t0
        for k in range(i0 + 1, i1):
            out[k] = t0 + (t1 - t0) * (k - i0) / (i1 - i0)
    for k in range(1, n):
        out[k] = max(out[k], out[k - 1])
    return out


# Parts of a formula that are its punctuation rather than one of its terms.
_OPERATORS = frozenset({
    "=", "+", "-", "/", "\\cdot", "\\times", "\\div", "\\pm", "\\mp", "(", ")",
    "[", "]", ",", ".", ":", ";", "<", ">", "\\le", "\\ge", "\\leq", "\\geq",
    "\\neq", "\\approx", "\\sim", "\\equiv", "\\Rightarrow", "\\rightarrow",
    "\\to", "\\implies", "\\Leftrightarrow", "\\quad", "\\qquad", "\\,",
    "\\;", "\\!", "&", "\\\\", "\\left(", "\\right)", "\\left[", "\\right]",
    "",
})


def is_operator(tex: str) -> bool:
    return re.sub(r"[\s{}]", "", tex or "") in _OPERATORS


_RELATION_RE = re.compile(r"=|<|>|\\(?:le|ge|leq|geq|neq|approx|equiv|sim|propto)(?![A-Za-z])")


def states_something(tex: str) -> bool:
    """Whether a formula says something - has an = or another relation.

    What a sentence is "about" when a block shows a formula. A bare "c", an
    "a + b" under a side or a "c^2" inside a square is a label, and a label
    lit up and underlined would draw the eye to the wrong place.
    """
    return bool(_RELATION_RE.search(tex or ""))


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
    import numpy as np
    from manim import (
        AnnularSector,
        Arc,
        Circle,
        CoordinateSystem,
        DecimalNumber,
        Dot,
        Ellipse,
        Line,
        MarkupText,
        NumberLine,
        Paragraph,
        ParametricFunction,
        Rectangle,
        SingleStringMathTex,
        Text,
        VGroup,
        VMobject,
        config,
    )
    from manim.utils.color import ManimColor

    import anyq_narration as narration_shim

    manifest: Dict[str, Any] = {}
    if manifest_path:
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    audio_root = Path(manifest_path).parent if manifest_path else None
    amber = ManimColor(AMBER).to_rgba()

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

    def line_words(text: str) -> List[Tuple[float, float, str]]:
        """When each word of a line is said, from the manifest; [] if unknown."""
        raw = (manifest.get("words") or {}).get(narration_shim.narration_key(text)) or []
        out = []
        for item in raw:
            try:
                out.append((float(item[0]), float(item[1]), str(item[2])))
            except (TypeError, ValueError, IndexError):
                continue
        return out

    def formula_terms(formula: Any) -> List[Any]:
        """The parts of a formula that are terms, left to right.

        MathTex("F", "=", "m", "a") has one part per string, and = is not a
        term. A formula written as one string has one part; it is then
        followed as a whole.
        """
        parts = list(formula.submobjects)
        if len(parts) > 1 and all(hasattr(p, "tex_string") for p in parts):
            terms = [p for p in parts if not is_operator(p.tex_string)
                     and any(m.has_points() for m in p.get_family())]
            if terms:
                return terms
        return [formula]

    class _Block:
        """One voiceover block, while it plays."""

        def __init__(self, text: str, tracker: Any, on_screen: set) -> None:
            self.text = text
            self.tracker = tracker
            self.seen = on_screen
            self.new_formulas: List[Any] = []
            self.explicit: Optional[Tuple[Any, List[str]]] = None

    def formulas_on_screen(mobjects: Sequence[Any]) -> List[Any]:
        """Formulas at the top level, or directly inside a top-level group."""
        found = []
        for mob in mobjects:
            if isinstance(mob, SingleStringMathTex):
                found.append(mob)
            elif type(mob) is VGroup:
                found.extend(m for m in mob.submobjects if isinstance(m, SingleStringMathTex))
        return found

    # Anything with words or numbers in it: it has to be read, so it stays put.
    text_like = (Text, MarkupText, Paragraph, SingleStringMathTex, DecimalNumber)
    # Things whose place means something next to another object: an axis and
    # what is plotted on it.
    anchored = (CoordinateSystem, NumberLine, ParametricFunction)
    round_shapes = (Circle, Ellipse, Dot)

    def may_float(mob: Any, frame_w: float, frame_h: float) -> bool:
        """Whether a top-level mobject may float. Conservative on purpose:
        a label left behind by its shape looks worse than a shape at rest."""
        if not isinstance(mob, VMobject):
            return False
        if isinstance(mob, Line):
            return False  # lines and arrows connect things
        if isinstance(mob, Arc) and not isinstance(mob, (Circle, AnnularSector)):
            return False  # an angle mark belongs to its vertex
        family = mob.get_family()
        if not any(m.has_points() for m in family):
            return False
        if any(isinstance(m, text_like) or isinstance(m, anchored) for m in family):
            return False
        if mob.get_family_updaters():
            return False  # the script moves it itself
        if mob.width > IDLE_MAX_FRAME_SHARE * frame_w or mob.height > IDLE_MAX_FRAME_SHARE * frame_h:
            return False
        return True

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

            if getattr(self, "_anyq_hold", None) is not None:
                self._anyq_hold_tick(t)

        # ------------------------------------------------------------ idle
        def play(self, *args: Any, **kwargs: Any) -> None:
            super().play(*args, **kwargs)
            self._anyq_after_play()

        def _anyq_after_play(self) -> None:
            """Whatever a play put on screen, and may float, starts to."""
            fw, fh = self._anyq_frame
            for mob in list(self.mobjects):
                if getattr(mob, "_anyq_idle", None) is None and may_float(mob, fw, fh):
                    self._anyq_start_idle(mob)
            block = getattr(self, "_anyq_block", None)
            if block is not None:
                for formula in formulas_on_screen(self.mobjects):
                    if id(formula) not in block.seen:
                        block.seen.add(id(formula))
                        tex = " ".join(getattr(formula, "tex_strings", None)
                                       or [getattr(formula, "tex_string", "")])
                        if states_something(tex):
                            block.new_formulas.append(formula)

        def _anyq_start_idle(self, mob: Any) -> None:
            now = self._anyq_time()
            # The state lives on the mobject, not in the updater: a .copy() of
            # a floating shape copies the updater function by reference, and
            # must carry its own state with it.
            mob._anyq_idle = {
                "t0": now,
                "last": now,
                # A dot marks a point; it pulses where it is.
                "amp": 0.0 if isinstance(mob, Dot) else idle_amplitude(max(mob.width, mob.height)),
                "pulse": PULSE_SHARE if isinstance(mob, round_shapes) else 0.0,
                "applied": np.zeros(3),
                "scale": 1.0,
            }
            scene = self
            frame_dt = 1.0 / float(config.frame_rate)

            def idle(m: Any, dt: float) -> None:
                st = getattr(m, "_anyq_idle", None)
                if st is None:
                    return
                t = scene._anyq_time()
                tau = t - st["t0"]
                ox, oy = idle_offset(t, tau, st["amp"])
                offset = np.array([ox, oy, 0.0])
                scale = 1.0 + st["pulse"] * smooth(tau / IDLE_RAMP) \
                    * math.sin(math.tau * tau / PULSE_PERIOD)
                if t - st["last"] > 2.5 * frame_dt:
                    # Back from an animation of this shape - manim suspends a
                    # mobject's updaters while it is being animated - so its
                    # place is now the animation's. Carry on from there rather
                    # than jump back to where the circle has got to.
                    st["applied"], st["scale"], st["last"] = offset, scale, t
                    return
                m.shift(offset - st["applied"])
                if st["pulse"]:
                    m.scale(scale / st["scale"])
                st["applied"], st["scale"], st["last"] = offset, scale, t

            mob.add_updater(idle)

        # ------------------------------------------------------------ hold
        @contextmanager
        def voiceover(self, text: Any = None, **kwargs: Any) -> Iterator[Any]:
            with super().voiceover(text=text, **kwargs) as tracker:
                on_screen = {id(f) for f in formulas_on_screen(self.mobjects)}
                self._anyq_block = _Block(str(text or ""), tracker, on_screen)
                self._anyq_hold = None
                yield tracker
                # Still inside the block: the rest of the sentence is about to
                # be waited out, after every animation of the block - which is
                # when the hold runs, with nothing else moving the formula.
                self._anyq_begin_hold()
            self._anyq_end_hold()
            self._anyq_block = None

        def read_formula(self, formula: Any, *words: Any) -> None:
            """Light up `formula`'s terms as the narrator says them.

            Called inside a voiceover block, once the formula is on screen.
            `words` are the sentence's words for its terms, left to right -
            operators such as = and + are not terms. It returns at once and
            takes effect in the rest of the sentence, after the block's
            animations. Without it, a formula the block puts on screen is
            followed anyway, with the terms taking turns.
            """
            block = getattr(self, "_anyq_block", None)
            if block is not None:
                block.explicit = (formula, [str(w) for w in words])

        def _anyq_begin_hold(self) -> None:
            block = self._anyq_block
            if block is None:
                return
            if block.explicit is not None:
                formula, words = block.explicit
            elif block.new_formulas:
                formula, words = block.new_formulas[-1], []
            else:
                return
            if not any(formula in m.get_family() for m in self.mobjects):
                return  # gone again before the sentence ended
            now = self._anyq_time()
            end = float(getattr(block.tracker, "end_t", now)) - HOLD_TAIL
            if end - now < HOLD_MIN_SECONDS:
                return

            terms = formula_terms(formula)
            start_t = float(getattr(block.tracker, "start_t", now))
            spoken = [(start_t + a, start_t + b, w) for a, b, w in line_words(block.text)]
            if words:
                wanted = (list(words) + [""] * len(terms))[:len(terms)]
            else:
                # Without words from the script a term can still match when
                # the sentence says it as written - "F", "v" - which is rare
                # in speech, so this mostly falls back to taking turns.
                wanted = [re.sub(r"[^A-Za-z0-9]", "", getattr(p, "tex_string", ""))
                          for p in terms]
            matched = match_terms(wanted, spoken) if spoken else [None] * len(terms)
            ons = schedule(matched, now, end)

            saved = []
            for term in terms:
                saved.append([(m, np.array(m.fill_rgbas, copy=True),
                               np.array(m.stroke_rgbas, copy=True))
                              for m in term.get_family() if m.has_points()])
            y = formula.get_bottom()[1] - UNDERLINE_GAP
            x0 = formula.get_left()[0]
            underline = VMobject(stroke_color=AMBER, stroke_width=4)
            underline.set_points_as_corners([[x0, y, 0], [x0 + 1e-3, y, 0]])
            underline._anyq_idle = False  # it marks the formula; it does not float
            self.add(underline)
            self._anyq_hold = {
                "ons": ons, "end": end, "saved": saved, "underline": underline,
                "x0": x0, "y": y, "rights": [term.get_right()[0] for term in terms],
            }
            self._anyq_hold_tick(now)

        def _anyq_hold_tick(self, t: float) -> None:
            hold = self._anyq_hold
            ons, end = hold["ons"], hold["end"]
            n = len(ons)
            for i in range(n):
                off = ons[i + 1] if i + 1 < n else end
                if off - ons[i] < HOLD_MIN_TERM:
                    # Its word was said while the formula was still being
                    # written; a flash of a few frames would only flicker.
                    # The underline passes under it all the same.
                    continue
                w = smooth((t - ons[i]) / HOLD_FADE) * (1.0 - smooth((t - off) / HOLD_FADE))
                for m, fill, stroke in hold["saved"][i]:
                    # Colour only, alpha kept: the formula never moves.
                    if len(fill):
                        target = np.tile(amber, (len(fill), 1))
                        target[:, 3] = fill[:, 3]
                        m.fill_rgbas = fill + (target - fill) * w
                    if len(stroke):
                        target = np.tile(amber, (len(stroke), 1))
                        target[:, 3] = stroke[:, 3]
                        m.stroke_rgbas = stroke + (target - stroke) * w

            # The underline reaches the right edge of the term being said.
            current = max((i for i in range(n) if ons[i] <= t), default=-1)
            x0, y = hold["x0"], hold["y"]
            x = x0 + 1e-3
            if current >= 0:
                prev = hold["rights"][current - 1] if current > 0 else x0
                x = prev + (hold["rights"][current] - prev) * smooth((t - ons[current]) / HOLD_SWEEP)
            hold["underline"].set_points_as_corners([[x0, y, 0], [max(x, x0 + 1e-3), y, 0]])
            hold["underline"].set_stroke(opacity=1.0 - smooth((t - end) / HOLD_TAIL))

        def _anyq_end_hold(self) -> None:
            hold, self._anyq_hold = getattr(self, "_anyq_hold", None), None
            if hold is None:
                return
            for members in hold["saved"]:
                for m, fill, stroke in members:
                    m.fill_rgbas = fill
                    m.stroke_rgbas = stroke
            self.remove(hold["underline"])

    MotionScene.__name__ = "MotionScene"
    MotionScene.__qualname__ = "MotionScene"
    return MotionScene
