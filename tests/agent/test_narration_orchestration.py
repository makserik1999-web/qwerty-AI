"""Reading the spoken lines out of a script, and choosing who says them.

The manifest has to cover exactly what the rendered script will ask to speak.
If it misses a line the render raises; if it holds a line the script never
says, a paid synthesis was wasted. So extraction reads the code rather than
any separate list, and these tests pin the cases where "read the code" is less
obvious than it sounds.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "agent" / "manim-mcp-server" / "src"


@pytest.fixture(scope="module", autouse=True)
def _shim_on_path():
    if str(SHIM_DIR) not in sys.path:
        sys.path.insert(0, str(SHIM_DIR))


@pytest.fixture
def narration(agent_import_path):
    from anyq import narration as module

    return module


def _script(body: str) -> str:
    return (
        "from manim import *\n"
        "from anyq_narration import VoiceoverScene\n\n"
        "class Demo(VoiceoverScene):\n"
        "    def construct(self):\n" + body
    )


# ------------------------------------------------------------- extraction --


def test_a_spoken_line_is_found(narration):
    script = _script('        with self.voiceover(text="Жер тартады.") as t:\n'
                     "            self.play(FadeIn(Circle()), run_time=t.duration)\n")

    assert narration.extract_lines(script) == ["Жер тартады."]


def test_lines_keep_their_order(narration):
    script = _script(
        '        with self.voiceover(text="бірінші") as t:\n'
        "            self.play(FadeIn(Circle()), run_time=t.duration)\n"
        '        with self.voiceover(text="екінші") as t:\n'
        "            self.play(FadeOut(Circle()), run_time=t.duration)\n"
    )

    assert narration.extract_lines(script) == ["бірінші", "екінші"]


def test_a_repeated_line_is_synthesised_once(narration):
    """The manifest is keyed by text, so a second copy is a wasted API call."""
    script = _script(
        '        with self.voiceover(text="қайталанады") as t:\n'
        "            self.play(FadeIn(Circle()), run_time=t.duration)\n"
        '        with self.voiceover(text="қайталанады") as t:\n'
        "            self.play(FadeOut(Circle()), run_time=t.duration)\n"
    )

    assert narration.extract_lines(script) == ["қайталанады"]


def test_lines_differing_only_in_whitespace_are_one_line(narration):
    """manim-voiceover collapses whitespace before asking, so these collide."""
    script = _script(
        '        with self.voiceover(text="екі  сөз") as t:\n'
        "            self.play(FadeIn(Circle()), run_time=t.duration)\n"
        '        with self.voiceover(text="екі сөз") as t:\n'
        "            self.play(FadeOut(Circle()), run_time=t.duration)\n"
    )

    assert len(narration.extract_lines(script)) == 1


def test_a_positional_argument_is_read_too(narration):
    """The model does not always use the keyword."""
    script = _script('        with self.voiceover("позиция бойынша") as t:\n'
                     "            self.play(FadeIn(Circle()), run_time=t.duration)\n")

    assert narration.extract_lines(script) == ["позиция бойынша"]


def test_an_empty_line_is_skipped(narration):
    """Synthesising silence costs a request and returns nothing useful."""
    script = _script('        with self.voiceover(text="   ") as t:\n'
                     "            self.play(FadeIn(Circle()), run_time=t.duration)\n")

    assert narration.extract_lines(script) == []


def test_a_computed_line_is_skipped(narration):
    """Only literals can be synthesised ahead of the render.

    A line built at runtime cannot be known here, so it is left out - the
    renderer will raise on it, which is the intended loud failure rather than
    a video that silently drops a sentence.
    """
    script = _script('        with self.voiceover(text="а" + "б") as t:\n'
                     "            self.play(FadeIn(Circle()), run_time=t.duration)\n")

    assert narration.extract_lines(script) == []


def test_a_broken_script_yields_nothing(narration):
    assert narration.extract_lines("class Demo(:::") == []


def test_a_silent_script_yields_nothing(narration):
    script = _script("        self.play(FadeIn(Circle()))\n")

    assert narration.extract_lines(script) == []


# ----------------------------------------------------------------- voices --


class TestVoiceChoice:
    def test_both_kazakh_voices_are_reachable(self, narration):
        assert narration.voice_for("kk", "aigul") == "kk-KZ-AigulNeural"
        assert narration.voice_for("kk", "daulet") == "kk-KZ-DauletNeural"

    def test_other_languages_follow_the_same_choice(self, narration):
        """The setting names the Kazakh voices; the rest match on gender."""
        assert narration.voice_for("ru", "aigul") == "ru-RU-SvetlanaNeural"
        assert narration.voice_for("ru", "daulet") == "ru-RU-DmitryNeural"
        assert narration.voice_for("en", "aigul") == "en-US-AriaNeural"

    def test_an_unknown_language_has_no_voice(self, narration):
        """Rather than narrating Kazakh text with an English voice."""
        assert narration.voice_for("tr", "aigul") == ""
        assert narration.voice_for("", "aigul") == ""

    def test_an_unknown_choice_has_no_voice(self, narration):
        assert narration.voice_for("kk", "nonesuch") == ""


# ------------------------------------------------------------ degradation --


class TestNarrationNeverCostsTheVideo:
    """Every failure path renders silently instead of failing the request.

    A student who asked a question and got a silent animation has been served.
    One who got an error has not - and Azure's free tier ends at half a
    million characters a month, so this path will be reached.
    """

    async def test_no_credentials_means_silence(self, narration, monkeypatch):
        monkeypatch.setattr(narration, "AZURE_SPEECH_KEY", "")

        assert await narration.prepare("x", "kk") == ""

    async def test_an_unsupported_language_means_silence(self, narration, monkeypatch):
        monkeypatch.setattr(narration, "AZURE_SPEECH_KEY", "k")
        monkeypatch.setattr(narration, "AZURE_SPEECH_REGION", "r")

        assert await narration.prepare("x", "tr") == ""

    async def test_the_switch_being_off_means_silence(self, narration, monkeypatch):
        monkeypatch.setattr(narration, "NARRATION_ENABLED", False)

        assert await narration.prepare("x", "kk") == ""

    async def test_an_over_long_script_means_silence(self, narration, monkeypatch):
        """A cap on the whole job, not trust in the prompt's length guidance."""
        monkeypatch.setattr(narration, "AZURE_SPEECH_KEY", "k")
        monkeypatch.setattr(narration, "AZURE_SPEECH_REGION", "r")
        monkeypatch.setattr(narration, "NARRATION_ENABLED", True)

        long_line = "сөз " * 2000
        script = _script(f'        with self.voiceover(text="{long_line}") as t:\n'
                         "            self.play(FadeIn(Circle()), run_time=t.duration)\n")

        assert await narration.prepare(script, "kk") == ""

    async def test_a_refused_request_means_silence(self, narration, monkeypatch):
        """Azure returning 429 must not turn into a failed question."""
        monkeypatch.setattr(narration, "AZURE_SPEECH_KEY", "k")
        monkeypatch.setattr(narration, "AZURE_SPEECH_REGION", "r")
        monkeypatch.setattr(narration, "NARRATION_ENABLED", True)

        def boom(*a, **k):
            raise RuntimeError("azure tts 429: out of quota")

        monkeypatch.setattr(narration, "_synthesise_sync", boom)
        script = _script('        with self.voiceover(text="сөйлем") as t:\n'
                         "            self.play(FadeIn(Circle()), run_time=t.duration)\n")

        assert await narration.prepare(script, "kk") == ""


