#!/usr/bin/env bash
# Anyq refactor checks. Run from anywhere:  scripts/check.sh
#
# Verifies that the anyq/* extraction did not change anything observable:
# module graph still imports, the re-exports agent_ws_client depends on are
# still reachable, the pure helpers still behave, and the Manim system prompt
# is still byte-for-byte what it was before the refactor.
set -u
# The checks import the agent package, so run from agent/.
cd "$(dirname "$0")/../agent"

export PYTHONIOENCODING=utf-8

# spoon-ai-sdk is a heavy runtime dep and is not installed everywhere. When it
# is missing we stub it, so the checks still exercise the real import graph of
# our own modules instead of being skipped. The stub is written outside the
# repo and is used ONLY when the real package is absent.
if ! python -c "import spoon_ai" >/dev/null 2>&1; then
  STUB_DIR="$(mktemp -d)"
  trap 'rm -rf "$STUB_DIR"' EXIT
  mkdir -p "$STUB_DIR/spoon_ai/tools"
  : > "$STUB_DIR/spoon_ai/__init__.py"
  : > "$STUB_DIR/spoon_ai/tools/__init__.py"
  cat > "$STUB_DIR/spoon_ai/graph.py" <<'STUB_EOF'
END = "END"


class StateGraph:
    def __init__(self, *a, **k):
        self.nodes = {}
        self.edges = []

    def add_node(self, name, fn):
        self.nodes[name] = fn

    def add_parallel_group(self, *a, **k):
        pass

    def set_entry_point(self, name):
        self.entry = name

    def add_edge(self, a, b):
        self.edges.append((a, b))

    def add_conditional_edges(self, *a, **k):
        self.edges.append(a)

    def compile(self):
        return self
STUB_EOF
  cat > "$STUB_DIR/spoon_ai/llm.py" <<'STUB_EOF'
class LLMManager:
    def __init__(self, *a, **k):
        pass
STUB_EOF
  cat > "$STUB_DIR/spoon_ai/schema.py" <<'STUB_EOF'
class Message:
    def __init__(self, role=None, content=None):
        self.role = role
        self.content = content
STUB_EOF
  cat > "$STUB_DIR/spoon_ai/tools/mcp_tool.py" <<'STUB_EOF'
class MCPTool:
    def __init__(self, *a, **k):
        pass
STUB_EOF
  export PYTHONPATH="$STUB_DIR${PYTHONPATH:+:$PYTHONPATH}"
  echo "NOTE: spoon_ai is not installed here - using a minimal stub for the import checks."
fi

python - <<'PYCHK'
import hashlib
import sys

sys.path.insert(0, ".")

# sha256 of build_manim_system_prompt(True, "Kazakh (kazak tili)").
#
# This guard exists so a refactor cannot change the prompt by accident, and
# it did its job: the value below is the SECOND one. It moved on purpose
# when narration was added - the model now has to write a spoken sentence
# alongside each on-screen caption, which is a behaviour change and not a
# refactor. Before 0cf84926... it was the pre-refactor prompt.
#
# THIRD value, moved on purpose again: the prompt used to require
# run_time=tracker.duration on every animation and to swap captions with
# Transform. Both were wrong on screen - the first stretched every fade across
# a whole spoken sentence, the second spent that sentence morphing one word's
# letters into another's. Rules 15, 16, L1, L2 and L8 now say the opposite,
# which is a behaviour change and not a refactor. Previous: 740244fe3570...
EXPECTED_PROMPT_SHA256 = "1239fa501d3d3e849f7c6dd942ed9bc24d051bbd41a3620f478f2f78dc0f097c"

failures = []


def check(name, got, expected):
    ok = got == expected
    print(("  PASS  " if ok else "  FAIL  ") + name)
    if not ok:
        print("          expected %r, got %r" % (expected, got))
        failures.append(name)
    return ok


def check_true(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name)
    if not cond:
        if detail:
            print("          " + detail)
        failures.append(name)
    return cond


