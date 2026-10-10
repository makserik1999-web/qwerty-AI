"""The production deployment: a home server behind a Cloudflare tunnel,
docker-compose.prod.yml, deploy/.

Each of these is a way a server comes up quietly wrong rather than failing:
a fresh database nobody can log in to, every visitor counted as one address,
a cookie without Secure, a port open that should not be, a mongo that will
not start on the box's CPU, a backup service holding the root password, a
clone that cannot build because a file never reached git. They read the files
rather than a running stack, like test_transport_security.py, so they run in
the suite that actually gets run.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
PROD = ROOT / "docker-compose.prod.yml"
LISTEN_SCRIPT = ROOT / "frontend" / "docker-entrypoint.d" / "15-anyq-listen.sh"
TEMPLATE = ROOT / "frontend" / "nginx.conf.template"
DEPLOY = ROOT / "deploy"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _service(compose: str, name: str) -> str:
    """One service's block, from its key to the next two-space key."""
    found = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", compose, re.DOTALL | re.M)
    assert found, f"no {name} service"
    return found.group(1)


def _services(compose: str) -> list:
    """The service names: the two-space keys under `services:`, up to the next
    top-level key (networks: and volumes: have two-space keys too)."""
    body = re.search(r"^services:\n(.*?)(?=^\S|\Z)", compose, re.S | re.M).group(1)
    return re.findall(r"^  ([a-z][a-z0-9_-]*):\n", body, re.M)


@pytest.fixture(scope="module")
def prod() -> str:
    return _read(PROD)


@pytest.fixture(scope="module")
def base() -> str:
    return _read(COMPOSE)


# ------------------------------------------------------------- database --


class TestAFreshDatabaseHasItsAppUser:
    """The mongo image creates the root user on an empty volume and nothing
    else. Every service logs in as the app user - so before the init script,
    a new server's backend was refused by its own database and the site never
    came up."""

    def test_the_init_script_is_mounted(self, base):
        assert "./scripts/mongo-init:/docker-entrypoint-initdb.d:ro" in _service(base, "mongo")

    def test_mongo_is_given_the_app_credentials(self, base):
        mongo = _service(base, "mongo")
        assert "MONGO_APP_USER=" in mongo and "MONGO_APP_PASSWORD=" in mongo

    def test_the_user_gets_readwrite_on_one_database_and_nothing_more(self):
        script = _read(ROOT / "scripts" / "mongo-init" / "10-app-user.js")
        assert 'role: "readWrite", db: dbName' in script
        assert "root" not in re.sub(r"//.*", "", script), "the app user must not be root"

    def test_the_password_is_read_from_the_environment(self):
        script = _read(ROOT / "scripts" / "mongo-init" / "10-app-user.js")
        assert "process.env.MONGO_APP_PASSWORD" in script


class TestMongoRunsOnTheBox:
    """The server is an Ivy Bridge i3: AVX, no AVX2. mongo 8 does not start
    there, and a floating tag would be a different database on the next pull."""

    def test_every_mongo_image_is_one_pinned_7_0_release(self, base, prod):
        tags = re.findall(r"image: mongo:(\S+)", base + prod)
        assert len(tags) == 3, tags  # mongo, backup, restore
        assert len(set(tags)) == 1, f"mongo, backup and restore differ: {tags}"
        assert re.fullmatch(r"7\.0\.\d+", tags[0]), tags[0]

    def test_production_still_requires_a_password(self, prod):
        """The prod command replaces the base one; --auth has to be in it."""
        assert '"--auth"' in _service(prod, "mongo")

    def test_the_cache_fits_the_container(self, prod):
        """WiredTiger sizes its cache from the machine's memory, not the
        container's 2 GB limit, and would be killed for going over it."""
        assert "--wiredTigerCacheSizeGB" in _service(prod, "mongo")


# --------------------------------------------------------------- tunnel --


class TestTheTunnel:
    def test_cloudflared_is_pinned(self, prod):
        image = re.search(r"image: (cloudflare/cloudflared:\S+)", _service(prod, "cloudflared")).group(1)
        assert re.search(r":\d{4}\.\d+\.\d+$", image), f"not a pinned release: {image}"

    def test_it_runs_the_token_from_env_and_never_updates_itself(self, prod):
        block = _service(prod, "cloudflared")
        assert '"tunnel", "--no-autoupdate"' in block and '"run"' in block
        assert "TUNNEL_TOKEN=${TUNNEL_TOKEN" in block

    def test_it_shares_the_network_with_the_frontend(self, prod):
        assert "anyq-network" in _service(prod, "cloudflared")

    def test_nginx_listens_where_the_route_points(self, prod):
        """The route in the Cloudflare dashboard is http://frontend:80."""
        assert "NGINX_PORT=80" in _service(prod, "frontend")

    def test_the_token_is_documented_and_left_for_a_human(self):
        assert "TUNNEL_TOKEN=" in _read(ROOT / ".env.example")
        assert 'set_var TUNNEL_TOKEN ""' in _read(DEPLOY / "init-env.sh")