# ------------------------------------------------------- the base class ----


class TestTheNarratedBaseIsSupplied:
    """The model is told to subclass VoiceoverScene; forgetting is cheap to fix.

    Left alone, a forgotten base class fails at render with AttributeError on
    self.voiceover - a full repair round trip to add one line we already know.
    """

    def test_a_plain_scene_is_rewritten(self, agent_import_path):
        from anyq.script_guard import _ensure_narration_base

        out = _ensure_narration_base(
            "from manim import *\n\nclass Demo(Scene):\n    def construct(self):\n"
            "        pass\n"
        )

        assert "class Demo(VoiceoverScene):" in out
        assert "from anyq_narration import VoiceoverScene" in out

    def test_applying_it_twice_changes_nothing(self, agent_import_path):
        from anyq.script_guard import _ensure_narration_base

        once = _ensure_narration_base("from manim import *\n\nclass D(Scene):\n    pass\n")

        assert _ensure_narration_base(once) == once

    def test_the_result_still_passes_the_validator(self, agent_import_path,
                                                   validate_manim_script):
        from anyq.script_guard import _ensure_narration_base

        out = _ensure_narration_base("class D(Scene):\n    def construct(self):\n"
                                     "        pass\n")

        assert validate_manim_script(out)[0]

    def test_a_script_without_the_manim_import_still_gets_both(self, agent_import_path):
        from anyq.script_guard import _ensure_narration_base

        out = _ensure_narration_base("class D(Scene):\n    def construct(self):\n"
                                     "        pass\n")

        assert out.startswith("from manim import *\n")
        assert "from anyq_narration import VoiceoverScene" in out
