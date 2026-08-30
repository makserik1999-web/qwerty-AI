# Anyq refactoring notes

Log of the `agent/` refactoring into the `anyq/` package. One section per task.
Rules in `PROJECT_MEMORY.md`: no behaviour change, no renames, comments kept
verbatim, bugs recorded here instead of fixed.

Checks: `agent/check.sh` (run it from anywhere; it cd's to `agent/`).

---

## FIX RUN - auth, sandbox, correctness, deploy hygiene (branch `fix/auth-and-hardening`)

A separate hardening pass on top of the refactor (commit range after the
refactor tasks). This is a *behaviour-changing* pass - the original "record
bugs, don't fix them" rule is intentionally overridden by the task that asked
for these fixes.

### Status of the known-bug list ("Bugs and oddities found - NOT fixed")

1. `_SIMPLE_ARITH_RE` - already removed in Task 5. Unchanged.
2. `_latex_is_available()` - still defined and unused (kept; harmless).
3. `_heuristic_video_needed` never returns `None` - unreachable fallback branch
   kept; harmless.
4. `format_output` returns `final_video_path: None` when no video - kept as-is
   (`agent_ws_client` still normalises with `or ""`).
5. `_TRANSIENT_LLM_MARKERS` raw-substring matching - **fixed**: markers
   tightened (`"429 too many requests"`, `"500 internal"`, ...) and matched
   against the message tail (-300 chars) instead of the whole string, so
   user-echoed text like "took 500 ms" no longer forces bogus retries.
6. Env reads at import time - kept (intended), but `config.py` now validates
   every numeric env (typo/negative exits with a clear FATAL message instead of
   a deep traceback).
7. `_friendly_failure_text` fallback - unchanged (still works per check.sh).
8. `_resolve_output_language` forward reference - kept verbatim (never
   evaluated at runtime).
9. **Parallel group race (empty `educator_text`) - FIXED.** `build_app` no
   longer uses the `educate_and_script` parallel group: the video path is now
   strictly `educator_video -> manim_script -> render -> output`, so
   `generate_manim_script` sees the educator explanation (measured: non-zero
   `educator_text_len` in telemetry) and `educator_answer` runs exactly ONCE
   per request (no double LLM cost).
10. `manim_script` with no incoming edge - **FIXED** by the same change: it now
    has an explicit `educator_video -> manim_script` edge.

### Fixed in this pass (highlights)

**Backend (`backend/main.py` rewritten):**
- Real auth: `users` (username unique, email optional unique, bcrypt
  `password_hash`), `sessions` (random 48-byte token stored as sha256, TTL
  index), endpoints `/api/auth/signup|login|logout|me`, HttpOnly
  `anyq_session` cookie (`SameSite=Lax`, `Secure` behind `COOKIE_SECURE=1`),
  in-memory login rate limiter (ip + user keys).
- Identity is server-side only: `GET /api/chats[/{chat_id}]` derive user from
  the cookie; custom exceptions -> 401/400/404 JSON. `x-user-id` headers are
  gone.
- UI WS moved to `/ws` (no path param); unauthenticated/origin-not-allowed
  handshakes are rejected. Every frame handled in `_handle_ui_frame`; malformed
  frames no longer kill the socket.
- Agent channel: `AGENT_SECRET` handshake (`{"type":"auth","token":...}`)
  before any request is processed; wrong/missing secret -> close 1008;
  `request_id` is server-generated uuid4; `pending_requests` get a TTL sweep +
  notification of all affected users when the agent drops.
- `user_message`: chat ownership check (403-ish error frame), 24-hex
  `chat_id` validation, prompt/title/screenshot size limits, agent availability
  checked BEFORE saving the message.
- `/media`: authenticated, only known video types, `os.path.basename`-safe.
- Chat list: single aggregation (no N+1 `count_documents`).
- CORS: explicit origin allowlist (`credentials` enabled, never `*`).

**Agent:**
- `script_guard.py`: real AST validator `validate_manim_script` (import
  whitelist manim/numpy/math/random/typing, module level only imports/classes/
  simple assignments/Text.set_default, banned eval/exec/open/socket/requests/
  input/breakpoint/getattr/dunder tricks, class decorators, `__`-prefixed dict
  keys/kwargs). A rejected script is NEVER rendered - `nodes.py` raises a clear
  error before render, `render.py` also re-validates before every render and
  before repair prompts.
- `manim_server.py`: same validator embedded (defense in depth); subprocess
  runs with a minimal env (no API keys/secrets), as a new process group killed
  with `os.killpg` on timeout (no ffmpeg orphans); removed the "search any mp4"
  fallback that could return a stale video; `MANIM_RENDER_TIMEOUT_SEC`.
- Prompt injection: every user/image/script insertion is wrapped in
  `<user_input>…</user_input>`-style tags with explicit "data, not
  instructions" notices (`nodes.py`, `vision.py`, `render.py`).
- `nodes.py`: LaTeX probe and font listing run in `asyncio.to_thread`; result
  cached in `_latex_toolchain_healthy`.
- `agent_ws_client.py`: AGENT_SECRET handshake; per-request deadline
  (`asyncio.wait_for` on `app.invoke`); `max_size` frame limit; idlest
  `recv` timeout; real `"status":"error"` responses (friendly text separate
  field); previews are length-only (no user text in stdout); image size/count
  limits.
- `telemetry.py`: user message stored as sha256 + length only (no raw 200
  chars); one JSON line also printed to stdout as `TELEMETRY ...` (bounded by
  docker log rotation).
- `config.py`: env validation (int/float ranges, FATAL on typo), AGENT_SECRET,
  image limits, WS limits, request deadline.

**Frontend:**
- `App.tsx`: hardcoded `admin/yesko` and `sessionStorage['anyq_auth']` gone;
  session restored via `GET /api/auth/me`; login/signup forms call the real
  endpoints (`LoginScreen.tsx`); logout clears all chat state.
- Cross-chat contamination fixed: messages/videos stored per `chatId`
  (`messagesByChat`, `videoByChat`); `ai_response` and `error` frames keyed by
  `chat_id`.
- Message loss / eternal spinner: `sendMessage` return value honored, sending
  blocked while `!isConnected` (button + warning text), `isLoading` is
  per-chat with a 25 min timeout, outbound queue flashed on reconnect.
- `useWebSocket.ts`: app-level heartbeat (ping every 25 s, close with code
  4001 after 35 s without pong), stale-socket guard (`wsRef.current === ws`),
  `pong` handled internally.
- `ChatSidebar`/`ChatPanel`/`VideoPanel`: count updates incremental (no
  full refetch on every response), canvas `absolute` + centered, undo history
  capped at 15 entries.
- ES-lint fixed: `eslint` + `@typescript-eslint` + `eslint-plugin-react-hooks`
  added to devDependencies with `.eslintrc.cjs`; `npm run lint` passes and
  shares the lockfile (`npm ci`).

**Deploy:**
- nginx: `/ws/agent` blocked externally (403), security headers (CSP,
  X-Frame-Options, nosniff, HSTS, Referrer-Policy, Permissions-Policy),
  `client_max_body_size`.
- compose: AGENT_SECRET to backend+agent, `MANIM_OUTPUT_DIR` explicit,
  `MEDIA_DIR`, read-only rootfs + tmpfs for the agent, `cap_drop: ALL` +
  `no-new-privileges`, resource limits (`deploy.resources`), log rotation
  (`max-size/max-file`), healthchecks for frontend/agent, backend `/health`
  now pings MongoDB (503 when DB down).
- Dockerfiles: non-root users (backend `appuser`, agent `appuser`), `npm ci` +
  lockfile-first build, no manual envsubst in CMD (template auto-render),
  `.dockerignore` for all three build contexts.
- Telemetry file lands in the agent's tmpfs and stdout; docker log rotation
  bounds growth.

### Not fixed (out of scope / by design)

- MongoDB auth (`--auth` + users): the audit's 2.6 recommendation. Not enabled
  because the port is not published (internal network only) and this pass
  focuses on the app layer; can be a follow-up without code changes.
- TLS: nginx still serves plain HTTP locally; `COOKIE_SECURE=1` exists for
  when a TLS terminator is added (README notes the wss:// upgrade is
  automatic).
- `check.sh` verified locally via a spoon_ai stub on a Windows host (see
  `logs/run_check.sh`) - the stub lives under `logs/` which is gitignored;
  the canonical verification remains the real-SDK container run.

### Bugs caught by verification during this pass

- **Email-uniqueness bug (backend).** The original duplicate check used
  `{"$or": [{"username": u}, {"email": e}]}` even when `e` was empty. In Mongo
  `{"email": null}` matches documents that have NO `email` field at all, so the
  *second* signup without an email always reported "Email already registered".
  Caught by the backend smoke test (signup carol -> 409 Email already
  registered). Fixed: the `email` condition is only added to the `$or` list
  when an email was actually provided.
- **WS smoke flow.** A full end-to-end backend test (signup/login/logout/me,
  401 gates on `/api/chats` + `/media`, WS without cookie rejected, create chat
  via WS, agent handshake with wrong secret rejected / right secret accepted,
  server-side uuid4 request_id in the request to the agent, ai_response and
  error frames keyed by chat_id, cross-user chat isolation) lives in
  `logs/backend_smoke.py` and currently passes 38/38 against the real app with
  mongomock-motor (not committed - `logs/` is gitignored).

### Verification results (this pass)

- `python -m py_compile` on every backend + agent python file: PASS.
- `agent/check.sh` (via the `logs/` spoon_ai stub on Windows): 39/39 PASS,
  including the new `validate_manim_script` accept/reject cases and the
  hashed-telemetry key set.
- `logs/backend_smoke.py` (real app + mongomock-motor): 38/38 PASS - covers
  401 gates, signup/dup/short-password, login/logout/me round-trip, chat list
  + invalid chat_id, media auth + traversal, WS without cookie rejected, WS
  chat create + invalid chat_id error frame, agent handshake wrong/right
  secret, server-side uuid4 request_id, ai_response/error frames keyed by
  chat_id, cross-user chat isolation (alice 404 on carol's chat).
- Frontend: `npm run lint` 0 warnings, `tsc --noEmit` clean, `npm run build`
  6 builds OK (chunk-size warning only).
- Docker: `docker compose config` valid; all three images built
  (qwerty-ai-agent 5.75GB/1.57GB, backend 273MB, frontend 96MB) with the new
  Dockerfiles; `docker compose up --build -d` completed its build phase.
- NOT re-verified end-to-end against running containers: Docker Desktop's
  engine wedged mid-`up` (containers created but never started; `docker start`
  and `docker compose up` hang; a Docker Desktop restart took >2 min to bring
  the named pipe back). The in-process smoke test covers the same backend
  code paths, so the gap is the nginx layer (/ws/agent 403, /ws proxy) and
  the real Mongo/Manim runtime. See the final report for exactly what was
  verified vs. what needs a container run to confirm.
- One real bug was caught by the smoke test and fixed: a Mongo uniqueness
  query that treated `{"email": None}` as "matches everyone without email",
  making the second signup fail with "Email already registered" (see "Bugs
  caught by verification" above).
- Live-stack verification (after Docker Desktop recovered): `docker compose up
  -d` brought all four containers up; mongo/backend/agent/frontend all
  HEALTHY. Agent log shows "Connected to backend as AI Agent" +
  "Agent authenticated (handshake ok)"; backend log shows "AI Agent
  authenticated / AI Agent connected". Through nginx (localhost:3000):
  `/` 200, `/health` 200, `/api/auth/me` without cookie 401, `/ws/agent` 403
  (blocked). Full auth round-trip through nginx: signup 201 -> me 200 ->
  logout 200 -> me 401 -> login 200 -> me 200.
- Live fix found by the frontend healthcheck: nginx binds `0.0.0.0:3000`
  (IPv4) inside the container, but `localhost` resolves to `::1` first in the
  official nginx image, so the healthcheck `wget http://localhost:3000/`
  always got Connection refused. Changed to `http://127.0.0.1:3000/`. Docker
  Desktop's engine also wedged once mid-`up --build` (containers created but
  never started; a Docker Desktop restart was needed) - unrelated to the
  project code.

### Live-stack LLM round-trip (this pass, with a temporary Gemini key)

- **Model discovery**: default `gemini-2.5-pro` is no longer served to new
  accounts (404 "no longer available to new users"). The API approves
  `gemini-3-flash-preview` / `gemini-3.1-pro-preview`.
- **spoon_ai env quirk**: the model is read from `{PROVIDER}_MODEL`
  (`GEMINI_MODEL`), NOT `DEFAULT_MODEL`. The compose file now forwards
  `GEMINI_MODEL` (defaulting to `DEFAULT_MODEL`) and `.env.example` documents
  both.
- Full round-trip passed with the live stack: signup -> WS /ws -> create chat
  -> "Explain gravity" -> agent classified (kk, Physics) -> LLM wrote the
  educator text AND the Manim script -> AST validator accepted it -> Manim
  rendered a real 762 KB mp4 -> `/media` served it (200 with cookie, 401
  without). Telemetry showed `educator_text_len: 2413/2578` (the parallel
  group fix holds in production) and `render_ok: true`.
- **No-key behaviour** (final .env state): with `GEMINI_API_KEY` empty the
  agent replies with the polite Russian "AI-функции сейчас недоступны…"
  message as a normal `ai_response` (no crash, no error frame). Implemented
  in `agent_ws_client.process_request` before calling the graph.
- **Second real bug caught in the live stack**: the users collection in Mongo
  has a `sparse unique` index on email, and signup stored `email: None`
  explicitly. A sparse index treats explicit null as a VALUE (not "missing"),
  so every subsequent signup without an email hit DuplicateKeyError ->
  "Username or email already registered" 409. Fixed by only writing the
  `email` field when an email was actually provided (backend/main.py). The
  in-memory smoke test could not catch this because mongomock does not model
  sparse-index null semantics. (This supersedes the earlier $or-only fix from
  the smoke test - both changes are in the code.)

---

## Prompt integrity log

sha256 of `build_manim_system_prompt(True, "Kazakh (қазақ тілі)")`:

| when | sha256 | 
|---|---|
| baseline, before Task 2 | `0cf849266f9ae68e4081397abd3309eaa7ec0a002b5cbe79224fe99506fcb045` |
| after Task 2 | `0cf849266f9ae68e4081397abd3309eaa7ec0a002b5cbe79224fe99506fcb045` |
| after Task 3 | `0cf849266f9ae68e4081397abd3309eaa7ec0a002b5cbe79224fe99506fcb045` |
| after Task 4 | `0cf849266f9ae68e4081397abd3309eaa7ec0a002b5cbe79224fe99506fcb045` |
| after FIX RUN | `0cf849266f9ae68e4081397abd3309eaa7ec0a002b5cbe79224fe99506fcb045` |

The value is pinned in `agent/check.sh` as `EXPECTED_PROMPT_SHA256`, so every
run re-verifies it (the fix run only wraps user content in delimiters; the
system prompt byte-for-byte is untouched).

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

## Tail 1 - `render_attempt` off `ScienceVideoState` (from Task 3's measurement)

Removed the `render_attempt: int` line from `ScienceVideoState` in
`anyq/nodes.py`. `render_video`'s own return dict is untouched - the success
path still returns `render_attempt`, the failure path still omits it.

Re-measured against the real SDK in a container, running the compiled graph
end to end (`DOC_SNIPPET_MODE=1`, a fake MCP tool):

- **Success**: the final merged state still contains `render_attempt: 1` -
  confirms Task 3's finding again, undeclared keys are not filtered.
- **Failure** (all repair attempts exhausted): the final merged state now has
  **no `render_attempt` key at all** - before this tail, with the field
  declared, `_initialize_state` pre-seeded it and the key was present with
  value `None`. That pre-seeding is gone now that the field isn't declared.

`check.sh`'s `[render]` section already asserted the return value of
`render_video` itself on all three paths (untouched by this tail); the
`ScienceVideoState`-declaration assertion right after it was flipped from
"declares render_attempt" to "no longer declares render_attempt".

---

## Tail 2 - removed the `educator_text` length print-probe

Removed the `print(f"[manim_script] educator_text length at entry: ...")`
line from `generate_manim_script` in `anyq/nodes.py`. The comment above it
describes the measurement itself (why `len(educator_text)` is read here,
and what an empty value means), which is still exactly true now that the
same measurement feeds `telemetry.record(educator_text_len=...)` instead of
stdout - so the comment was kept verbatim and only the `print(...)` call was
swapped for the `telemetry.record(...)` call.

Confirmed in the container that the probe text no longer appears in stdout
during a real graph run, and that `educator_text_len` still reads `0` inside
`generate_manim_script` under the parallel-group race (bug 9/10, unchanged,
not fixed).

---

## Task 5 - run telemetry and honest error statuses

Created **`anyq/telemetry.py`** (standard library only: `json`, `os`,
`threading`, `time`, `uuid`, `datetime`). One JSON Lines record per
websocket request:

- `new_run(request_id, user_message)` - called once, at the top of
  `agent_ws_client.process_request`, creates the run dict (module-level, not
  part of `ScienceVideoState`) with every field defaulted (`status` defaults
  to `"error"`, everything else to its natural empty value).
- `record(**fields)` - merges fields into the current run. Called from
  `process_request` after `app.invoke()` returns (language, is_science,
  subject, video_needed, render_attempt, render_ok, render_error_tail,
  status) and from `anyq/nodes.py`'s `generate_manim_script` (educator_text_len
  at entry, script_len at exit, on every return path including the
  `DOC_SNIPPET_MODE` stub).
- `note_guard_rewrite(name, fixed)` - appends
  `{"guard": name, "fired": True, "fixed": fixed}` to `guard_rewrites`;
  called once in each of the three rewrite branches in
  `generate_manim_script`, after the branch's own re-check of the rewritten
  script (see question 12 - this went through a revision, see there for the
  final shape and why `fired` is always `true`).
- `write()` - builds the final line (adds `timestamp`, computes `duration_ms`
  from a `time.monotonic()` start captured in `new_run`), creates the log
  directory if needed, appends one line under a `threading.Lock` in `"a"`
  mode with a `flush()`, and clears the module-level slot. The entire body is
  wrapped in `try/except Exception` - a telemetry failure only prints a
  warning, never raises.

Added `ANYQ_TELEMETRY_PATH = os.getenv("ANYQ_TELEMETRY_PATH",
"/app/logs/runs.jsonl")` to `anyq/config.py`, next to the other `os.getenv`
reads.

**Why a plain module-level dict is safe here, without `contextvars`:**
`agent_client()`'s loop does `resp = await process_request(data)` once per
message - one request is in flight at a time, so there is no cross-request
concurrency to guard against. Inside a single request, `educator_answer` and
`generate_manim_script` do run concurrently (the `educate_and_script`
parallel group), but they only ever touch their own keys of the same dict and
never `await` between reading and writing them, so plain dict mutation is
race-free.

### `agent_ws_client.py`: honest telemetry status, unchanged response

`process_request` now wraps its body in `try/except Exception/finally`:

- On success, `telemetry.record(..., status="complete")` before returning.
- On any exception, `telemetry.record(status="error",
  error_type=type(e).__name__)`, then a bare `raise` - the exception that
  reaches `agent_client()` is byte-identical to before, so its `except`
  block still builds the same friendly `status: "complete"` response the
  end user sees. Only the telemetry line now says what actually happened.
- `finally` still does the temp-image cleanup (untouched) and now also calls
  `telemetry.write()` exactly once.

The two early validation raises (`Missing request_id`, `Missing text`) moved
from before the `try` to inside it, so they also get a telemetry line now.
Same exception type, same message, same propagation - see question 1 below.

Verified end to end in the container (real SDK, real graph, `DOC_SNIPPET_MODE=1`):
a success run logs `status=complete, error_type=""`; a `Missing text` call
logs `status=error, error_type=ValueError` and still raises `ValueError`
out of `process_request`; a real node failure (missing
`MANIM_MCP_SERVER_SCRIPT`) logs `status=error,
error_type=GraphExecutionError` (the SDK wraps node exceptions in its own
`GraphExecutionError` - that wrapping predates this task) and still
propagates out of `process_request` unchanged.

### Removed `_SIMPLE_ARITH_RE`

Deleted the dead compiled regex from `anyq/nodes.py` (bug 1 in the list
below - explicitly named in this task, not a self-directed fix). Nothing
else in the repo referenced it; `check.sh` now asserts
`not hasattr(anyq.nodes, "_SIMPLE_ARITH_RE")`.

### `check.sh` additions

- `anyq.telemetry` added to the combined `anyq.*` import line; a new
  `_SIMPLE_ARITH_RE was removed` check next to it.
- The `ScienceVideoState declares render_attempt` check (Task 3) was flipped
  to `ScienceVideoState no longer declares render_attempt` (Tail 1).
- New `[telemetry]` section: writes a fully-populated run to a temp path
  under a subdirectory that doesn't exist yet (asserts the directory gets
  created and the line is valid JSON with exactly the 17 documented keys);
  writes a bare `new_run()`+`write()` with no `record()` calls (asserts the
  defaulted line still has the full key set and `status == "error"`); then
  points `ANYQ_TELEMETRY_PATH` at a path whose parent is a plain *file*
  (guaranteed to fail `os.makedirs` regardless of container privileges,
  unlike a merely-nonexistent absolute path which a root container can often
  still create) and asserts `write()` does not raise.