class TestNothingIsPublished:
    """The tunnel dials out; nothing needs an open port. The one exception is
    the site on the loopback interface, for checking it from the box."""

    def test_only_the_frontend_on_loopback(self, prod):
        for name in _services(prod):
            block = _service(prod, name)
            if name == "frontend":
                assert "ports: !override" in block, "the development port would stay published"
                assert re.findall(r'^\s+- "([^"]+)"$', block[block.index("ports:"):], re.M)[0] == "127.0.0.1:8080:80"
            else:
                assert "ports:" not in block, name

    def test_the_database_publishes_nothing_anywhere(self, base):
        assert "ports:" not in _service(base, "mongo")


class TestTheClientAndTheScheme:
    def test_the_client_address_comes_from_cloudflare_in_production(self, prod):
        assert "TRUST_CF_CONNECTING_IP=1" in _service(prod, "frontend")

    def test_and_only_there(self):
        """Without the tunnel anybody could write that header."""
        assert "ENV TRUST_CF_CONNECTING_IP=0" in _read(ROOT / "frontend" / "Dockerfile")
        script = _read(LISTEN_SCRIPT)
        assert 'if [ "${TRUST_CF_CONNECTING_IP:-0}" = "1" ]' in script
        assert "real_ip_header CF-Connecting-IP;" in script
        assert "set_real_ip_from 0.0.0.0/0" not in script

    def test_the_real_ip_include_is_used(self):
        assert "include /etc/nginx/conf.d/real_ip.inc;" in _read(TEMPLATE)

    def test_the_incoming_scheme_is_passed_on(self):
        """Cloudflare says https; nginx itself only ever sees http."""
        conf = _read(TEMPLATE)
        assert "map $http_x_forwarded_proto $anyq_forwarded_proto" in conf
        assert "X-Forwarded-Proto $scheme;" not in conf
        assert conf.count("X-Forwarded-Proto $anyq_forwarded_proto;") >= 6

    def test_forwarded_for_is_replaced_not_appended(self):
        """An entry the client wrote is what --proxy-headers would report."""
        conf = _read(TEMPLATE)
        assert "$proxy_add_x_forwarded_for" not in conf
        assert "X-Forwarded-For $remote_addr;" in conf

    @pytest.mark.parametrize("service", ["backend", "quiz"])
    def test_uvicorn_reads_the_proxy_headers(self, service):
        dockerfile = _read(ROOT / service / "Dockerfile")
        cmd = dockerfile[dockerfile.rindex("CMD ["):]
        assert '"--proxy-headers"' in cmd and '"--forwarded-allow-ips", "*"' in cmd

    def test_production_sets_the_secure_cookie(self):
        init = _read(DEPLOY / "init-env.sh")
        assert "set_var COOKIE_SECURE 1" in init
        assert 'set_var CORS_ORIGINS "https://$domain"' in init


# --------------------------------------------------------- the box itself --


class TestTheBoxStaysUp:
    def test_every_lasting_service_restarts_itself(self, base, prod):
        """After a power cut everything has to come back without anybody."""
        for name in _services(base):
            assert "restart: unless-stopped" in _service(base, name), name
        for name in ("cloudflared", "backup"):
            assert "restart: unless-stopped" in _service(prod, name), name

    def test_every_service_rotates_its_logs(self, base, prod):
        names = set(_services(base)) | set(_services(prod))
        for name in names:
            block = (_service(prod, name) if name in _services(prod) else "") + (
                _service(base, name) if name in _services(base) else "")
            assert "logging: *logging" in block or 'max-size: "10m"' in block, name

    @pytest.mark.parametrize("service", ["agent", "exporter"])
    def test_rendering_yields_to_the_site(self, prod, service):
        block = _service(prod, service)
        assert "cpu_shares: 512" in block
        assert "cpus:" in block

    def test_renders_start_small(self):
        assert "set_var EFFORT_DEFAULT low" in _read(DEPLOY / "init-env.sh")

    def test_nothing_from_the_tls_setup_is_left(self, prod):
        assert "certbot" not in prod and "letsencrypt" not in prod
        assert not (DEPLOY / "init-tls.sh").exists()
        for script in DEPLOY.glob("*.sh"):
            assert "TLS_SERVER_NAME" not in _read(script), script.name

    def test_the_firewall_is_left_alone(self):
        """ufw, ssh and Tailscale are already set up on the box."""
        body = _read(DEPLOY / "prepare-server.sh")
        assert "ufw " not in re.sub(r"#.*", "", body)


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
        assert 'backup.sh", "check"' in _service(prod, "backup")

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
        body = _read(DEPLOY / "deploy.sh")
        assert re.search(r"local_status /ws/agent\)\" 403", body)
        assert re.search(r'public_status "https://\$domain/ws/agent"\)" 403', body)

    def test_deploy_checks_the_client_address(self):
        assert "CF-Connecting-IP: $probe" in _read(DEPLOY / "deploy.sh")

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