print("[imports]")
import science_manim_graph_agent as A
print("  PASS  import science_manim_graph_agent")
import agent_ws_client as W
print("  PASS  import agent_ws_client")
import anyq.config, anyq.language, anyq.prompts
import anyq.llm_client, anyq.script_guard
import anyq.vision, anyq.render, anyq.telemetry
import anyq.nodes as N
print("  PASS  import anyq.{config,language,prompts,llm_client,script_guard,vision,render,telemetry,nodes}")
check_true("_SIMPLE_ARITH_RE was removed from anyq.nodes", not hasattr(N, "_SIMPLE_ARITH_RE"))

print("[re-exports from science_manim_graph_agent]")
check_true("app is importable", hasattr(A, "app"))
check_true("run_once is importable", hasattr(A, "run_once"))
check_true("ScienceVideoState is importable", hasattr(A, "ScienceVideoState"))
check_true("_latex_toolchain_healthy is importable", hasattr(A, "_latex_toolchain_healthy"))
check_true("_detect_language is importable", hasattr(A, "_detect_language"))
check_true("DEFAULT_OUTPUT_LANGUAGE is importable", hasattr(A, "DEFAULT_OUTPUT_LANGUAGE"))
from science_manim_graph_agent import app  # noqa: F401
from science_manim_graph_agent import _detect_language, DEFAULT_OUTPUT_LANGUAGE
print("  PASS  from science_manim_graph_agent import app, _detect_language, DEFAULT_OUTPUT_LANGUAGE")

print("[language]")
check("_detect_language('privet') == 'ru'", _detect_language("\u043f\u0440\u0438\u0432\u0435\u0442"), "ru")
check("_detect_language('salem') == 'kk'", _detect_language("\u0441\u04d9\u043b\u0435\u043c"), "kk")
# Latin text used to return None, and the caller then fell back to the
# default language - Kazakh - so "what is gravity" was answered in Kazakh.
# That was a bug, not an invariant; these two lines now assert the fix.
check("_detect_language('hello') == 'en'", _detect_language("hello"), "en")
check("a bare formula still has no language", _detect_language("E = mc^2"), None)
check("DEFAULT_OUTPUT_LANGUAGE == 'kk'", DEFAULT_OUTPUT_LANGUAGE, "kk")

from anyq.language import _pick_unicode_font, _friendly_failure_text, _GENERIC_FAILURE_MESSAGES
font = _pick_unicode_font()
check_true("_pick_unicode_font() returns a non-empty string",
           isinstance(font, str) and font.strip() != "", "got %r" % (font,))

# agent_ws_client falls back to Kazakh when language resolution raises. If the
# re-export chain silently breaks, every user gets Kazakh and nothing errors -
# so assert the Russian branch is actually reached.
check("_friendly_failure_text('privet') is the Russian message",
      _friendly_failure_text("\u043f\u0440\u0438\u0432\u0435\u0442"), _GENERIC_FAILURE_MESSAGES["ru"])
check("_friendly_failure_text('salem') is the Kazakh message",
      _friendly_failure_text("\u0441\u04d9\u043b\u0435\u043c"), _GENERIC_FAILURE_MESSAGES["kk"])
check("_friendly_failure_text('hello') is the English message",
      _friendly_failure_text("hello"), _GENERIC_FAILURE_MESSAGES["en"])
check("text with no language still falls back to the default",
      _friendly_failure_text("E = mc^2"), _GENERIC_FAILURE_MESSAGES[DEFAULT_OUTPUT_LANGUAGE])

print("[script guard]")
from anyq.script_guard import (
    _tex_contains_cyrillic,
    _contains_forbidden_manim,
    validate_manim_script,
)
check("_tex_contains_cyrillic('MathTex(\"privet\")') is True",
      _tex_contains_cyrillic('MathTex("\u043f\u0440\u0438\u0432\u0435\u0442")'), True)
check("_tex_contains_cyrillic('MathTex(\"x^2\")') is False",
      _tex_contains_cyrillic('MathTex("x^2")'), False)