31 checks before this task; the full run (with all Task 5 additions) is
included in the "against the real spoon-ai-sdk" verification below.

### Breakages during Task 5

None. `check.sh` passed against the local stub on the first run and against
the real SDK in the container on the first run.

### Layout, updated

New file: `anyq/telemetry.py` (114 lines). Line counts of files touched by
the tails and Task 5, for the record (see the Task 4 tree above for the rest,
unchanged): `anyq/config.py` 59 -> 62, `anyq/nodes.py` 324 -> 330,
`agent_ws_client.py` 185 -> 205.

---

## Verification against the real spoon-ai-sdk (not the stub)

### Environment

`spoon-ai-sdk` would not install on the host: `bitarray` has no cp313 wheel and
building it needs MSVC. The full `agent` image was not built either - its
Dockerfile installs `texlive-*` and `manim`, several GB and many minutes, none
of which these checks touch. Instead: `python:3.12-slim-bookworm` +
`agent/requirements.txt` with only `manim` and `ManimPango` removed
(`manimpango` is imported inside a `try/except` in `_pick_unicode_font`, and
`manim` is never imported by the agent process at all). Result: **real
spoon-ai-sdk 0.3.6, fastmcp 2.14.1, mcp 1.25.0, pydantic 2.12.5** - the pinned
versions. The repo was bind-mounted at `/app`.

