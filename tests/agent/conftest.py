"""Fixtures for the agent-side tests.

The agent package imports the real `spoon_ai` SDK, which is a Linux/container
dependency. `tests/stubs/` carries a minimal stand-in so the pure-python parts
(the AST validator, telemetry) can be tested on any host.
"""

import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session", autouse=True)
def agent_import_path():
    """Put `agent/` and the spoon_ai stub on sys.path for this package."""
    for path in (REPO_ROOT / "agent", REPO_ROOT / "tests" / "stubs"):
        entry = str(path)
        if entry not in sys.path:
            sys.path.insert(0, entry)
    yield


@pytest.fixture(scope="session")
def validate_manim_script(agent_import_path):
    from anyq.script_guard import validate_manim_script as validator

    return validator


@pytest.fixture(scope="session")
def safe_json_loads(agent_import_path):
    from anyq.script_guard import _safe_json_loads as loader

    return loader


@pytest.fixture
def agent_telemetry(agent_import_path, monkeypatch):
    """The telemetry module, writing into a throwaway file."""
    log_path = Path(tempfile.mkdtemp()) / "runs.jsonl"
    monkeypatch.setenv("ANYQ_TELEMETRY_PATH", str(log_path))

    import anyq.telemetry as telemetry

    # config.py reads the env at import time, so point the module at the
    # temporary file directly - importing it again would not re-read it.
    monkeypatch.setattr(telemetry, "ANYQ_TELEMETRY_PATH", str(log_path))
    return telemetry
