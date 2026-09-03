"""A slide deck a teacher can open and edit.

The frames are chosen by scene detection rather than at fixed intervals. A
Manim animation is a sequence of distinct states - a formula appears, a
diagram moves, a caption replaces another - and ffmpeg's scene filter finds
exactly those boundaries. Evenly-spaced frames would land mid-transition and
produce a deck of half-drawn shapes; that fallback is kept only for videos
where detection finds too little to work with.

Deliberately not done here, and why:

- **The quiz slide** the plan sketches needs a model to write the questions.
  The exporter has no API key and should not have one: it runs untrusted
  encodes, and a key inside that blast radius is a bad trade for three
  questions a teacher can write faster than they can check.
- **Formulas re-rendered as images.** They are already in the frames, at
  render quality. A second rendering path would be a second thing to get
  wrong in Kazakh.
"""

import re
from pathlib import Path
from typing import Any, Callable, Dict, List

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from app import ffmpeg

# Not Noto Sans, which the plan suggested: a deck is opened on someone else's
# computer, and Arial is the widest font that actually carries the Kazakh
# letters. A missing font silently substitutes and ruins the layout.
FONT = "Arial"

BACKGROUND = RGBColor(0x11, 0x14, 0x1B)
TEXT = RGBColor(0xF2, 0xF4, 0xF8)
MUTED = RGBColor(0x9A, 0xA3, 0xB2)
ACCENT = RGBColor(0x6C, 0x5C, 0xE7)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

MIN_STEPS = 3
MAX_STEPS = 8
# Below this the scene filter is picking up noise rather than real changes.
SCENE_THRESHOLD = 0.25


def _paragraphs(text: str) -> List[str]:
    """The explanation split into the steps it already has.

    Markdown paragraphs, with list items kept whole: the educator text is
    written as prose with bullet points, and splitting on sentences would cut
    a formula in half.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    return [re.sub(r"\s+", " ", b) for b in blocks]


def _detect_scene_times(source: Path, duration: float, wanted: int) -> List[float]:
    """Timestamps where the picture changes substantially."""
    try:
        raw = ffmpeg.scene_change_times(source, SCENE_THRESHOLD)
    except ffmpeg.FfmpegError as exc:
        print(f"[pptx] scene detection failed, falling back to even spacing: {exc}")
        raw = []

    # Drop anything in the first moment: the opening fade is not a step.
    times = [t for t in raw if 0.3 < t < duration - 0.3]

    if len(times) < MIN_STEPS:
        step = duration / (wanted + 1)
        return [step * (i + 1) for i in range(wanted)]

    if len(times) > wanted:
        # Keep an even spread rather than the first N, so the deck covers the
        # whole explanation instead of its opening.
        stride = len(times) / wanted
        times = [times[int(i * stride)] for i in range(wanted)]
    return times


def _blank_slide(deck: Presentation):
    slide = deck.slides.add_slide(deck.slide_layouts[6])  # 6 is the blank layout
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = BACKGROUND
    return slide


def _textbox(slide, left, top, width, height, text, size, color=TEXT, bold=False):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    run = paragraph.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = FONT
    return box


def run_pptx(source: Path, destination: Path, params: Dict[str, Any],
             max_bytes: int, on_progress: Callable[[int], None]) -> Dict[str, Any]:
    title = str(params.get("source_title") or "Anyq").strip()
    body = str(params.get("educator_text") or "")
    steps = _paragraphs(body)
    wanted = max(MIN_STEPS, min(MAX_STEPS, len(steps) or MIN_STEPS))

    duration = ffmpeg.probe_duration(source)
    if duration <= 0:
        raise RuntimeError("could not read the video duration")

    on_progress(15)
    times = _detect_scene_times(source, duration, wanted)

    deck = Presentation()
    deck.slide_width = SLIDE_W
    deck.slide_height = SLIDE_H

    # --- title ------------------------------------------------------------
    slide = _blank_slide(deck)
    _textbox(slide, Inches(1), Inches(2.4), Inches(11.3), Inches(2),
             title, 40, TEXT, bold=True)
    _textbox(slide, Inches(1), Inches(4.4), Inches(11.3), Inches(0.8),
             "Anyq", 18, ACCENT)

    # --- one slide per step -----------------------------------------------
    frames_dir = destination.parent / f"{destination.stem}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        for index, at in enumerate(times):
            on_progress(20 + int(60 * (index + 1) / max(len(times), 1)))
            frame_path = frames_dir / f"step_{index:02d}.png"
            try:
                ffmpeg.extract_frame(source, frame_path, at)
            except ffmpeg.FfmpegError as exc:
                print(f"[pptx] frame at {at:.1f}s failed, skipping: {exc}")
                continue

            slide = _blank_slide(deck)
            # Picture left, words right: a teacher reads the slide while the
            # class looks at the picture, so they must not overlap.
            slide.shapes.add_picture(
                str(frame_path), Inches(0.5), Inches(1.4), width=Inches(7.2)
            )
            _textbox(slide, Inches(0.5), Inches(0.4), Inches(12.3), Inches(0.8),
                     f"{index + 1}. {title}", 20, MUTED)

            step_text = steps[index] if index < len(steps) else ""
            if step_text:
                _textbox(slide, Inches(8.1), Inches(1.6), Inches(4.7), Inches(4.5),
                         step_text, 16)

            # The full paragraph goes into the notes: the slide shows a
            # summary, the presenter needs the whole thing.
            if step_text:
                notes = slide.notes_slide.notes_text_frame
                notes.text = step_text

        # --- closing ------------------------------------------------------
        slide = _blank_slide(deck)
        _textbox(slide, Inches(1), Inches(3.2), Inches(11.3), Inches(1.2),
                 title, 28, TEXT, bold=True)
        _textbox(slide, Inches(1), Inches(4.4), Inches(11.3), Inches(0.8),
                 "The full animation is in Anyq", 16, MUTED)

        deck.save(str(destination))
    finally:
        for leftover in frames_dir.glob("*.png"):
            leftover.unlink(missing_ok=True)
        frames_dir.rmdir()

    size = destination.stat().st_size
    return {
        "bytes": size,
        "slides": len(deck.slides),
        "over_budget": size > max_bytes,
    }
