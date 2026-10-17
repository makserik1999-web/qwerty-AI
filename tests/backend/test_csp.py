"""The page must be allowed to load the things it actually loads.

A Content-Security-Policy that forbids something the page needs fails in the
quietest way there is: the browser drops the resource, logs to a console nobody
is watching, and renders a page that looks almost right. Nothing 500s, no test
goes red, and `npm run dev` is clean because the dev server sends no CSP at all
- the policy only exists in nginx, which only runs in Docker.

Both allowances checked here were found that way, by reading the config rather
than by anything failing:

- the interface asks for Inter from fonts.googleapis.com, and the policy listed
  neither that host nor fonts.gstatic.com, so every font quietly fell back to
  the system stack in production;
- index.html runs one inline script to set the theme before the first paint,
  and `script-src 'self'` blocks inline scripts, so the page loaded light and
  flipped to dark once React mounted - the exact flash the script prevents.

The hash test below is the one that earns its place over time. It is easy to
edit that script - even its comment - and never think about nginx; the hash
then no longer matches, the browser blocks the script, and the only symptom is
a flicker on load.
"""

import base64
import hashlib
import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
TEMPLATE = FRONTEND / "nginx.conf.template"
INDEX = FRONTEND / "index.html"


@pytest.fixture(scope="module")
def policy() -> str:
    conf = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]+)"', conf)
    assert match, "no Content-Security-Policy header found in the nginx template"
    return match.group(1)


def directive(policy: str, name: str) -> str:
    for part in policy.split(";"):
        part = part.strip()
        if part.split(" ")[0] == name:
            return part
    raise AssertionError(f"{name} is not set; it falls back to default-src")


# ------------------------------------------------------------------ fonts --


def test_the_font_stylesheet_host_is_allowed(policy):
    assert "https://fonts.googleapis.com" in directive(policy, "style-src"), (
        "index.html links a stylesheet from fonts.googleapis.com; without the "
        "host in style-src the browser drops it and every face falls back"
    )


def test_the_font_files_host_is_allowed(policy):
    """The stylesheet loading is only half of it - the .woff2 files come from
    a different host, and allowing one without the other still gives no fonts."""
    assert "https://fonts.gstatic.com" in directive(policy, "font-src")


# ------------------------------------------------- the theme script's hash --


def inline_scripts() -> list[str]:
    raw = INDEX.read_bytes()
    assert b"\r\n" not in raw, (
        "index.html has CRLF line endings. The browser hashes the bytes it "
        "receives, so the same commit would produce a different hash here than "
        "on Linux. .gitattributes pins this file to LF - re-checkout it."
    )
    return re.findall(r"<script>(.*?)</script>", raw.decode("utf-8"), re.S)


def sha256_source(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode()


def test_every_inline_script_is_allowed_by_its_hash(policy):
    scripts = inline_scripts()
    assert scripts, "no inline script in index.html - has the theme script moved?"

    allowed = directive(policy, "script-src")
    for source in scripts:
        expected = sha256_source(source)
        assert expected in allowed, (
            "the inline script in frontend/index.html is not permitted by the "
            "policy, so the browser will refuse to run it and the page will "
            "flash the light theme on the way to dark.\n\n"
            f"Put this in script-src in frontend/nginx.conf.template:\n\n"
            f"    '{expected}'\n"
        )


def test_inline_scripts_are_not_allowed_wholesale(policy):
    """A hash permits one known script; 'unsafe-inline' permits every future one.

    If the hash ever becomes annoying to maintain, this is the shortcut that
    will look tempting - and it would also allow anything an injection manages
    to place on the page.
    """
    assert "'unsafe-inline'" not in directive(policy, "script-src")


# ---------------------------------------------------------- what stays shut --


class TestTheRestOfThePolicyIsUnchanged:
    """Adding two hosts must not quietly relax anything else."""

    def test_the_page_cannot_be_framed(self, policy):
        assert "frame-ancestors 'none'" in policy

    def test_only_first_party_code_runs(self, policy):
        """No CDN, no analytics: everything the page executes ships with it."""
        script_src = directive(policy, "script-src")
        assert "http://" not in script_src
        assert "https://" not in script_src

    def test_sockets_stay_same_origin(self, policy):
        connect = directive(policy, "connect-src")
        assert "'self'" in connect
        assert "https://" not in connect
