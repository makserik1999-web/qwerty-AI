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
    """The imported backend module, wired to an in-memory Mongo.

    Session-scoped: `backend/main.py` reads its configuration at import time,
    so it is imported exactly once per test run.
    """
    os.environ["AGENT_SECRET"] = AGENT_SECRET
    os.environ["CORS_ORIGINS"] = "http://localhost:3000"

    sys.path.insert(0, str(REPO_ROOT / "backend"))
    import main
    from mongomock_motor import AsyncMongoMockClient

    client = AsyncMongoMockClient()
    main.db.client = client
    main.db.db = client["anyq_test"]

    # A media dir holding one fake video, for the /media auth checks.
    media = Path(tempfile.mkdtemp())
    (media / "rendered_1.mp4").write_bytes(b"fake-video-bytes")
    main.MEDIA_DIR = media

    # No real Mongo on the host: the lifespan would try to build indexes.
    @contextlib.asynccontextmanager
    async def _noop_lifespan(app):
        yield

    main.app.router.lifespan_context = _noop_lifespan

    return main


@pytest.fixture(autouse=True)
def reset_login_limiter(backend):
    """The limiter is in-memory and per-IP; every test starts from a clean slate.

    Without this, tests that exercise wrong passwords would burn the 5-attempt
    budget for every later test coming from the same TestClient IP.
    """
    backend.login_limiter._attempts.clear()
    yield
    backend.login_limiter._attempts.clear()


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
