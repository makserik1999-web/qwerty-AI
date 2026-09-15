"""The database had no password, and the site had no TLS.

Both were on the audit's "required before a public launch" line, and both are
the kind of gap that costs nothing until the day it costs everything.

MONGO. The database ran with no authentication at all. It is on the internal
docker network rather than the internet, which is what made it feel safe - but
that network holds four other containers, and one of them is the agent, which
executes code a language model wrote. "Not reachable from outside" was the
only thing standing between that code and every chat, session and account.

TLS. The session cookie travelled in clear text, and there was no way to serve
HTTPS at all. The comment above COOKIE_SECURE claimed compose set it from
HTTPS_TERMINATED; nothing anywhere set HTTPS_TERMINATED.

These read the compose file rather than a running stack, because what is being
asserted is the deployment, and a test that needed docker would not run in the
suite that actually gets run.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"
GITIGNORE = ROOT / ".gitignore"


@pytest.fixture(scope="module")
def compose() -> str:
    return COMPOSE.read_text(encoding="utf-8")


def _service(compose: str, name: str) -> str:
    """One service's block, from its key to the next two-space key."""
    found = re.search(rf"^  {name}:\n(.*?)(?=^  \S|\Z)", compose, re.DOTALL | re.M)
    assert found, f"no {name} service in docker-compose.yml"
    return found.group(1)


# ------------------------------------------------------------------ mongo --


class TestTheDatabaseRequiresAPassword:
    def test_mongod_is_started_with_auth(self, compose):
        """The one line that decides it. Everything else here is plumbing."""
        assert '"--auth"' in _service(compose, "mongo"), (
            "mongod is running without authentication"
        )

    def test_no_service_connects_anonymously(self, compose):
        """`mongodb://mongo:27017` with no credentials in it is the old URL."""
        anonymous = re.findall(r"MONGO_URL=mongodb://(?!\$)[^@\n]*\n", compose)
        assert not anonymous, anonymous

    @pytest.mark.parametrize("service", ["backend", "exporter"])
    def test_it_connects_as_the_least_privileged_user(self, compose, service):
        block = _service(compose, service)
        assert "MONGO_APP_USER" in block and "MONGO_APP_PASSWORD" in block, block

    def test_nothing_connects_as_root(self, compose):
        """The root user administers; it must never be a service's login."""
        for service in ("backend", "exporter"):
            block = _service(compose, service)
            assert "MONGO_ROOT_USER" not in block, service

    def test_the_auth_source_is_the_application_database(self, compose):
        """The app user is created in anyq_db, not in admin. Pointing
        authSource at admin would authenticate against a user that is not
        there, and the failure reads like a wrong password."""
        assert "authSource=${DATABASE_NAME:-anyq_db}" in compose

    def test_the_healthcheck_authenticates(self, compose):
        """Under --auth an anonymous ping is refused, so an unauthenticated
        healthcheck reports this container unhealthy forever - and nothing
        with `depends_on: service_healthy` on it ever starts."""
        block = _service(compose, "mongo")
        healthcheck = block[block.index("healthcheck:"):]
        assert "MONGO_ROOT_USER" in healthcheck, healthcheck

    def test_the_credentials_are_documented(self):
        example = ENV_EXAMPLE.read_text(encoding="utf-8")
        for key in ("MONGO_ROOT_USER", "MONGO_ROOT_PASSWORD",
                    "MONGO_APP_USER", "MONGO_APP_PASSWORD"):
            assert f"{key}=" in example, key

    def test_the_migration_script_exists(self):
        """An existing volume is never re-initialised by the mongo image, so
        adding the variables to compose is not enough on its own: the users
        have to be created while auth is still off. Without this script, a
        deployment with data in it locks itself out on the next restart."""
        assert (ROOT / "scripts" / "mongo_enable_auth.sh").is_file()


# -------------------------------------------------------------------- TLS --


