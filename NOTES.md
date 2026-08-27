# Anyq refactoring notes

Log of the `agent/` refactoring into the `anyq/` package. One section per task.
Rules in `PROJECT_MEMORY.md`: no behaviour change, no renames, comments kept
verbatim, bugs recorded here instead of fixed.

Checks: `agent/check.sh` (run it from anywhere; it cd's to `agent/`).

---

## Prompt integrity log

sha256 of `build_manim_system_prompt(True, "Kazakh (қазақ тілі)")`:

| when | sha256 | 
|---|---|
| baseline, before Task 2 | `0cf849266f9ae68e4081397abd3309eaa7ec0a002b5cbe79224fe99506fcb045` |
| after Task 2 | `0cf849266f9ae68e4081397abd3309eaa7ec0a002b5cbe79224fe99506fcb045` |
| after Task 3 | `0cf849266f9ae68e4081397abd3309eaa7ec0a002b5cbe79224fe99506fcb045` |
| after Task 4 | `0cf849266f9ae68e4081397abd3309eaa7ec0a002b5cbe79224fe99506fcb045` |

The value is pinned in `agent/check.sh` as `EXPECTED_PROMPT_SHA256`, so every
run re-verifies it.

---

## Task 1 - config, prompts, language (commit `b302210`)

Created `agent/anyq/`: `__init__.py`, `config.py`, `prompts.py`, `language.py`.

Moved:

- **`anyq/config.py`** - all 16 `os.getenv` reads from both entry modules
  (`_LLM_RETRIES`, `_LLM_RETRY_BASE_DELAY`, `DEFAULT_OUTPUT_LANGUAGE`,
  `MANIM_TEXT_FONT`, `MANIM_ALLOW_LATEX`, `_RENDER_REPAIR_ATTEMPTS`,
  `MANIM_MCP_SERVER_SCRIPT`, `MANIM_MCP_PYTHON`, `MANIM_EXECUTABLE`,
  `GEMINI_API_KEY`, `GEMINI_VISION_MODEL`, `DOC_SNIPPET_MODE`,
  `DEFAULT_WS_URL`, `RECONNECT_DELAY_SEC`, `WS_PING_INTERVAL_SEC`,
  `WS_PING_TIMEOUT_SEC`) plus `load_dotenv()` in its original `try/except`.
- **`anyq/prompts.py`** - `MANIM_API_REFERENCE`,
  `build_manim_system_prompt(allow_latex, language_name)`, the three rewrite
  system prompts and the render-repair prompt.
- **`anyq/language.py`** - `_LANGUAGE_NAMES`, `_KAZAKH_ONLY_CHARS`,
  `_detect_language`, `_resolve_output_language`, `_language_name`,
  `_FONT_PREFERENCES`, `_cached_font`, `_pick_unicode_font`,
  `_REJECT_MESSAGES`, `_RENDER_FALLBACK_MESSAGES`, `_GENERIC_FAILURE_MESSAGES`,
  `_friendly_failure_text`.

Both large prompt blocks were spliced line-by-line from the original file by a
script rather than retyped; equality was asserted against the original values.

Not moved, and why:

- `_cached_font` lives in `anyq/language.py` but is deliberately **not**
  re-exported into `science_manim_graph_agent` - a plain `from ... import
  _cached_font` would snapshot `None` and never see the cache fill.
- `_TRANSIENT_LLM_MARKERS` / `_is_transient_llm_error` / `_llm_chat` - out of
  Task 1's scope (moved in Task 2).
- The inline system prompts of `classify_intent` and `educator_answer` - the
  task named only the generate/rewrite/repair prompts.
- The `DOC_SNIPPET_MODE` stub Manim script inside `generate_manim_script` - a
  text block, but not named in the task.
- `os.environ.copy()` in `_latex_toolchain_healthy` - not a named env read.
- `_DATA_URL_RE` and the mime->extension map in `agent_ws_client.py`.

---

## Task 2 - llm client and script guard

Created:

- **`anyq/llm_client.py`** - `llm = LLMManager()`, `_TRANSIENT_LLM_MARKERS`,
  `_is_transient_llm_error`, `_llm_chat`. Moved verbatim (42 lines, asserted
  identical to the pre-task-2 source).
- **`anyq/script_guard.py`** - `_CODE_FENCE_RE`, `_strip_code_fences`,
  `_safe_json_loads`, `_TEX_CALL_RE`, `_tex_contains_cyrillic`,
  `_ensure_unicode_font`, `_contains_latex_objects`,
  `_contains_forbidden_manim`, `_latex_is_available`,
  `_latex_toolchain_healthy`. Moved verbatim (17 + 87 lines, asserted
  identical). `_ensure_unicode_font` imports `_pick_unicode_font` from
  `anyq.language` - not duplicated.

`science_manim_graph_agent.py`: 773 -> 636 lines. Dropped the now-unused
`shutil`, `subprocess`, `tempfile` and `from spoon_ai.llm import LLMManager`
imports (their only consumers moved out). Everything moved is re-imported so
the module namespace is unchanged.

Import-order note: `anyq/llm_client.py` imports `anyq.config` before it
constructs `LLMManager()`, so `load_dotenv()` still runs before the manager is
built, exactly as in the original file.

Created `agent/check.sh`. When `spoon_ai` is not installed it writes a minimal
stub to a temp dir and puts it on `PYTHONPATH`, so the import graph of *our*
modules is still exercised rather than skipped; it prints a NOTE when it does.

Breakages during Task 2: none.

---

## Task 3 - vision and render

Created:

- **`anyq/vision.py`** - `_guess_image_mime_type`, `_analyze_one_image_sync`,
  `analyze_image_with_gemini`. Moved verbatim (111 lines, asserted identical).
- **`anyq/render.py`** - `_error_tail`, `render_video`, and
  `_RENDER_REPAIR_ATTEMPTS`. Diffed against the previous file: the only
  difference is the one line the task authorises (see below).

`science_manim_graph_agent.py`: 636 -> 441 lines. Dropped `mimetypes`, `time`,
`json`, `os`, `Tuple` and `from spoon_ai.tools.mcp_tool import MCPTool` - every
consumer of those moved out. Everything moved is re-imported, so the module
namespace is unchanged.

### The one authorised behaviour change

`render_video` now reports which attempt produced the video:

```python
        if payload.get("status") == "ok":
            return {
                "video_path": str(payload.get("video_path") or ""),
                "mcp_raw_result": raw,
                "render_error": "",
                "render_attempt": attempt + 1,      # <- added
            }
```

`render_attempt` is `1` when the first render succeeds, `2` when the first
repair succeeds, and so on. The failure return is untouched: it still yields
`{"video_path": "", "mcp_raw_result": "", "render_error": last_error}` with no
`render_attempt` key. `render_attempt: int` was added to `ScienceVideoState`
so the key is declared where the rest of the state lives.

`check.sh` grew a `[render]` section that drives `render_video` against a fake
MCP tool and a fake `_llm_chat`, asserting `render_attempt == 1` on a
first-try success, `== 2` after one repair, and absent on total failure.

Breakages during Task 3: none in the code. One in my tooling, recorded for
completeness:

  [task 3] сломалось: check.sh got a literal newline inside a Python string
  when I generated it → причина: the backslash escapes in my generator script
  did not survive to the file → починил: rebuilt that section line-by-line
  with no escape sequences, and normalised check.sh back to LF endings.

---

## Task 4 - nodes and graph

Created:

- **`anyq/nodes.py`** - `ScienceVideoState`, `classify_intent`,
  `route_after_intent`, `_SIMPLE_ARITH_RE`, `_heuristic_video_needed`,
  `decide_video_needed`, `route_after_video_needed`, `reject_non_science`,
  `educator_answer`, `generate_manim_script`, `format_output`. Moved verbatim
  (288 lines, asserted identical).
- **`anyq/graph.py`** - `build_app`, `app = build_app()`, `run_once`. Moved
  verbatim (46 lines, asserted identical).

`science_manim_graph_agent.py`: 441 -> 41 lines. It now re-exports exactly the
six names the task lists - `app`, `run_once`, `_detect_language`,
`DEFAULT_OUTPUT_LANGUAGE`, `_latex_toolchain_healthy`, `ScienceVideoState` -
and keeps the `if __name__ == "__main__":` REPL block verbatim, so
`python science_manim_graph_agent.py` still behaves as before.

`_SIMPLE_ARITH_RE` is dead code (see the bug list) but sits inside the moved
region, so it moved with the nodes rather than being deleted.

### The silent-Kazakh check, done explicitly

The worry was: if the re-export chain breaks, `agent_ws_client` swallows the
ImportError and every user silently gets Kazakh. Two things were verified.

1. **It cannot happen any more.** Task 1 moved `_friendly_failure_text` into
   `anyq/language.py`, where `_detect_language` is a direct import rather than
   a `try:`-wrapped import from `science_manim_graph_agent`. Deleting the
   re-export line from the shim and re-running still produced the *Russian*
   message for Russian input.
2. **A broken re-export fails loudly.** Removing
   `from anyq.language import _detect_language` from the shim on purpose made
   `check.sh` print `FAIL  _detect_language is importable` and exit 1. The line
   was then restored and the checks pass again.

Note this means the premise in the task ("agent_ws_client imports them from
science_manim_graph_agent inside try/except") no longer holds - that import was
removed in Task 1. The shim still re-exports both names as required.

Breakages during Task 4: none in the code. One in my own negative test:

  [task 4] сломалось: the first negative test reported PASS when it should
  have failed → причина: my test patched the shim with an LF-terminated
  pattern while the file is CRLF, so the deletion silently did nothing →
  починил: split on the actual line terminator; the retried test failed
  correctly, and the shim was restored from a backup copy.

### Final layout

```
agent/
  science_manim_graph_agent.py   41   thin shim + CLI entry point
  agent_ws_client.py            185   websocket wrapper
  check.sh                            all checks
  anyq/
    __init__.py                   7
    config.py                    59   every os.getenv + load_dotenv
    prompts.py                  361   API reference + system/rewrite/repair prompts
    language.py                 150   language, fonts, user-facing messages
    llm_client.py                55   llm, retry wrapper
    script_guard.py             124   fence/JSON helpers + Manim script guards
    vision.py                   138   Gemini image analysis
    render.py                   114   MCP render + repair loop
    nodes.py                    324   graph steps + ScienceVideoState
    graph.py                     68   wiring, app, run_once
```

---

## Bugs and oddities found - NOT fixed

Recorded per rule 5. None of these were touched.

1. **`_SIMPLE_ARITH_RE`** (`science_manim_graph_agent.py`) is compiled and
   never used anywhere. Dead code from an earlier heuristic.
2. **`_latex_is_available()`** is defined and never called; the code path
   actually used is `_latex_toolchain_healthy()`.
3. **`_heuristic_video_needed` never returns `None`**, so in
   `decide_video_needed` the branch `if heuristic is not None` is always taken
   and the trailing "Fallback: always generate video for science" `return` is
   unreachable.
4. **`format_output` returns `final_video_path: None`** when `video_needed` is
   false, while `reject_non_science` returns `""` for the same key.
   `ScienceVideoState` declares it `str`. `agent_ws_client` papers over it with
   `or ""`.
5. **`_TRANSIENT_LLM_MARKERS` matches raw substrings** of the lowercased
   exception text, including `"500"`, `"429"` and `"timeout"`. A message like
   "took 500 ms", or a path containing `429`, is misread as a transient error
   and retried with backoff.
6. **Env reads moved to import time** (this was the explicit ask in Task 1, so
   it is intended, but it is a real behaviour difference): `DOC_SNIPPET_MODE`,
   `GEMINI_API_KEY`, `GEMINI_VISION_MODEL`, `MANIM_ALLOW_LATEX`,
   `MANIM_MCP_SERVER_SCRIPT`, `MANIM_MCP_PYTHON` and `MANIM_EXECUTABLE` used to
   be read on every call. Anything that mutates `os.environ` *after* import no
   longer has an effect.
7. **`_friendly_failure_text` lost one fallback path in Task 1.** The original
   wrapped `from science_manim_graph_agent import _detect_language,
   DEFAULT_OUTPUT_LANGUAGE` in the `try`, so a failure of that import silently
   fell back to Kazakh. It now imports `_detect_language` directly from
   `anyq.language`, which cannot fail that way. The `try/except` is kept for
   shape but now only guards `_detect_language` itself. `check.sh` asserts the
   Russian and Kazakh branches are actually reached, so a silent all-Kazakh
   regression cannot pass unnoticed.
8. **`_resolve_output_language(state: "ScienceVideoState")`** in
   `anyq/language.py` annotates a forward reference to a name that does not
   exist in that module. It is never evaluated at runtime so behaviour is
   unchanged, but `typing.get_type_hints()` on it would now raise where it
   previously resolved. Kept verbatim per the no-rename rule.


---

## ВОПРОСЫ - choices I made that you may want to overrule

1. **`_RENDER_REPAIR_ATTEMPTS` lives in two places.** Task 1 said every
   `os.getenv` read belongs in `anyq/config.py`; Task 3 said `anyq/render.py`
   should hold `_RENDER_REPAIR_ATTEMPTS`. I kept the `os.getenv` call in
   `config.py` and re-exported the name from `render.py`, so
   `anyq.render._RENDER_REPAIR_ATTEMPTS` resolves and the "all env reads in one
   file" rule survives. If you want the `getenv` itself in `render.py`, say so.

2. **`render_attempt` on the failure path.** I read "номер попытки, на которой
   рендер удался" as success-only, so the failure return is byte-identical to
   before and carries no `render_attempt` key at all. The alternative - report
   how many attempts were burned - would change the failure return too, which
   the task told me not to touch.

3. **`render_attempt: int` was added to `ScienceVideoState`.** If
   `spoon_ai`'s `StateGraph` filters state updates against the TypedDict, the
   key would be dropped without this. I could not verify either way:
   `spoon-ai-sdk` is not installed in this environment, so `check.sh` exercises
   `render_video` directly rather than through a real graph run.

4. **`from __future__ import annotations` in `vision.py` and `render.py`**
   instead of importing `ScienceVideoState`. It keeps the moved code byte-for-
   byte and avoids a runtime dependency on `anyq.nodes`. Now that
   `ScienceVideoState` lives in `anyq/nodes.py` and nodes imports neither
   module, a real `from anyq.nodes import ScienceVideoState` would also work
   without a cycle - I picked the lighter option.

5. **The shim's namespace shrank.** As instructed it re-exports six names.
   Everything else that used to be an attribute of `science_manim_graph_agent`
   (`MANIM_API_REFERENCE`, `_REJECT_MESSAGES`, `llm`, `_llm_chat`,
   `_strip_code_fences`, `render_video`, `analyze_image_with_gemini`, ...) is
   now only on its `anyq.*` module. Nothing in this repo imported them from
   there - I grepped - but an outside script might.

6. **The CLI REPL stayed in the shim** rather than moving to `anyq/graph.py`,
   because moving it would change what `python science_manim_graph_agent.py`
   does. Say the word if you want it in `graph.py` with a `python -m` entry.

7. **`check.sh` stubs `spoon_ai` when it is missing.** In your venv it will use
   the real package. The stub exists so the checks exercise our own import
   graph instead of being skipped; it prints a NOTE whenever it kicks in.
   Worth re-running `agent/check.sh` in the real venv before trusting it.

8. **`check.sh` is stored with LF endings**, like the existing `start.sh`. With
   this repo's `core.autocrlf=true`, a Windows working tree gets CRLF for both.
   That is a pre-existing repo condition (`start.sh` already has it), so I did
   not add a `.gitattributes` - it would be outside the task.

9. **Commits are on branch `refactor/anyq-package`, not `main`.** Task 1 was
   also uncommitted when this run started, so it got its own commit
   (`b302210`) rather than being folded into the Task 2 commit.

10. **`NOTES.md` is at the repo root** next to `PROJECT_MEMORY.md`;
    `check.sh` is in `agent/` because it has to run from there.