Worth knowing: a *loose* `pip install spoon-ai-sdk==0.3.6` resolves a newer
`fastmcp` and then dies on import:

```
ImportError: cannot import name 'WSTransport' from 'fastmcp.client.transports'
  spoon_ai/tools/mcp_tool.py:8
```

So `fastmcp==2.14.1` in `requirements.txt` is load-bearing, not cosmetic.

### check.sh with the real SDK

31 PASS, `ALL CHECKS PASSED`, exit code 0. `LLMManager()` constructs for real
(it logs `No API keys found for any provider, falling back to openai`). Prompt
sha256 recomputed inside the container: unchanged.

**Re-run for the tails and Task 5** (same image rebuilt from the current
`requirements.txt`, same bind mount): **40 PASS, `ALL CHECKS PASSED`, exit
code 0.** Prompt sha256 still unchanged. Beyond `check.sh` itself, two
additional real-SDK probes (not part of `check.sh`, run once by hand and then
discarded):

- Invoked the compiled `anyq.graph.app` directly (`DOC_SNIPPET_MODE=1`, a
  fake MCP tool) for both a render-success and a render-exhausted run. Success:
  final state has `render_attempt: 1`. Failure: `'render_attempt' in result`
  is `False` - confirms Tail 1's fix removed the `None`-seeded key on the
  failure path (see Tail 1 above). No `[manim_script] educator_text length at
  entry` text in stdout either run. `telemetry._current["educator_text_len"]`
  read `0` mid-run (bug 9/10, still reproduces, still not fixed) and
  `["script_len"]` read `146`, the stub script's length.
