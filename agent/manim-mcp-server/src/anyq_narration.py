"""The name `VoiceoverScene` that a generated script imports.

Two things live here, and both exist because of decisions made elsewhere in
this repo.

FIRST: the render subprocess gets no API key. run_manim_script builds a
deliberately minimal environment - "NO secrets, NO API keys, nothing the
script could exfiltrate" - because the script it is about to execute was
written by a language model. Handing that process an Azure key to synthesise
speech would quietly undo that, so it does not get one. Instead the agent,
which legitimately holds the key, synthesises every line first and leaves the
audio on disk; PrerenderedService below only ever reads those files. It has
no network code at all, so the property is structural rather than a promise.

SECOND: narration is a toggle, and the same generated script has to serve
both settings. Rather than maintaining two prompts and two script shapes, the
script always writes `with self.voiceover(...)` blocks and this module decides
what that means: with a manifest it is real speech, without one it is a silent
stand-in that still paces the animation. One script, one cache entry, and the
toggle costs nothing at generation time.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

# Where the agent left the synthesised audio. Empty means "render silent".
_MANIFEST_PATH = (os.environ.get("ANYQ_NARRATION_MANIFEST") or "").strip()

# Reading pace for the silent variant, in characters per second. Roughly the
# rate the Azure voices actually speak at (measured: 11.9 for Kazakh, 11.3 for
# Russian), so switching narration off changes the sound and not the pacing.
_SILENT_CHARS_PER_SEC = 12.0
_SILENT_MIN_SEC = 1.2
_SILENT_MAX_SEC = 12.0


def normalise_line(text: str) -> str:
    """Collapse whitespace exactly the way manim-voiceover does.

    SpeechService._wrap_generate_from_text runs `" ".join(text.split())` before
    it ever reaches a service, so anything that hashes the line has to do the
    same or the agent and the renderer will disagree about what was spoken.
    """
    return " ".join((text or "").split())


def narration_key(text: str) -> str:
    """The manifest key for one spoken line."""
    return hashlib.sha256(normalise_line(text).encode("utf-8")).hexdigest()


class _SilentTracker:
    """Stands in for the real tracker so `run_time=tracker.duration` works.

    `start_t`/`end_t` mirror the real VoiceoverTracker so that remaining time
    is measured against the scene clock rather than assumed. It used to report
    the full duration however much of the block had already played, which was
    harmless only while every animation was stretched to fill the block.
    """

    def __init__(self, duration: float, scene: Any = None) -> None:
        self.duration = duration
        self._scene = scene
        self.start_t = float(getattr(scene.renderer, "time", 0.0) or 0.0) if scene else 0.0
        self.end_t = self.start_t + duration
        # Real trackers expose these; scripts occasionally read them.
        self.data: Dict[str, Any] = {}

    def get_remaining_duration(self, buff: float = 0.0) -> float:
        if self._scene is None:
            return self.duration
        now = float(getattr(self._scene.renderer, "time", 0.0) or 0.0)
        return max(self.end_t - now + buff, 0.0)


def _build_narrated_scene() -> type:
    """The narrated base class, built on first use.

    Deferred rather than defined at import time so that `narration_key` above
    can be imported by anything: the agent needs the same hashing rule to write
    the manifest, and importing this module for one pure function should not
    require manim to be installed.
    """
    from manim_voiceover import VoiceoverScene as _RealVoiceoverScene
    from manim_voiceover.services.base import SpeechService

    class PrerenderedService(SpeechService):
        """Serves audio the agent already synthesised. Cannot reach a network.

        A missing line raises instead of falling back to silence: a video that
        quietly loses one sentence of its explanation is worse than one that
        fails and gets retried, because nobody would notice the first.
        """

        def __init__(self, manifest_path: str, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            raw = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            self._root = Path(manifest_path).parent
            self._index: Dict[str, str] = raw["lines"]
            self._voice: str = raw.get("voice", "")

        def generate_from_text(
            self,
            text: str,
            cache_dir: Optional[Any] = None,
            path: Optional[Any] = None,
            **kwargs: Any,
        ) -> Dict[str, Any]:
            key = narration_key(text)
            source = self._index.get(key)
            if source is None:
                raise RuntimeError(
                    "no pre-rendered audio for this line - the script asked to "
                    f"speak text that was not synthesised: {normalise_line(text)[:80]!r}"
                )

            target_dir = Path(cache_dir or self.cache_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = str(path) if path else f"{key}.mp3"
            shutil.copyfile(self._root / source, target_dir / filename)

            return {
                "input_text": text,
                "input_data": {
                    "input_text": normalise_line(text),
                    "service": "anyq-prerendered",
                    "config": {"voice": self._voice},
                },
                "original_audio": filename,
            }

    class NarratedScene(_RealVoiceoverScene):  # type: ignore[misc]
        """What the generated script inherits from when narration is on.

        The speech service is wired here rather than in the script because the
        script is model-written: letting it choose the service would also let
        it choose the voice, which would silently disagree with the voice the
        cache key was computed from.
        """

        def setup(self) -> None:
            super().setup()
            self.set_speech_service(PrerenderedService(_MANIFEST_PATH))

    return NarratedScene


def _build_silent_scene() -> type:
    """The same script with the sound taken out, paced the same way."""
    from manim import Scene, config

    class SilentScene(Scene):
        @contextmanager
        def voiceover(self, text: str = "", **kwargs: Any) -> Iterator[_SilentTracker]:
            spoken = normalise_line(text)
            seconds = len(spoken) / _SILENT_CHARS_PER_SEC
            seconds = min(_SILENT_MAX_SEC, max(_SILENT_MIN_SEC, seconds))
            tracker = _SilentTracker(seconds, self)
            try:
                yield tracker
            finally:
                # Hold the frame for whatever the sentence had left, the way
                # manim-voiceover's own wait_for_voiceover does on the narrated
                # path. Without it a silent render is only as long as its
                # animations - which was invisible while every animation was
                # stretched to fill its block, and became the difference
                # between a 90-second video and a 20-second one the moment
                # they stopped being.
                remaining = tracker.get_remaining_duration()
                if remaining > 1 / config["frame_rate"]:
                    self.wait(remaining)

        def set_speech_service(self, *args: Any, **kwargs: Any) -> None:
            """Accepted and ignored, so one script renders either way."""
            return None

    return SilentScene


def __getattr__(name: str) -> Any:
    """`from anyq_narration import VoiceoverScene`, resolved on demand."""
    if name == "VoiceoverScene":
        return _build_narrated_scene() if _MANIFEST_PATH else _build_silent_scene()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
