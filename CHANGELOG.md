# Changelog

All notable changes to Anyq are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

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