- Called `agent_ws_client.process_request` directly three times: a normal
  success, a `Missing text` call, and a call that reaches a real node failure
  (`MANIM_MCP_SERVER_SCRIPT` unset). All three raised/returned exactly as
  before this task (`ValueError`/`GraphExecutionError` still propagate out of
  `process_request` unchanged); the resulting telemetry log had three lines,
  each with the full key set, reading `status=complete/error/error` and
  `error_type=""/ValueError/GraphExecutionError` respectively.

### 1. Does the real StateGraph compile?

Yes.

```
from anyq.graph import app  -> spoon_ai.graph.engine.CompiledGraph
nodes registered   -> ['educator_text', 'educator_video', 'intent', 'manim_script',
                       'output', 'reject', 'render', 'video_needed', 'vision']
parallel_groups    -> {'educate_and_script': ['educator_video', 'manim_script']}
node_to_group      -> {'educator_video': 'educate_and_script',
                       'manim_script': 'educate_and_script'}
```

`build_app()` is also re-callable; a second call compiles a second graph fine.

### 2. Is `render_attempt` filtered out by the TypedDict?

**No. There is no filtering at all.** A probe node returning three keys - one
declared (`video_path`), one declared by this refactor (`render_attempt`), and
one declared nowhere (`totally_undeclared_key`) - had *all three* present in
the final state. `_update_state_with_reducers` (`engine.py:1259`) writes
whatever key it is handed.