class TestTheSiteCanServeHTTPS:
    def test_the_frontend_takes_a_certificate(self, compose):
        block = _service(compose, "frontend")
        assert "/etc/nginx/certs:ro" in block, "no certificate is mounted"

    def test_the_certificate_is_mounted_read_only(self, compose):
        assert ":/etc/nginx/certs:ro" in _service(compose, "frontend")

    def test_the_https_port_is_published(self, compose):
        assert "3443" in _service(compose, "frontend")

    def test_the_entrypoint_that_decides_this_is_shipped(self):
        script = ROOT / "frontend" / "docker-entrypoint.d" / "15-anyq-tls.sh"
        assert script.is_file()
        body = script.read_text(encoding="utf-8")
        # It must refuse rather than fall back. Serving the whole site in
        # clear text because a file was missing is the failure nobody notices.
        assert "exit 1" in body
        assert "redirect.conf" in body, "plain HTTP is not redirected"

    def test_the_dockerfile_makes_it_executable(self):
        """A file copied out of a Windows checkout arrives without its
        executable bit, and the nginx entrypoint skips it in silence - so the
        site would come up on plain HTTP with TLS switched on."""
        dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
        assert "chmod +x /docker-entrypoint.d/15-anyq-tls.sh" in dockerfile

    def test_the_healthcheck_survives_the_redirect(self, compose):
        """With TLS on, port 3000 answers a 301 and nothing else. A plain HTTP
        probe there fails, the container is unhealthy forever, and everything
        that depends on it stops starting."""
        block = _service(compose, "frontend")
        healthcheck = block[block.index("healthcheck:"):]
        assert "3443" in healthcheck, healthcheck

    def test_the_private_key_cannot_be_committed(self):
        ignored = GITIGNORE.read_text(encoding="utf-8")
        assert "*.pem" in ignored
        assert "frontend/certs/" in ignored


class TestTheCookieFollowsTheTransport:
    """The failure this pairing exists to prevent, and the one it caused first.

    Written first as "COOKIE_SECURE if it is set, otherwise HTTPS_TERMINATED",
    which reads sensibly and is wrong: every .env already carries
    COOKIE_SECURE=0 from before, so turning HTTPS on left the cookie
    travelling in clear text. Found on the running stack by reading the
    Set-Cookie header, not by reading the code.
    """

    @pytest.fixture(autouse=True)
    def _clean_env(self, backend, monkeypatch):
        monkeypatch.delenv("COOKIE_SECURE", raising=False)
        monkeypatch.delenv("HTTPS_TERMINATED", raising=False)
        yield
        # These tests reload app.config with a different environment, and the
        # module would otherwise stay reloaded with the last one's values for
        # whatever runs next. Put it back the way the rest of the suite
        # expects, so nothing here can become an ordering-dependent failure
        # somewhere else.
        import importlib

        import app.config as config

        importlib.reload(config)

    def _secure(self, monkeypatch, **env) -> bool:
        import importlib

        for key, value in env.items():
            monkeypatch.setenv(key, value)
        import app.config as config

        return importlib.reload(config).COOKIE_SECURE

    def test_off_by_default(self, backend, monkeypatch):
        assert self._secure(monkeypatch) is False

    def test_https_alone_turns_it_on(self, backend, monkeypatch):
        assert self._secure(monkeypatch, HTTPS_TERMINATED="1") is True

    def test_cookie_secure_alone_turns_it_on(self, backend, monkeypatch):
        """For TLS terminated further out, by something this stack does not
        know about."""
        assert self._secure(monkeypatch, COOKIE_SECURE="1") is True

    def test_a_stale_zero_cannot_take_it_away(self, backend, monkeypatch):
        """THE BUG. No deployment wants TLS and a cookie in clear text, so
        refusing to be talked down costs nothing - and a 0 left in an old .env
        is exactly how it would otherwise happen."""
        assert self._secure(
            monkeypatch, HTTPS_TERMINATED="1", COOKIE_SECURE="0"
        ) is True

    def test_the_compose_file_passes_it_through(self, compose):
        block = _service(compose, "backend")
        assert "HTTPS_TERMINATED=${HTTPS_TERMINATED:-0}" in block
