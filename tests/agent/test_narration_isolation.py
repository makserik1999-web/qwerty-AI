"""Narration must not hand an API key to model-written code.

run_manim_script builds a deliberately minimal environment for the render
subprocess - its own comment says "NO secrets, NO API keys, nothing the script
could exfiltrate" - because the script it executes was written by a language
model. Speech synthesis needs an Azure key, and the obvious way to add
narration would have been to put that key in there.

It is not there. The agent synthesises every line first and the renderer is
handed a directory of finished mp3 files, so PrerenderedService has no network
code to fall back on. These tests exist because that arrangement is invisible
from the outside: a narrated video looks identical whichever way the audio was
produced, so nothing but a test would notice the day someone "simplifies" it.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = REPO_ROOT / "agent" / "manim-mcp-server" / "src" / "manim_server.py"
SHIM = REPO_ROOT / "agent" / "manim-mcp-server" / "src" / "anyq_narration.py"
GUARD = REPO_ROOT / "agent" / "anyq" / "script_guard.py"


@pytest.fixture(scope="module")
def server_source() -> str:
    return SERVER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def shim_source() -> str:
    return SHIM.read_text(encoding="utf-8")


# ------------------------------------------------------------- no secrets ---


def test_the_render_environment_carries_no_credential(server_source):
    """Whatever safe_env gains later, it must not gain a key."""
    match = re.search(r"safe_env\s*=\s*\{(.*?)\n\s*\}", server_source, re.S)
    assert match, "safe_env literal not found - has run_manim_script moved?"
    body = match.group(1)

    for smell in ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL"):
        assert smell not in body.upper(), (
            f"{smell} appears in the render subprocess environment: {body.strip()[:200]}"
        )


def test_only_a_path_is_added_for_narration(server_source):
    """The manifest is a file path. A path the renderer can read is not a key."""
    assert 'safe_env["ANYQ_NARRATION_MANIFEST"] = narration_manifest' in server_source
    assert "AZURE" not in server_source.upper(), (
        "the render server should never mention Azure - it does not synthesise"
    )


def test_the_prerendered_service_cannot_reach_a_network(shim_source):
    """No HTTP client, no socket, no SDK - the isolation is structural."""
    tree = ast.parse(shim_source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"httpx", "requests", "urllib", "urllib3", "socket", "http",
                 "aiohttp", "azure"}
    assert not (imported & forbidden), (
        f"the shim imports something that can make a request: {imported & forbidden}"
    )


def test_a_missing_line_is_an_error_not_silence(shim_source):
    """A video that quietly drops one sentence is worse than one that fails.

    Nobody reviews a rendered video against the script it was meant to speak,
    so a missing line has to be loud or it will never be found.
    """
    assert "raise RuntimeError(" in shim_source
    assert "no pre-rendered audio for this line" in shim_source


# ---------------------------------------------------- the two validators ----


def _constant_set(source: str, name: str) -> set:
    match = re.search(rf"^{name} = \{{(.*?)\}}", source, re.S | re.M)
    assert match, f"{name} not found"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


class TestValidatorParity:
    """manim_server.py keeps its own copy of the safety rules on purpose.

    It re-validates rather than trusting whoever called it, which is right.
    The hazard is drift: a rule tightened in one copy and forgotten in the
    other reads as protection while providing none.
    """

    @pytest.mark.parametrize(
        "constant",
        ["_ALLOWED_IMPORT_MODULES", "_FORBIDDEN_NAMES", "_ALLOWED_DUNDER_ATTRS"],
    )
    def test_both_copies_agree(self, constant, server_source):
        guard = _constant_set(GUARD.read_text(encoding="utf-8"), constant)
        server = _constant_set(server_source, constant)

        assert guard == server, (
            f"{constant} differs between the two validators.\n"
            f"  only in script_guard: {sorted(guard - server)}\n"
            f"  only in manim_server: {sorted(server - guard)}"
        )


# ------------------------------------------------------- what is allowed ----


def test_the_shim_module_may_be_imported(agent_import_path):
    """It supplies VoiceoverScene, so a narrated script has to reach it."""
    from anyq.script_guard import _ALLOWED_IMPORT_MODULES

    assert "anyq_narration" in _ALLOWED_IMPORT_MODULES


def test_the_model_may_not_choose_the_voice(agent_import_path, validate_manim_script):
    """set_speech_service picks the voice, and the cache key already named one.

    A script that sets its own service would be served from a cache entry
    recorded against a different voice - and the mismatch is inaudible to
    everything except the person listening.
    """
    script = (
        "from manim import *\n"
        "from anyq_narration import VoiceoverScene\n\n"
        "class Demo(VoiceoverScene):\n"
        "    def construct(self):\n"
        "        self.set_speech_service(object())\n"
    )

    ok, reason = validate_manim_script(script)

    assert not ok
    assert "set_speech_service" in reason


def test_a_plain_narrated_script_is_accepted(agent_import_path, validate_manim_script):
    script = (
        "from manim import *\n"
        "from anyq_narration import VoiceoverScene\n\n"
        "class Demo(VoiceoverScene):\n"
        "    def construct(self):\n"
        '        with self.voiceover(text="Жер денелерді тартады.") as t:\n'
        "            self.play(FadeIn(Circle()), run_time=t.duration)\n"
    )

    ok, reason = validate_manim_script(script)

    assert ok, reason


# --------------------------------------------------------------- hashing ----


class TestLineKeys:
    """The agent and the renderer must agree on what identifies a line.

    manim-voiceover collapses whitespace before a service ever sees the text,
    so anything hashing it has to collapse the same way or every lookup misses.
    """

    def test_whitespace_does_not_change_the_key(self):
        import sys

        sys.path.insert(0, str(SHIM.parent))
        from anyq_narration import narration_key

        assert narration_key("Жер  денелерді\n тартады.") == \
            narration_key("Жер денелерді тартады.")

    def test_different_text_gets_a_different_key(self):
        import sys

        sys.path.insert(0, str(SHIM.parent))
        from anyq_narration import narration_key

        assert narration_key("бірінші сөйлем") != narration_key("екінші сөйлем")