So `render_attempt: int` on `ScienceVideoState` was **not required** for the
key to survive. It does, however, have a side effect I did not anticipate:

`_initialize_state` (`engine.py:1244`) pre-fills **every** annotated field of
the schema before the run - `[]` for list-typed fields, `None` for everything
else. Measured: a graph whose only node returns `{}` still ends with
`render_attempt` present, value `None`.

Consequence: because the field is now declared, the final state **always**
carries a `render_attempt` key - `None` when the render never succeeded, where
before the declaration the key would simply be absent on that path.
`render_video`'s own return dict is untouched on failure, and `check.sh` still
asserts that. See the questions section.

### 3. Does `educate_and_script` really run in parallel?

**Yes, genuinely concurrent** - and that is exactly why the script generator
never sees the explanation. Measured with 0.30s sleeps wrapped around both
nodes, `DOC_SNIPPET_MODE=1`, real graph:

```
[manim_script] educator_text length at entry: 0

  educator_answer        enter   0.001
  generate_manim_script  enter   0.001
  educator_answer        exit    0.301
  generate_manim_script  exit    0.302
  render_video           enter   0.302
  total wall time -> 0.302s        (0.60s if it were sequential)
```

`generate_manim_script` entered before `educator_answer` exited => CONCURRENT.

**`len(educator_text)` inside `generate_manim_script` is 0.** The engine only
merges a parallel group's results after every task completes
(`asyncio.wait(..., ALL_COMPLETED)` at `engine.py:1151`, updates applied at
`engine.py:1162`), so `generate_manim_script` structurally *cannot* observe
`educator_answer`'s output. The user message it builds ends with
"Explanation to visualize:" followed by nothing. The final state does hold
`educator_text` (length 39, the stub string) - it is merged, just after the
node that was supposed to consume it already ran.

