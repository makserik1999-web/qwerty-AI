#!/usr/bin/env bash
# Anyq refactor checks. Run from anywhere:  agent/check.sh
#
# Verifies that the anyq/* extraction did not change anything observable:
# module graph still imports, the re-exports agent_ws_client depends on are
# still reachable, the pure helpers still behave, and the Manim system prompt
# is still byte-for-byte what it was before the refactor.
set -u
cd "$(dirname "$0")"

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

# sha256 of build_manim_system_prompt(True, "Kazakh (kazak tili)") taken before
# the refactor started. The prompt must not move by a single byte.
EXPECTED_PROMPT_SHA256 = "0cf849266f9ae68e4081397abd3309eaa7ec0a002b5cbe79224fe99506fcb045"

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
import anyq.vision, anyq.render
print("  PASS  import anyq.{config,language,prompts,llm_client,script_guard,vision,render}")

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
check("_detect_language('hello') is None", _detect_language("hello"), None)
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
check("_friendly_failure_text('hello') falls back to the default language",
      _friendly_failure_text("hello"), _GENERIC_FAILURE_MESSAGES[DEFAULT_OUTPUT_LANGUAGE])

print("[script guard]")
from anyq.script_guard import _tex_contains_cyrillic, _contains_forbidden_manim
check("_tex_contains_cyrillic('MathTex(\"privet\")') is True",
      _tex_contains_cyrillic('MathTex("\u043f\u0440\u0438\u0432\u0435\u0442")'), True)
check("_tex_contains_cyrillic('MathTex(\"x^2\")') is False",
      _tex_contains_cyrillic('MathTex("x^2")'), False)
check("_contains_forbidden_manim('Checkmark()') is True",
      _contains_forbidden_manim("Checkmark()"), True)
check("_contains_forbidden_manim('Circle()') is False",
      _contains_forbidden_manim("Circle()"), False)

print("[render]")
import asyncio as _asyncio

import anyq.render as R


class _FakeTool:
    """Stands in for MCPTool: replies with a queued JSON payload per call."""

    _replies = []

    def __init__(self, *a, **k):
        pass

    async def call_mcp_tool(self, name, manim_code=None):
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

check_true("ScienceVideoState declares render_attempt",
           "render_attempt" in A.ScienceVideoState.__annotations__,
           repr(sorted(A.ScienceVideoState.__annotations__)))

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
