"""What a cached answer looks like to the person who asked.

An answer that normally takes minutes arriving in milliseconds needs saying so,
and the reader must be able to reject it and ask for a fresh one - otherwise
the cache silently decides what they are allowed to see.
"""

import hashlib
import json
import subprocess
import uuid

import pytest

pytestmark = [
    pytest.mark.ui,
    pytest.mark.skipif(
        not __import__("os").environ.get("ANYQ_STACK_UP"),
        reason="needs the docker stack on :3000 - run `make up` and set ANYQ_STACK_UP=1",
    ),
]

BASE = "http://localhost:3000"
PASSWORD = "password123"
CACHED_TEXT = "Photosynthesis, straight from the library."


def _compose(*args, timeout=60):
    return subprocess.run(
        ["docker", "compose", *args], capture_output=True, text=True, timeout=timeout
    )


def _existing_video() -> str:
    out = _compose("exec", "-T", "backend", "sh", "-c",
                   "ls -S /app/media/outputs/*.mp4 2>/dev/null | head -1").stdout
    name = out.strip().rsplit("/", 1)[-1]
    if not name.endswith(".mp4"):
        pytest.skip("no rendered video in the media volume")
    return name


@pytest.fixture(scope="module")
def seeded_answer():
    """A library entry for a question no other test asks."""
    video = _existing_video()
    # Matches what the normaliser produces for "Explain <topic>".
    topic = f"topic{uuid.uuid4().hex[:8]}"
    key = hashlib.sha256(f"{topic}|v1".encode()).hexdigest()

    payload = json.dumps({"key": key, "norm": topic, "video": f"/media/{video}", "text": CACHED_TEXT})
    _compose("exec", "-T", "mongo", "mongosh", "anyq_db", "--quiet", "--eval",
             f"const p = {payload}; const now = new Date();"
             "db.library_entries.updateOne({cache_key: p.key}, {$set: {cache_key: p.key,"
             "  normalized_question: p.norm, educator_text: p.text, video_url: p.video,"
             "  tier: 'warm', pipeline_version: 'v1',"
             "  expires_at: new Date(Date.now() + 30*864e5), last_hit_at: now},"
             "$setOnInsert: {created_at: now, hits: 0}}, {upsert: true});")
    return {"question": f"Explain {topic}", "video": video}


@pytest.fixture
def signed_in(seeded_answer):
    from playwright.sync_api import sync_playwright
    import httpx

    username = f"cui_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE, timeout=30) as hx:
        assert hx.post(
            "/api/auth/signup", json={"username": username, "password": PASSWORD}
        ).status_code == 201

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        page.set_default_timeout(20000)
        page.goto(BASE)
        page.get_by_placeholder("Enter username").fill(username)
        page.get_by_placeholder("Enter password").fill(PASSWORD)
        page.locator("form").get_by_role("button", name="Sign In").click()
        page.wait_for_selector("text=New Chat", timeout=20000)
        yield page, seeded_answer
        browser.close()


def _ask(page, question):
    page.get_by_placeholder("Ask about the video or a topic...").fill(question)
    page.get_by_role("button", name="Send").click()


def test_a_cached_answer_is_labelled_and_arrives_at_once(signed_in):
    page, seeded = signed_in
    _ask(page, seeded["question"])

    # Ten seconds is far below what a real generation costs, so passing this
    # also proves the agent was never involved.
    page.wait_for_selector('[data-testid="from-cache-badge"]', timeout=10000)

    assert CACHED_TEXT in page.locator("body").inner_text()
    assert "From the library" in page.locator('[data-testid="from-cache-badge"]').inner_text()


def test_the_reader_can_ask_for_a_fresh_answer(signed_in):
    """The cache must be an offer, not a verdict."""
    page, seeded = signed_in
    _ask(page, seeded["question"])
    page.wait_for_selector('[data-testid="from-cache-badge"]', timeout=10000)

    regenerate = page.locator('[data-testid="regenerate-button"]').first
    assert regenerate.is_visible(), "a cached answer must offer a way to bypass it"

    regenerate.click()
    # The bypass goes to the agent, so the request is now genuinely in flight:
    # the loading indicator appearing is the proof the cache was skipped.
    page.wait_for_selector("text=Generating", timeout=15000)


def test_an_uncached_question_carries_no_badge(signed_in):
    page, _ = signed_in
    _ask(page, f"Explain {uuid.uuid4().hex[:10]}")
    page.wait_for_timeout(3000)
    assert page.locator('[data-testid="from-cache-badge"]').count() == 0