Related: the node `manim_script` has **no incoming edge** in `build_app`. It
only ever runs because `add_parallel_group` binds it to `educator_video`, and
the graph then continues along `educator_video -> render -> output`.

Not fixed, per instruction. `build_app` was moved verbatim, so this predates
the refactor. The probe print in `generate_manim_script` was the one line
added for this measurement - removed in Tail 2 above once the measurement was
recorded; the same `len(educator_text)` reading now feeds telemetry's
`educator_text_len` field instead of stdout.

### Does anything import the shim's dropped names?

No.

- `docker-compose.yml`, `start.sh`, `agent/Dockerfile`, `backend/Dockerfile`
  contain no Python imports at all - they only `exec agent_ws_client.py` and
  `uvicorn main:app`.
- The only cross-module import of the shim anywhere in the repo is
  `agent/agent_ws_client.py:93` -> `from science_manim_graph_agent import app`,
  which the shim still provides.
- Every name the shim stopped exposing (`MANIM_API_REFERENCE`, `llm`,
  `_llm_chat`, `_strip_code_fences`, `render_video`, `build_app`, ...) is
  referenced only from `check.sh`, which imports each from its `anyq.*` module.
  `_GENERIC_FAILURE_MESSAGES` is used by `agent_ws_client.py`, also via
  `anyq.language`, not via the shim.
