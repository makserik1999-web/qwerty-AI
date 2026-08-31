# Changelog

All notable changes to Anyq are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

### Phase C (in progress) - the answer cache

**Added**

- Answers are cached and repeats are served in milliseconds. Storage policy:
  every question increments a small counter, an answer starts in a 48-hour
  tier, and it only earns 30-day storage once the question actually comes
  back. Curated entries never expire.
- Not cached, deliberately: anything with a screenshot, prompts over 200
  characters, personal requests ("реши мою задачу"), and text-only replies -
  which is what refusals and degraded-mode notices look like.
- Media retention with a disk budget (`MEDIA_MAX_BYTES`, default 20GB).
  Collection runs hourly, only above the high-water mark, and scores files by
  hits, recency and size. Curated videos and anything under 24 hours old are
  never deleted; when it cannot free enough it says so instead of deleting
  protected content. Deleting a file also clears the references to it, so old
  chats lose the video rather than gaining a broken player.
- `/api/admin/cache/stats`, behind a username allowlist.
- Cached answers are labelled "From the library" and offer "Generate a new
  one", which re-asks with the cache bypassed.


### Phase B1 - backend/main.py split into a package

**Changed**

- `backend/main.py` (1149 lines: config, database, auth, four routers, two
  WebSocket endpoints and the connection managers in one file) is now the
  `backend/app/` package. The largest module is 199 lines.
- `backend/main.py` remains as a 13-line entry point, because the image runs
  `uvicorn main:app`; the Dockerfile is unchanged.
- Routes are registered through `APIRouter` instead of `@app.*` decorators.
  The route table is identical - same paths, same methods, same handlers.
- `api/media.py` reads `config.MEDIA_DIR` at call time rather than binding it
  at import, so tests can point it at a temporary directory.

Behaviour is unchanged by design (the standing refactoring rule): names,
signatures and comments were moved verbatim. Verified by an AST diff showing
all 59 functions/classes and all 31 module constants still present, an
identical route table, and the full test suite passing with **unchanged test
bodies** - only the conftest wiring moved.


### Phase D (partial) - the video player

**Fixed**

- **The scrub bar could not seek.** Three independent causes, all measured on
  the running stack:
  1. `/media` ignored `Range` (starlette 0.36's `FileResponse` always answers
     200). Asking for 101 bytes of a 784KB video returned all 784KB. Range is
     now implemented in the endpoint, with `ETag`, `If-Range` and 416.
  2. Manim wrote the `moov` atom at the END of the file (measured at 99% of
     the way in), so the browser could not build a seek index without
     downloading everything. Renders are now remuxed with `+faststart`.
  3. The client cleared its "seeking" flag from `mouseup` on the range input;
     releasing anywhere else stranded the flag and froze the bar. Replaced
     with a pointer-capture bar driven by the video's `seeking`/`seeked`.
- **The brush turned itself on.** The canvas took pointer events whenever the
  video was paused, so clicks meant to resume playback drew instead. Drawing
  is now an explicit toggle (button or `D`), off by default.
- `message_count` was 0 for every chat: the aggregation joined an ObjectId
  against a string `chat_id`.
- Error bubbles rendered as `role: "assistant"`, so a failed pipeline looked
  like an answer. They now carry `data-role="error"`.

**Changed**

- `VideoPanel.tsx` (756 lines) split into `features/player/`.
- Canvas honours `devicePixelRatio` and survives a resize; annotations are no
  longer wiped when playback resumes; the pen has a colour palette; player
  controls carry ARIA roles and labels.
- Keyboard: space play/pause, arrows seek 5s (10s with shift), `D` draw mode,
  `P`/`E` pen and eraser.


### Phase A - repository cleanup and structure

**Security**

- Removed `logs/cookies.txt`, which held a live `anyq_session` token valid into
  September 2026, and `logs/sig.json`, which held the `e2e_user` password.
  Test credentials are now generated per run instead of living on disk.

**Added**

- `tests/` - the smoke, e2e and UI scripts from `logs/` rewritten as a pytest
  suite. `tests/backend` and `tests/agent` run with no Docker; `tests/e2e` and
  `tests/ui` are marked and skipped unless `ANYQ_STACK_UP=1`.
- `pyproject.toml` with a ruff configuration, `pytest.ini`, `requirements-dev.txt`.
- `Makefile` replacing the macOS-only `start.sh` (`make up/down/test/lint`).
- `.github/workflows/ci.yml` - lint plus tests for python, lint plus build for
  the frontend, and a docker build of every service.
- `.editorconfig`, `CHANGELOG.md`.

**Changed**

- Docs moved to `docs/`: `AUDIT_2026-08.md`, `REFACTORING_NOTES.md`,
  `PROJECT_MEMORY.md`, `IMPROVEMENT_PLAN.md`.
- Debug scripts moved to `scripts/`; `agent/check.sh` moved there too.
- Containers and the network renamed `spoon-*` to `anyq-*`. Named volumes are
  unchanged, so no data is affected - but run `docker compose down` **before**
  the first `make up` on the new names, otherwise the old `spoon-*` containers
  linger as orphans.
- Default `DATABASE_NAME` is now `anyq_db` in both `backend/main.py` and
  `docker-compose.yml`, matching the README and the existing `.env`. Deployments
  that relied on the old `spoon_chat` fallback (i.e. never set `DATABASE_NAME`)
  must set it explicitly or migrate the database.
- Default model in `docker-compose.yml` is now `gemini-3-flash-preview`,
  matching the README and `.env`.
- `signup` now raises its 409 with `from None`, so a Mongo `DuplicateKeyError`
  can never surface in a traceback.

**Removed**

- `logs/` in its entirety - it mixed tests, debug scripts, a virtualenv,
  run artefacts and credentials.
- `frontend/dist/` and `compose_up*.log` build artefacts; `start.sh`.
