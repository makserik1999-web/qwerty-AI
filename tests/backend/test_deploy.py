"""The production deployment: one VPS, docker-compose.prod.yml, deploy/.

Each of these is a way a server comes up quietly wrong rather than failing:
a fresh database nobody can log in to, a certificate nginx never picks up
again, a renewal answered with the SPA's index.html, a backup service holding
the root password, a clone that cannot build because a file never reached
git. They read the files rather than a running stack, like
test_transport_security.py, so they run in the suite that actually gets run.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
PROD = ROOT / "docker-compose.prod.yml"
TLS_SCRIPT = ROOT / "frontend" / "docker-entrypoint.d" / "15-anyq-tls.sh"
TEMPLATE = ROOT / "frontend" / "nginx.conf.template"
DEPLOY = ROOT / "deploy"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _service(compose: str, name: str) -> str:
    """One service's block, from its key to the next two-space key."""
    found = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", compose, re.DOTALL | re.M)
    assert found, f"no {name} service"
    return found.group(1)


@pytest.fixture(scope="module")
def prod() -> str:
    return _read(PROD).replace("\r\n", "\n")


# ------------------------------------------------------------- database --


class TestAFreshDatabaseHasItsAppUser:
    """The mongo image creates the root user on an empty volume and nothing
    else. Every service logs in as the app user - so before the init script,
    a new server's backend was refused by its own database and the site never
    came up."""

    def test_the_init_script_is_mounted(self):
        mongo = _service(_read(COMPOSE).replace("\r\n", "\n"), "mongo")
        assert "./scripts/mongo-init:/docker-entrypoint-initdb.d:ro" in mongo

    def test_mongo_is_given_the_app_credentials(self):
        mongo = _service(_read(COMPOSE).replace("\r\n", "\n"), "mongo")
        assert "MONGO_APP_USER=" in mongo and "MONGO_APP_PASSWORD=" in mongo

    def test_the_user_gets_readwrite_on_one_database_and_nothing_more(self):
        script = _read(ROOT / "scripts" / "mongo-init" / "10-app-user.js")
        assert 'role: "readWrite", db: dbName' in script
        assert "root" not in re.sub(r"//.*", "", script), "the app user must not be root"

    def test_the_password_is_read_from_the_environment(self):
        script = _read(ROOT / "scripts" / "mongo-init" / "10-app-user.js")
        assert "process.env.MONGO_APP_PASSWORD" in script


# ---------------------------------------------------------- certificate --


class TestTheCertificate:
    def test_it_replaces_the_development_mount(self, prod):
        """Compose merges volumes by target. A different target would mount
        both, and nginx would go on reading the development directory."""
        frontend = _service(prod, "frontend")
        assert "letsencrypt:/etc/nginx/certs:ro" in frontend
        assert ":/etc/nginx/certs:ro" in _service(_read(COMPOSE).replace("\r\n", "\n"), "frontend")

    def test_nginx_looks_where_certbot_writes(self, prod):
        """init-tls.sh names the certificate; the path nginx is given has to be
        that name. Two files that must agree, so one test reads both."""
        name = re.search(r"--cert-name (\w+)", _read(DEPLOY / "init-tls.sh")).group(1)
        assert f"TLS_CERT_DIR=/etc/nginx/certs/live/{name}" in _service(prod, "frontend")

    def test_nginx_reloads_when_it_is_renewed(self):
        """nginx reads the certificate once. Without a reload it serves the
        old one until the day it expires, renewals notwithstanding."""
        script = _read(TLS_SCRIPT)
        assert "nginx -s reload" in script
        assert "cksum" in script

    def test_certbot_is_kept_off_the_internal_network(self, prod):
        """It talks to Let's Encrypt and to nothing in the stack."""
        assert not re.search(r"^\s+networks:", _service(prod, "certbot"), re.M)