- `backend/main.py` never imports the agent; it talks to it over the websocket.

---

## Bugs and oddities found - NOT fixed

Recorded per rule 5. None of these were touched.

1. ~~**`_SIMPLE_ARITH_RE`** (`science_manim_graph_agent.py`) is compiled and
   never used anywhere. Dead code from an earlier heuristic.~~ **Removed in
   Task 5**, explicitly named in that task's instructions - not a
   self-directed fix.
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
9. **The parallel group defeats its own purpose.** `educate_and_script` runs
   `educator_video` and `manim_script` truly concurrently, and the engine
   merges a group's results only after all of its tasks finish. So
   `generate_manim_script` always reads `educator_text` as empty (measured: 0)
   and sends the model a prompt whose "Explanation to visualize:" section is
   blank. The Manim script is therefore written from the user question and
   subject alone, never from the educator explanation the pipeline just paid
   for. Pre-existing; `build_app` was moved verbatim.
10. **`manim_script` has no incoming edge.** It is reachable only through the
    parallel group. If `add_parallel_group` were ever removed or renamed, the
    node would silently stop running and `render_video` would raise
    `ValueError("manim_script is required")`.


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

3. ~~**`render_attempt: int` on `ScienceVideoState` - now measured, and I
   suggest dropping it.**~~ **Done, in Tail 1** of this run: the line is
   removed, `check.sh`'s assertion was flipped, and the failure-path state now
   measures as key-absent again (see Tail 1 above for the container
   confirmation).

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

7. **`check.sh` stubs `spoon_ai` when it is missing** - resolved: it has now
   been run against the real SDK 0.3.6 in a container (31 PASS, exit 0), so the
   stub path is a convenience, not the evidence. The container was a slim image
   built from `requirements.txt` minus `manim`/`ManimPango`, not the full
   `agent` image; if you want the checks run inside the real `agent` image too,
   that is a `docker compose build agent` away (long: texlive).