check("_contains_forbidden_manim('Checkmark()') is True",
      _contains_forbidden_manim("Checkmark()"), True)
check("_contains_forbidden_manim('Circle()') is False",
      _contains_forbidden_manim("Circle()"), False)

print("[safety]")
_VALID_OK = "from manim import *\n\nclass Demo(Scene):\n    def construct(self):\n        t = Text(\"x\")\n        self.play(Write(t))\n"
_VALID_BAD = {
    "import_os": "import os\nclass X(Scene):\n    def construct(self):\n        pass\n",
    "from_subprocess": "from subprocess import run\nclass X(Scene):\n    def construct(self):\n        pass\n",
    "eval_call": "from manim import *\nclass X(Scene):\n    def construct(self):\n        eval('1+1')\n",
    "module_print": "from manim import *\nprint('hi')\nclass X(Scene):\n    def construct(self):\n        pass\n",
    "open_call": "from manim import *\nclass X(Scene):\n    def construct(self):\n        f = open('/etc/passwd')\n",
    "socket_import": "from manim import *\nimport socket\nclass X(Scene):\n    def construct(self):\n        pass\n",
    "dunder_attr": "from manim import *\nclass X(Scene):\n    def construct(self):\n        y = getattr('a', '__class__')\n",
}
_ok, _reason = validate_manim_script(_VALID_OK)
check_true("validate_manim_script accepts a plain Manim scene", _ok, _reason)
for _name, _script in _VALID_BAD.items():
    _ok, _reason = validate_manim_script(_script)
    check_true("validate_manim_script rejects %s" % _name, not _ok, _reason)

print("[render]")
import asyncio as _asyncio

import anyq.render as R


class _FakeTool:
    """Stands in for MCPTool: replies with a queued JSON payload per call."""

    _replies = []

    def __init__(self, *a, **k):
        pass

    async def call_mcp_tool(self, name, manim_code=None, narration_manifest="",
                            quality="l"):
        # narration_manifest is accepted and ignored: these checks cover the
        # repair loop, and synthesising speech would need a live Azure key.
        # quality likewise - it selects a manim render profile, and nothing
        # here renders. It is in the signature because render_video now passes
        # it, and a stub that did not accept it would fail every check with a
        # TypeError rather than telling anyone what changed.
        _FakeTool.last_quality = quality
        return _FakeTool._replies.pop(0)


class _FakeResp:
    content = "from manim import *"


async def _fake_llm_chat(messages, **kwargs):
    return _FakeResp()


_saved = (R.MCPTool, R.MANIM_MCP_SERVER_SCRIPT, R._llm_chat)
R.MCPTool = _FakeTool
R.MANIM_MCP_SERVER_SCRIPT = "/nonexistent/manim_server.py"
R._llm_chat = _fake_llm_chat
OK = '{"status": "ok", "video_path": "/tmp/v.mp4"}'
BAD = '{"status": "error", "stderr": "boom"}'
try:
    _FakeTool._replies = [OK]
    res = _asyncio.run(R.render_video({"manim_script": "from manim import *"}))
    check("render_attempt == 1 when the first render succeeds", res.get("render_attempt"), 1)
    check("video_path is returned on success", res.get("video_path"), "/tmp/v.mp4")
    check("render_error is empty on success", res.get("render_error"), "")

    _FakeTool._replies = [BAD, OK]
    res = _asyncio.run(R.render_video({"manim_script": "from manim import *"}))
    check("render_attempt == 2 when the repaired script succeeds", res.get("render_attempt"), 2)

    _FakeTool._replies = [BAD] * (R._RENDER_REPAIR_ATTEMPTS + 1)
    res = _asyncio.run(R.render_video({"manim_script": "from manim import *"}))
    check_true("render_error is set when every attempt fails",
               bool(res.get("render_error")), repr(res))
    check("video_path is empty when every attempt fails", res.get("video_path"), "")
    check_true("render_attempt is absent when every attempt fails",
               "render_attempt" not in res, repr(res))
