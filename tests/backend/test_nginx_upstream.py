"""nginx must survive the backend moving.

nginx resolves an upstream host once, when the configuration loads, and keeps
that address for the life of the process. On Docker a recreated backend gets a
new IP, so every proxied request 502s until nginx is restarted too - an
ordinary backend deploy becomes a site outage, and the site looks broken
rather than briefly unavailable.

Measured: with the backend moved from 172.23.0.3 to 172.23.0.7 and nginx left
alone, /api, /media and the UI WebSocket all answered normally.

The fix is two things that only work together - a resolver, and a variable in
proxy_pass, because nginx only re-resolves when the name comes from one. Half
of it is silently useless, which is why this is a test rather than a comment.
"""

import re
from pathlib import Path

import pytest

TEMPLATE = (
    Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf.template"
)


@pytest.fixture(scope="module")
def conf() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_a_resolver_is_configured(conf):
    """Without one, a name in proxy_pass fails to load the config at all."""
    assert re.search(r"^\s*resolver\s+\S+", conf, re.MULTILINE)


def test_the_resolver_expires_its_answers(conf):
    """A cached answer that never expires is the bug this fixes, one level down."""
    match = re.search(r"^\s*resolver\s+([^;]+);", conf, re.MULTILINE)
    assert match and "valid=" in match.group(1), (
        "resolver must set valid= or it caches the address indefinitely"
    )


def test_every_proxy_pass_goes_through_a_variable(conf):
    """This is the half that actually forces re-resolution.

    `proxy_pass http://backend:8000;` is resolved once at startup no matter
    what the resolver says. Only a variable defers it to request time.
    """
    targets = re.findall(r"^\s*proxy_pass\s+([^;]+);", conf, re.MULTILINE)

    assert targets, "no proxy_pass found - has the config been restructured?"
    for target in targets:
        assert target.lstrip().startswith("$"), (
            f"proxy_pass {target!r} names the host directly, so nginx will "
            "resolve it once at startup and keep the address forever"
        )


def test_the_uri_is_passed_on_explicitly(conf):
    """A variable in proxy_pass stops nginx appending the URI by itself.

    Left off, every proxied request arrives at the backend as "/" - which
    fails in a way that looks like a routing bug rather than a proxy one.
    """
    targets = re.findall(r"^\s*proxy_pass\s+([^;]+);", conf, re.MULTILINE)

    for target in targets:
        assert "$request_uri" in target, (
            f"proxy_pass {target!r} would drop the path"
        )


class TestTheAgentChannelStaysBlocked:
    """Changing how proxying works must not open the door it was hiding.

    The agent channel is reachable only on the internal network; anything
    arriving at nginx for it is refused. Verified live after the change:
    /ws/agent still answered 403 while /api and /media answered normally.
    """

    def test_the_exact_path_is_refused(self, conf):
        assert re.search(r"location\s*=\s*/ws/agent\s*\{\s*return\s+403;", conf)

    def test_paths_beneath_it_are_refused(self, conf):
        assert re.search(r"location\s*~\s*\^/ws/agent.*\{\s*return\s+403;", conf)

    def test_neither_block_proxies_anything(self, conf):
        """A block that forwarded instead of refusing would expose the channel."""
        for block in re.findall(r"location[^{]*ws/agent[^{]*\{([^}]*)\}", conf):
            assert "proxy_pass" not in block