8. **`check.sh` is stored with LF endings**, like the existing `start.sh`. With
   this repo's `core.autocrlf=true`, a Windows working tree gets CRLF for both.
   That is a pre-existing repo condition (`start.sh` already has it), so I did
   not add a `.gitattributes` - it would be outside the task.

9. **Commits are on branch `refactor/anyq-package`, not `main`.** Task 1 was
   also uncommitted when this run started, so it got its own commit
   (`b302210`) rather than being folded into the Task 2 commit.

10. **`NOTES.md` is at the repo root** next to `PROJECT_MEMORY.md`;
    `check.sh` is in `agent/` because it has to run from there.

11. ~~**The `[manim_script] educator_text length at entry:` print now lives in
    `anyq/nodes.py` permanently.**~~ **Done, in Tail 2** of this run: the
    print is gone, the same measurement now feeds
    `telemetry.record(educator_text_len=...)`.

12. ~~**`guard_rewrites` records a guard as "fired" when its condition is
    true, not only when the LLM's rewrite then succeeds.**~~ **Resolved:**
    both, per instruction. `guard_rewrites` is now a list of objects,
    `{"guard": "<name>", "fired": true, "fixed": <bool>}`. `fired` is always
    `true` (an entry only exists because the guard's outer `if` was true);
    `fixed` is `bool(script2 and not _contains_X(script2))` - the same
    condition the inner `if` already guarded on. In each of the three
    branches, `note_guard_rewrite(name, fixed)` moved from right after the
    outer `if` to right after `fixed` is computed (still before `script2` is
    prefixed with `from manim import *` if needed), so it fires exactly once
    per branch with the correct `fixed` value either way. `check.sh`'s
    telemetry check now exercises one `fixed: True` and one `fixed: False`
    entry. Verified again against the real SDK in the container: 40 PASS
    unchanged.

13. **`render_ok` and `render_error_tail` are read from the merged graph
    state in `process_request` (`result.get("video_path")` /
    `result.get("render_error")`), not from `render_video`'s return value
    directly**, unlike `render_attempt` which the task named explicitly as
    coming "из результата render_video". Reading the merged state gives the
    identical value here - nothing between `render_video` and the state
    reaching `process_request` touches `video_path` or `render_error` - and
    avoids adding a second telemetry call site inside `anyq/render.py`. Say
    if you'd rather have `render.py` itself call
    `telemetry.record(render_ok=..., render_error_tail=...)` next to where it
    already knows these values.

    **Confirmed: kept as-is, no change.**

14. **Moved the `Missing request_id`/`Missing text` raises inside
    `process_request`'s `try` block** so they get a telemetry line too (they
    used to raise before any `try` existed). Same exception type, same
    message, same thing happens to the caller - only now `agent_client()`'s
    friendly-response path for these two cases also produces a `status:
    "error"` telemetry line instead of leaving them unlogged. Say if you'd
    rather keep these two validations un-instrumented and outside the `try`
    to minimize the diff against the pre-Task-5 shape of `process_request`.

    **Confirmed: kept as-is, no change.**

15. **`status` defaults to `"error"` in `new_run()`**, overwritten to
    `"complete"` only after a fully successful `record(...)` call at the end
    of the try block. This means a run that exits via some path that isn't
    `except Exception` (e.g. `BaseException` - `asyncio.CancelledError`,
    a websocket-level cancellation) still logs `"error"` rather than being
    silently left as whatever stale value a previous run left behind. No such
    path is exercised by any test; it's a defensive default, not a measured
    behaviour.

    **Confirmed: kept as-is, no change.**

16. **`DOC_SNIPPET_MODE`'s stub Manim script now also gets a
    `telemetry.record(script_len=...)` call** that didn't exist as a `return`
    site before - I restructured `return {"manim_script": "..."}` into
    `stub_script = "..."; telemetry.record(...); return {...}` so the stub
    path's `script_len` isn't silently `0` in telemetry. This is a small
    structural change to a block the task didn't name line-by-line, done
    because leaving it out would make telemetry lie about the one path where
    the value is trivial to capture. Say if you'd rather that branch keep its
    original one-statement `return` and leave `script_len` at the default `0`
    for `DOC_SNIPPET_MODE` runs.

    **Confirmed: kept as-is, no change.**

---

All open questions resolved. Branch `refactor/anyq-package` closed out: Tasks
1-5 plus both tails are complete, `check.sh` passes locally and against the
real spoon-ai-sdk 0.3.6 in a container, and no known bug from the "Bugs and
oddities" list was silently fixed - bugs 9 and 10 (the parallel-group race)
remain exactly as measured, per instruction.
