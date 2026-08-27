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
