"""Player behaviour: seeking, and draw mode not turning itself on.

These are the two bugs D1/D2 were about, so they are asserted directly in a
real browser rather than inferred from the code.

The fixture seeds a chat that already points at a rendered video, so the suite
never spends LLM quota or minutes of render time just to get a <video> on the
screen.
"""

import json
import re
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


def _mongo_eval(script: str) -> str:
    """Run a mongosh snippet inside the stack's mongo container."""
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "mongo", "mongosh", "anyq_db", "--quiet", "--eval", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mongosh failed: {result.stderr[-400:]}")
    return result.stdout.strip()


def _existing_video() -> str:
    """Any already-rendered video in the shared media volume."""
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "sh", "-c",
         "ls -S /app/media/outputs/*.mp4 2>/dev/null | head -1"],
        capture_output=True, text=True, timeout=60,
    )
    name = result.stdout.strip().rsplit("/", 1)[-1]
    if not name.endswith(".mp4"):
        pytest.skip("no rendered video in the media volume to play")
    return name


@pytest.fixture(scope="module")
def seeded_chat():
    """A user whose first chat already contains a video message."""
    import httpx

    video = _existing_video()
    username = f"play_{uuid.uuid4().hex[:8]}"

    with httpx.Client(base_url=BASE, timeout=30) as hx:
        response = hx.post("/api/auth/signup", json={"username": username, "password": PASSWORD})
        assert response.status_code == 201, response.text
        user_id = response.json()["user"]["id"]

    payload = json.dumps({"user_id": user_id, "video": f"/media/{video}"})
    chat_id = _mongo_eval(
        f"const p = {payload};"
        "const now = new Date();"
        "const chat = db.chats.insertOne({user_id: p.user_id, title: 'Seek test',"
        "  current_video_url: p.video, created_at: now, updated_at: now});"
        "const cid = String(chat.insertedId);"
        "db.messages.insertOne({chat_id: cid, role: 'user', content: 'Explain gravity',"
        "  screenshots: [], video_url: null, timestamp: now});"
        "db.messages.insertOne({chat_id: cid, role: 'assistant', content: 'Here is the explanation.',"
        "  screenshots: [], video_url: p.video, timestamp: now});"
        "print(cid);"
    ).splitlines()[-1].strip()

    return {"username": username, "chat_id": chat_id, "video": video}