class TestTheRenewalCheckGetsTheToken:
    """Let's Encrypt fetches /.well-known/acme-challenge/<token> over plain
    HTTP. Answered by the SPA fallback it gets index.html; answered by a
    server-level `return 301` it never reaches a location at all."""

    def test_the_redirect_server_serves_the_challenge(self):
        script = _read(TLS_SCRIPT)
        redirect = script[script.index("redirect.conf\" <<'EOF'"):]
        redirect = redirect[: redirect.index("\nEOF")]
        assert "location ^~ /.well-known/acme-challenge/" in redirect
        assert "root /var/www/acme;" in redirect

    def test_the_301_is_inside_a_location(self):
        script = _read(TLS_SCRIPT)
        redirect = script[script.index("redirect.conf\" <<'EOF'"):]
        redirect = redirect[: redirect.index("\nEOF")]
        assert re.search(r"location / \{\s*return 301", redirect), redirect

    def test_plain_http_mode_serves_it_too(self):
        """The first certificate is issued with TLS still off."""
        assert "location ^~ /.well-known/acme-challenge/" in _read(TEMPLATE)

    def test_the_webroot_is_shared(self, prod):
        assert "acme_webroot:/var/www/acme:ro" in _service(prod, "frontend")
        assert "acme_webroot:/var/www/acme" in _service(prod, "certbot")


# --------------------------------------------------------------- backups --


class TestBackups:
    def test_they_never_hold_the_root_password(self, prod):
        for name in ("backup", "restore"):
            block = _service(prod, name)
            assert "MONGO_ROOT" not in block, name
            assert "MONGO_APP_USER" in block, name

    def test_they_live_outside_every_docker_volume(self, prod):
        """`docker compose down -v` must not take the backups with the data."""
        assert "${BACKUP_DIR:-/var/backups/anyq}:/backups" in _service(prod, "backup")

    def test_a_backup_that_stopped_is_unhealthy(self, prod):
        assert "backup.sh\", \"check\"" in _service(prod, "backup")

    def test_restore_only_runs_when_asked(self, prod):
        assert 'profiles: ["restore"]' in _service(prod, "restore")

    def test_old_dumps_are_pruned_only_after_a_good_one(self):
        script = _read(DEPLOY / "backup.sh")
        run_once = script[script.index("run_once() {"):]
        run_once = run_once[: run_once.index("\n}")]
        assert run_once.index("backup_db || return 1") < run_once.index("prune")


# --------------------------------------------------------------- the rest --


class TestTheServer:
    def test_every_production_setting_is_documented(self, prod):
        example = _read(ROOT / ".env.example")
        for key in set(re.findall(r"\$\{([A-Z_]+)", prod)):
            assert f"{key}=" in example, key

    def test_shell_scripts_are_checked_out_with_lf(self):
        """A CR at the end of a line is part of the command to bash on Linux."""
        assert re.search(r"^\*\.sh\s+text\s+eol=lf", _read(ROOT / ".gitattributes"), re.M)

    def test_deploy_checks_the_agent_channel_is_closed(self):
        assert re.search(r"expect 403 .*ws/agent", _read(DEPLOY / "deploy.sh"))

    @pytest.mark.skipif(not shutil.which("git"), reason="needs git")
    def test_nothing_the_build_needs_is_kept_out_of_git(self):
        """*.png in .gitignore kept the logo out of the repository, and a
        fresh clone - which is what a server builds from - could not build
        the frontend. A file that exists here but is ignored would do it
        again."""
        dirs = ["frontend/src", "frontend/public", "backend", "agent", "quiz", "exporter"]
        files = [
            str(p.relative_to(ROOT)).replace("\\", "/")
            for d in dirs if (ROOT / d).is_dir()
            for p in (ROOT / d).rglob("*")
            if p.is_file() and not any(
                part in {"node_modules", "__pycache__", "media", "logs", ".pytest_cache"}
                for part in p.relative_to(ROOT).parts)
            and p.suffix not in {".pyc"}
        ]
        # NUL-separated bytes: in text mode on Windows "\n" goes out as "\r\n",
        # git looks for paths ending in a CR, and nothing ever matches.
        result = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"], input="\0".join(files).encode(),
            capture_output=True, cwd=ROOT,
        )
        if result.returncode not in (0, 1):
            pytest.skip(f"not a git checkout: {result.stderr.decode(errors='replace').strip()}")
        ignored = [p for p in result.stdout.decode().split("\0") if p]
        assert ignored == [], ignored
