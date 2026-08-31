# Changelog

All notable changes to Anyq are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

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