@pytest.fixture
def player_page(seeded_chat):
    """A logged-in browser sitting on the seeded chat, video metadata loaded."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        page.set_default_timeout(20000)

        page.goto(BASE)
        page.get_by_placeholder("Enter username").fill(seeded_chat["username"])
        page.get_by_placeholder("Enter password").fill(PASSWORD)
        page.locator("form").get_by_role("button", name="Sign In").click()

        page.wait_for_selector('[data-testid="video-element"]', timeout=30000)
        # Seeking is impossible until the duration is known.
        page.wait_for_function(
            """() => {
                const v = document.querySelector('[data-testid="video-element"]');
                return v && Number.isFinite(v.duration) && v.duration > 0;
            }""",
            timeout=30000,
        )
        yield page
        browser.close()


# ============== D2: draw mode must be explicit ==============
def test_canvas_ignores_the_pointer_until_draw_mode_is_on(player_page):
    canvas = player_page.locator('[data-testid="annotation-canvas"]')
    assert canvas.get_attribute("data-active") == "false"
    assert canvas.evaluate("el => getComputedStyle(el).pointerEvents") == "none"


def test_pausing_does_not_enable_drawing(player_page):
    """The original bug: a paused video handed every click to the brush."""
    player_page.evaluate("document.querySelector('[data-testid=\"video-element\"]').pause()")
    player_page.wait_for_timeout(300)

    canvas = player_page.locator('[data-testid="annotation-canvas"]')
    assert canvas.get_attribute("data-active") == "false", "pausing must not start draw mode"
    assert canvas.evaluate("el => getComputedStyle(el).pointerEvents") == "none"


def test_clicking_a_paused_video_resumes_playback(player_page):
    """Previously the canvas swallowed this click and drew a line instead.

    Clicks by coordinate rather than at a locator, so whatever element is
    actually on top receives it - which is the whole question here. With draw
    mode off the topmost thing is the play overlay; when the canvas was armed
    by pause alone, it was the canvas, and the click drew instead of playing.
    """
    player_page.evaluate("document.querySelector('[data-testid=\"video-element\"]').pause()")
    player_page.wait_for_timeout(300)

    box = player_page.locator('[data-testid="video-element"]').bounding_box()
    player_page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    player_page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"video-element\"]').paused",
        timeout=5000,
    )

    # And nothing was drawn: the annotation layer is still untouched.
    drawn = player_page.evaluate(
        """() => {
            const c = document.querySelector('[data-testid="annotation-canvas"]');
            if (!c || !c.width) return false;
            const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) return true;
            return false;
        }"""
    )
    assert not drawn, "the click left a stroke on the canvas instead of playing"


def test_draw_mode_toggle_arms_the_canvas_and_pauses(player_page):
    player_page.evaluate("document.querySelector('[data-testid=\"video-element\"]').play()")
    player_page.wait_for_timeout(400)

    player_page.locator('[data-testid="draw-mode-toggle"]').click()
    player_page.wait_for_timeout(300)

    canvas = player_page.locator('[data-testid="annotation-canvas"]')
    assert canvas.get_attribute("data-active") == "true"
    assert canvas.evaluate("el => getComputedStyle(el).pointerEvents") == "auto"
    # Turning drawing on pauses, because annotating a moving picture is useless.
    assert player_page.evaluate(
        "document.querySelector('[data-testid=\"video-element\"]').paused"
    )


def test_draw_mode_can_be_switched_off_again(player_page):
    toggle = player_page.locator('[data-testid="draw-mode-toggle"]')
    toggle.click()
    player_page.wait_for_timeout(200)
    toggle.click()
    player_page.wait_for_timeout(200)

    canvas = player_page.locator('[data-testid="annotation-canvas"]')
    assert canvas.get_attribute("data-active") == "false"


# ============== D1: the scrub bar ==============
def _current_time(page) -> float:
    return page.evaluate("document.querySelector('[data-testid=\"video-element\"]').currentTime")


def test_clicking_the_bar_seeks(player_page):
    bar = player_page.locator('[data-testid="seek-bar"]')
    box = bar.bounding_box()
    bar.click(position={"x": box["width"] * 0.6, "y": box["height"] / 2})
    player_page.wait_for_timeout(600)
    assert _current_time(player_page) > 0.1, "clicking the bar did not move the playhead"


def test_release_outside_the_bar_does_not_freeze_it(player_page):
    """The regression that made the scrub bar stop responding.

    The old bar cleared its "seeking" flag from `mouseup` ON the input, so a
    release anywhere else - routine while dragging - left the flag stuck and
    `timeupdate` never wrote currentTime again. Pointer capture fixes it; this
    drags off the element and releases far away, then checks the bar still
    tracks playback.
    """
    bar = player_page.locator('[data-testid="seek-bar"]')
    box = bar.bounding_box()
    mouse = player_page.mouse

    mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] / 2)
    mouse.down()
    mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] / 2, steps=8)
    # Leave the element entirely before releasing.
    mouse.move(box["x"] + box["width"] * 0.5, box["y"] - 250, steps=8)
    mouse.up()
    player_page.wait_for_timeout(300)

    after_drag = _current_time(player_page)
    assert after_drag > 0.1, "the drag itself did not seek"

    # The real check: playback still advances the displayed position.
    player_page.evaluate("document.querySelector('[data-testid=\"video-element\"]').play()")
    player_page.wait_for_function(
        f"() => document.querySelector('[data-testid=\"video-element\"]').currentTime > {after_drag + 0.3}",
        timeout=10000,
    )

    label = player_page.locator('[data-testid="seek-bar"]').locator("xpath=..").inner_text()
    assert re.search(r"\d+:\d{2}", label), "the bar lost its time readout"

    reported = float(player_page.locator('[data-testid="seek-bar"]').get_attribute("aria-valuenow"))
    playhead = _current_time(player_page)
    assert abs(reported - playhead) <= 2, (
        f"the bar froze at {reported}s while the video is at {playhead:.1f}s"
    )


def test_keyboard_seeking_works_on_the_focused_bar(player_page):
    player_page.evaluate("document.querySelector('[data-testid=\"video-element\"]').pause()")
    bar = player_page.locator('[data-testid="seek-bar"]')
    bar.focus()
    before = _current_time(player_page)

    bar.press("ArrowRight")
    player_page.wait_for_timeout(400)
    after = _current_time(player_page)

    assert after > before, "ArrowRight did not seek forward"


def test_the_bar_exposes_its_state_to_assistive_tech(player_page):
    bar = player_page.locator('[data-testid="seek-bar"]')
    assert bar.get_attribute("role") == "slider"
    assert bar.get_attribute("aria-label")
    assert float(bar.get_attribute("aria-valuemax")) > 0


# ============== drawing, undo/redo and screenshots ==============
def _draw_a_stroke(page):
    canvas = page.locator('[data-testid="annotation-canvas"]')
    box = canvas.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx - 60, cy - 20)
    page.mouse.down()
    page.mouse.move(cx + 60, cy + 20, steps=10)
    page.mouse.up()
    page.wait_for_timeout(300)


def test_drawing_marks_the_canvas_and_enables_undo(player_page):
    player_page.locator('[data-testid="draw-mode-toggle"]').click()
    player_page.wait_for_timeout(300)
    _draw_a_stroke(player_page)

    painted = player_page.evaluate(
        """() => {
            const c = document.querySelector('[data-testid="annotation-canvas"]');
            const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) return true;
            return false;
        }"""
    )
    assert painted, "the stroke did not reach the canvas"
    assert player_page.get_by_title("Undo (Ctrl+Z)").first.is_enabled()


def test_undo_then_redo_round_trips(player_page):
    player_page.locator('[data-testid="draw-mode-toggle"]').click()
    player_page.wait_for_timeout(300)
    _draw_a_stroke(player_page)

    def painted():
        return player_page.evaluate(
            """() => {
                const c = document.querySelector('[data-testid="annotation-canvas"]');
                const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) return true;
                return false;
            }"""
        )

    assert painted()
    player_page.get_by_title("Undo (Ctrl+Z)").first.click()
    player_page.wait_for_timeout(300)
    assert not painted(), "undo left the stroke on the canvas"

    player_page.get_by_title("Redo (Ctrl+Y)").first.click()
    player_page.wait_for_timeout(300)
    assert painted(), "redo did not bring the stroke back"


def test_screenshot_attaches_a_thumbnail(player_page):
    player_page.locator('[data-testid="draw-mode-toggle"]').click()
    player_page.wait_for_timeout(300)
    _draw_a_stroke(player_page)

    player_page.locator('[data-testid="add-screenshot"]').click()
    player_page.wait_for_timeout(800)

    thumbs = player_page.locator('img[src^="data:"]')
    assert thumbs.count() >= 1, "no screenshot thumbnail appeared"
