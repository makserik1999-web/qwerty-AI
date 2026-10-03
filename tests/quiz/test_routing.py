"""How requests reach the quiz service, read off the nginx template.

Three properties nothing else would catch until a class was waiting:

  - the quiz prefixes go to the quiz service and nothing else does - in
    particular /api/quiz-drafts, which is the backend's;
  - X-Real-IP is set on every quiz route, because the join limits key on it
    and the client-written X-Forwarded-For is exactly what they must not trust;
  - the live channel is proxied as a WebSocket.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def conf() -> str:
    return (ROOT / "frontend" / "nginx.conf.template").read_text(encoding="utf-8")


def _block(conf: str, prefix: str) -> str:
    match = re.search(r"location \^~ " + re.escape(prefix) + r" \{(.*?)\n    \}", conf, re.S)
    assert match, f"no location for {prefix}"
    return match.group(1)


@pytest.mark.parametrize("prefix", ["/api/quiz/", "/api/play/", "/ws/quiz/"])
def test_each_quiz_prefix_goes_to_the_quiz_service(conf, prefix):
    block = _block(conf, prefix)
    assert "proxy_pass $quiz$request_uri;" in block
    assert "proxy_set_header X-Real-IP $remote_addr;" in block


def test_drafts_are_not_caught_by_the_quiz_prefix(conf):
    """The trailing slash is what keeps /api/quiz-drafts on the backend."""
    assert "location ^~ /api/quiz/ {" in conf
    assert "location ^~ /api/quiz {" not in conf


def test_the_live_channel_is_upgraded(conf):
    block = _block(conf, "/ws/quiz/")
    assert "proxy_set_header Upgrade $http_upgrade;" in block
    assert 'proxy_set_header Connection "upgrade";' in block


def test_the_quiz_address_is_a_variable(conf):
    assert re.search(r"^\s*set \$quiz \$\{QUIZ_URL\};", conf, re.M)


def test_the_image_defines_what_the_template_needs():
    """The nginx image only substitutes variables that exist; an undefined
    ${QUIZ_URL} would reach nginx literally and stop it loading."""
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "ENV QUIZ_URL=" in dockerfile


def test_the_dev_server_sends_quiz_paths_to_the_quiz_service():
    vite = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    quiz_at = vite.index("'/api/quiz/'")
    assert quiz_at < vite.index("'/api':"), "the generic /api entry would win"
    assert vite.index("'/ws/quiz/'") < vite.index("'/ws':")
