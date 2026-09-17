"""Shared fixtures for the Anyq test suite.

The backend is imported with its environment already prepared (AGENT_SECRET,
CORS_ORIGINS), because `backend/main.py` reads os.getenv at import time. The
real Mongo is replaced with mongomock-motor and the lifespan is neutralised,
so the whole backend suite runs without Docker.
"""

import contextlib
import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Test-only secret: the agent-channel handshake is exercised against it.
AGENT_SECRET = "test-secret-123"


@pytest.fixture(scope="session")
def agent_secret():
    """The shared secret the agent channel expects during the handshake."""
    return AGENT_SECRET


@pytest.fixture(scope="session")
def backend():
    """The wired-up backend, on an in-memory Mongo.

    Session-scoped: `app/config.py` reads the environment at import time, so
    the package is imported exactly once per test run.

    Returns a namespace rather than a module because the application is now a
    package: the attributes below are what the tests actually reach for, and
    keeping their names lets every test body stay as it was before the split.
    """
    os.environ["AGENT_SECRET"] = AGENT_SECRET
    os.environ["CORS_ORIGINS"] = "http://localhost:3000"

    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app import config
    from app.db import db
    from app.main import app as fastapi_app
    from app.security.ratelimit import login_limiter, signup_limiter
    from mongomock_motor import AsyncMongoMockClient

    client = AsyncMongoMockClient()
    db.client = client
    db.db = client["anyq_test"]

    # A media dir holding one fake video, for the /media auth checks.
    # api/media.py reads config.MEDIA_DIR at call time, so pointing the config
    # module at a temp dir is enough - no import-time path is frozen in.
    media = Path(tempfile.mkdtemp())
    (media / "rendered_1.mp4").write_bytes(b"fake-video-bytes")
    config.MEDIA_DIR = media
    # Finished exports live beside the videos in production; in tests they
    # need a real writable directory, not the container path.
    exports = media.parent / "exports"
    exports.mkdir(exist_ok=True)
    config.EXPORT_DIR = exports

    # No real Mongo on the host: the lifespan would try to build indexes.
    @contextlib.asynccontextmanager
    async def _noop_lifespan(app):
        yield

    fastapi_app.router.lifespan_context = _noop_lifespan

    return SimpleNamespace(
        app=fastapi_app,
        db=db,
        config=config,
        MEDIA_DIR=media,
        EXPORT_DIR=exports,
        login_limiter=login_limiter,
        signup_limiter=signup_limiter,
    )


@pytest.fixture(autouse=True)
def reset_auth_limiters(backend):
    """The limiters are in-memory and per-IP; every test starts clean.

    Without this, tests that exercise wrong passwords would burn the 5-attempt
    login budget for every later test from the same TestClient IP - and the
    signup limiter would be exhausted outright, since the whole suite creates
    far more than an hour's worth of accounts from one address.
    """
    backend.login_limiter._attempts.clear()
    backend.signup_limiter._attempts.clear()
    yield
    backend.login_limiter._attempts.clear()
    backend.signup_limiter._attempts.clear()


@pytest.fixture
def client(backend):
    """An authenticated-capable TestClient with its own cookie jar."""
    from fastapi.testclient import TestClient

    with TestClient(backend.app) as c:
        yield c


@pytest.fixture
def anon_client(backend):
    """A TestClient that never receives a session cookie."""
    from fastapi.testclient import TestClient

    with TestClient(backend.app) as c:
        yield c


@pytest.fixture
def new_user(client):
    """Sign up a fresh user and return its credentials + id.

    Each test gets its own account, so tests stay independent and can run in
    any order (the in-memory Mongo is shared for the whole session).
    """

    def _make(password: str = "password123"):
        username = f"u_{uuid.uuid4().hex[:12]}"
        response = client.post(
            "/api/auth/signup", json={"username": username, "password": password}
        )
        assert response.status_code == 201, response.text
        return {
            "username": username,
            "password": password,
            "id": response.json()["user"]["id"],
        }

    return _make
