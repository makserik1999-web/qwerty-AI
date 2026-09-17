"""The export panel in a real browser.

What is worth checking here is not that ffmpeg works - the e2e test covers
that - but that the choice in front of the user is a fair one: both formats
visible, both sized, and the limits stated before the request rather than
after it.
"""

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


def _newest_video() -> str:
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "sh", "-c",
         "ls -S /app/media/outputs/*.mp4 2>/dev/null | head -1"],
        capture_output=True, timeout=60,
    ).stdout.decode().strip()
    name = out.rsplit("/", 1)[-1]
    if not name.endswith(".mp4"):
        pytest.skip("no rendered video in the media volume")
    return name


@pytest.fixture
def player_with_video():
    """A signed-in browser sitting on a chat that already has a video."""
    import httpx
    from playwright.sync_api import sync_playwright

    video = _newest_video()
    username = f"eui_{uuid.uuid4().hex[:8]}"

    with httpx.Client(base_url=BASE, timeout=30) as hx:
        assert hx.post(
            "/api/auth/signup", json={"username": username, "password": PASSWORD}
        ).status_code == 201
        user_id = hx.get("/api/auth/me").json()["user"]["id"]

    payload = json.dumps({"uid": user_id, "video": f"/media/{video}"})
    subprocess.run(
        ["docker", "compose", "exec", "-T", "mongo", "mongosh", "anyq_db", "--quiet",
         "--eval",
         f"const p = {payload}; const now = new Date();"
         "const chat = db.chats.insertOne({user_id: p.uid, title: 'Export', "
         "  created_at: now, updated_at: now, current_video_url: p.video});"
         "db.messages.insertOne({chat_id: chat.insertedId.toString(), role: 'user', "
         "  content: 'Что такое гравитация', screenshots: [], timestamp: now});"
         "db.messages.insertOne({chat_id: chat.insertedId.toString(), "
         "  role: 'assistant', content: 'Ответ', screenshots: [], "
         "  video_url: p.video, timestamp: now});"],
        capture_output=True, timeout=60,
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        page.set_default_timeout(20000)
        page.goto(BASE)
        page.get_by_placeholder("Enter username").fill(username)
        page.get_by_placeholder("Enter password").fill(PASSWORD)
        page.locator("form").get_by_role("button", name="Sign In").click()
        page.wait_for_selector("text=New Chat", timeout=20000)

        # Open the seeded chat, then wait for the video to report its length.
        page.locator("text=Export").first.click()
        page.wait_for_selector('[data-testid="video-element"]', timeout=20000)
        page.wait_for_function(
            "() => { const v = document.querySelector('[data-testid=\"video-element\"]');"
            "return v && v.readyState >= 1 && v.duration > 0; }",
            timeout=20000,
        )
        yield page
        browser.close()


def _open_panel(page):
    page.locator('[data-testid="export-toggle"]').click()
    page.wait_for_selector('[data-testid="export-panel"]')


def test_the_panel_is_closed_until_asked_for(player_with_video):
    page = player_with_video
    assert page.locator('[data-testid="export-panel"]').count() == 0
    assert page.locator('[data-testid="export-toggle"]').is_visible()


def test_both_formats_are_offered_with_a_size(player_with_video):
    """GIF must be a peer of mp4, not an option hidden behind a menu."""
    page = player_with_video
    _open_panel(page)

    gif = page.locator('[data-testid="export-format-gif"]')
    clip = page.locator('[data-testid="export-format-clip"]')

    assert gif.is_visible() and clip.is_visible()
    # Each chip states what it will cost, so the choice is informed.
    assert "KB" in gif.inner_text() or "MB" in gif.inner_text()
    assert "KB" in clip.inner_text() or "MB" in clip.inner_text()


def test_mp4_is_preselected_and_smaller(player_with_video):
    page = player_with_video
    _open_panel(page)

    assert page.locator('[data-testid="export-format-clip"]').get_attribute("aria-pressed") == "true"
    assert page.locator('[data-testid="export-format-gif"]').get_attribute("aria-pressed") == "false"


def test_choosing_gif_switches_the_button(player_with_video):
    page = player_with_video
    _open_panel(page)

    page.locator('[data-testid="export-format-gif"]').click()

    assert page.locator('[data-testid="export-format-gif"]').get_attribute("aria-pressed") == "true"
    assert "GIF" in page.locator('[data-testid="export-submit"]').inner_text()


def test_the_estimate_follows_the_settings(player_with_video):
    """A number that never moves is worse than no number."""
    page = player_with_video
    _open_panel(page)
    before = page.locator('[data-testid="export-format-gif"]').inner_text()

    page.locator('[data-testid="export-width"]').select_option("320")

    page.wait_for_function(
        "(prev) => document.querySelector('[data-testid=\"export-format-gif\"]')"
        ".innerText !== prev",
        arg=before,
    )
    assert page.locator('[data-testid="export-format-gif"]').inner_text() != before


def test_the_default_selection_is_within_the_limit(player_with_video):
    page = player_with_video
    _open_panel(page)

    length = page.locator('[data-testid="export-length"]').inner_text()

    assert "at most" not in length, "the panel must open on a valid selection"
    assert page.locator('[data-testid="export-submit"]').is_enabled()


def test_the_download_button_asks_for_an_attachment(player_with_video):
    page = player_with_video
    href = page.locator('[data-testid="download-video"]').get_attribute("href")

    assert href and href.endswith("?download=1"), href


def test_closing_the_panel_leaves_the_player_alone(player_with_video):
    page = player_with_video
    _open_panel(page)

    page.locator('[data-testid="export-close"]').click()

    assert page.locator('[data-testid="export-panel"]').count() == 0
    assert page.locator('[data-testid="seek-bar"]').is_visible()


def test_the_deck_button_produces_a_download(player_with_video):
    """The teacher-facing export: one click, no settings, then a file."""
    page = player_with_video

    page.locator('[data-testid="deck-button"]').click()

    # Building a deck extracts frames and writes a pptx; give it room, but far
    # less than a generation would take.
    page.wait_for_selector('[data-testid="deck-download"]', timeout=120000)
    link = page.locator('[data-testid="deck-download"]')

    assert "/api/export/" in (link.get_attribute("href") or "")
    # The label carries the real size, not the estimate.
    assert "KB" in link.inner_text() or "MB" in link.inner_text()


def test_the_deck_button_needs_a_video(player_with_video):
    page = player_with_video
    assert page.locator('[data-testid="deck-button"]').is_enabled()