finally:
    R.MCPTool, R.MANIM_MCP_SERVER_SCRIPT, R._llm_chat = _saved

check_true("ScienceVideoState no longer declares render_attempt",
           "render_attempt" not in A.ScienceVideoState.__annotations__,
           repr(sorted(A.ScienceVideoState.__annotations__)))

print("[telemetry]")
import json as _json
import os as _os
import shutil as _shutil
import tempfile as _tempfile

import anyq.telemetry as T

_tmp_dir = _tempfile.mkdtemp()
_saved_path = T.ANYQ_TELEMETRY_PATH
try:
    # A run whose fields are fully populated: the written line must round-trip
    # as valid JSON with exactly the documented key set.
    _log_path = _os.path.join(_tmp_dir, "sub", "runs.jsonl")
    T.ANYQ_TELEMETRY_PATH = _log_path
    T.new_run("req-1", "hello world")
    T.record(
        language="ru",
        is_science=True,
        subject="physics",
        video_needed=True,
        educator_text_len=42,
        script_len=100,
        render_attempt=1,
        render_ok=True,
        render_error_tail="",
        status="complete",
    )
    T.note_guard_rewrite("forbidden", True)
    T.note_guard_rewrite("latex_objects", False)
    T.write()

    check_true("telemetry.write() created the log file and its directory",
               _os.path.exists(_log_path))
    with open(_log_path, "r", encoding="utf-8") as f:
        _line = f.readline()
    _entry = _json.loads(_line)
    _expected_keys = {
        "run_id", "timestamp", "request_id", "user_message_sha256",
        "user_message_len", "language", "is_science", "subject",
        "video_needed", "educator_text_len", "script_len", "guard_rewrites",
        "render_attempt", "render_ok", "render_error_tail", "duration_ms",
        "status", "error_type",
    }
    check_true("telemetry line has the full documented key set",
               set(_entry.keys()) == _expected_keys, repr(sorted(_entry.keys())))
    check("telemetry request_id round-trips", _entry.get("request_id"), "req-1")
    check("telemetry guard_rewrites round-trips", _entry.get("guard_rewrites"), [
        {"guard": "forbidden", "fired": True, "fixed": True},
        {"guard": "latex_objects", "fired": True, "fixed": False},
    ])
    check("telemetry status round-trips", _entry.get("status"), "complete")

    # A run that never calls record(): defaults must still produce a complete,
    # valid line rather than a missing key or a crash.
    T.new_run(None, "")
    T.write()
    with open(_log_path, "r", encoding="utf-8") as f:
        _lines = f.readlines()
    _entry2 = _json.loads(_lines[-1])
    check_true("a bare new_run()+write() still has the full key set",
               set(_entry2.keys()) == _expected_keys, repr(sorted(_entry2.keys())))
    check("an unrecorded run defaults to status=error", _entry2.get("status"), "error")

    # Unwritable path (a file sits where the log directory would need to be
    # created): write() must swallow the failure, not raise.
    _blocker = _os.path.join(_tmp_dir, "blocker")
    with open(_blocker, "w", encoding="utf-8") as f:
        f.write("x")
    T.ANYQ_TELEMETRY_PATH = _os.path.join(_blocker, "x.jsonl")
    T.new_run("req-2", "x")
    try:
        T.write()
        check_true("telemetry.write() does not raise on an unwritable path", True)
    except Exception as e:
        check_true("telemetry.write() does not raise on an unwritable path", False, repr(e))
finally:
    T.ANYQ_TELEMETRY_PATH = _saved_path
    _shutil.rmtree(_tmp_dir, ignore_errors=True)

print("[prompt integrity]")
from anyq.prompts import build_manim_system_prompt
prompt = build_manim_system_prompt(True, "Kazakh (\u049b\u0430\u0437\u0430\u049b \u0442\u0456\u043b\u0456)")
digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
check("sha256(build_manim_system_prompt(True, kk)) unchanged", digest, EXPECTED_PROMPT_SHA256)

print("")
if failures:
    print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("ALL CHECKS PASSED")
PYCHK
