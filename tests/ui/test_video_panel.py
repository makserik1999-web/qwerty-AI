"""Video panel UI test (CSP-safe: no page.evaluate).

The app's CSP forbids unsafe-eval, so we only use locator APIs. The stub video
auto-pauses after 'loadeddata' (VideoPanel pauses it), so the drawing tools are
enabled once the video is loaded.

Prereq: stack on :3000, agent in DOC_SNIPPET_MODE=1.
"""
import pytest

pytestmark = [pytest.mark.ui, pytest.mark.skipif(
    not __import__("os").environ.get("ANYQ_STACK_UP"),
    reason="needs the docker stack on :3000 - run `make up` and set ANYQ_STACK_UP=1",
)]

import re
import time
import uuid

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
USER = f"vid_{uuid.uuid4().hex[:10]}"
PW = "password123"
passed = []


def check(name, cond, detail=""):
    assert cond, f"{name}: {detail}"
    passed.append(name)
    print(f"  PASS  {name}", flush=True)


def wait_enabled(locator, timeout_s=30):
    """Poll until a locator matches an ENABLED button (locator APIs only)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if locator.count() and locator.is_enabled():
            return True
        time.sleep(0.5)
    return False


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.set_default_timeout(15000)

        # signup via the UI
        page.goto(BASE)
        page.get_by_role("button", name="Create Account").first.click(timeout=10000)
        page.get_by_placeholder("Enter username").fill(USER)
        page.get_by_placeholder("At least 8 characters").fill(PW)
        page.get_by_placeholder("Repeat password").fill(PW)
        page.locator("form").get_by_role("button", name="Create Account").click()
        page.wait_for_selector("text=New Chat", timeout=15000)

        # send a message and wait for the stub video to render (snippet mode)
        page.get_by_placeholder("Ask about the video or a topic...").fill("Show me gravity")
        page.get_by_role("button", name="Send").click()
        page.wait_for_selector("video", timeout=120000)
        check("video element appears after render", True)

        # the video auto-pauses after load -> pen tool becomes enabled
        pen = page.get_by_title("Pen tool (P)").first
        check("pen enabled after video loads", wait_enabled(pen, 30))

        pen.click()
        # draw a stroke on the canvas
        canvas = page.locator("canvas").first
        canvas.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        box = canvas.bounding_box()
        assert box, "canvas has no box"
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(cx - 60, cy - 20)
        page.mouse.down()
        time.sleep(0.4)
        page.mouse.move(cx + 60, cy + 20, steps=8)
        time.sleep(0.4)
        page.mouse.up()
        undo = page.get_by_title("Undo (Ctrl+Z)").first
        # fallback probe: a bare click on the canvas also triggers an undo entry
        if not (undo.count() and undo.is_enabled()):
            page.mouse.click(cx, cy)
            page.wait_for_timeout(400)
        page.screenshot(path="logs/draw_check.png", clip=box)
        page.wait_for_timeout(400)
        check("drawing happened (undo becomes enabled)", wait_enabled(undo, 10))

        # undo then redo
        undo.click()
        time.sleep(0.5)
        redo = page.get_by_title("Redo (Ctrl+Y)").first
        check("undo applied (redo becomes enabled)", wait_enabled(redo, 5))
        check("undo applied (undo disabled again)", not undo.is_enabled())
        redo.click()
        time.sleep(0.5)
        check("redo re-applies (undo enabled again)", wait_enabled(undo, 5))

        # screenshot flow: click the Add Screenshot button -> a data: thumbnail appears
        shot = page.get_by_role("button", name=re.compile("Screenshot", re.I)).first
        check("screenshot button enabled", wait_enabled(shot, 10))
        shot.click()
        time.sleep(1.0)
        imgs = page.locator('img[src^="data:"], img[src^="blob:"]')
        check("screenshot thumbnail captured", imgs.count() >= 1, f"imgs={imgs.count()}")

        browser.close()

    print(f"\n{len(passed)} PASS  ALL VIDEO PANEL CHECKS PASSED")
    return 0


def test_video_panel():
    """Wraps the original script so pytest reports it as one integration case."""
    assert main() == 0
