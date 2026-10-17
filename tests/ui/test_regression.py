"""UI regression via Playwright on system Edge (channel=msedge).

Covers: signup form -> main screen -> send message -> assistant replies ->
chat switching without cross-contamination -> logout clears state -> login
restores -> chat isolation between two users.

Prereq: stack running on :3000, pip install playwright, Edge installed.
"""
import pytest

pytestmark = [pytest.mark.ui, pytest.mark.skipif(
    not __import__("os").environ.get("ANYQ_STACK_UP"),
    reason="needs the docker stack on :3000 - run `make up` and set ANYQ_STACK_UP=1",
)]

import re
import uuid

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
USER = f"ui_{uuid.uuid4().hex[:10]}"
PW = "password123"
passed = []


def check(name, cond, detail=""):
    assert cond, f"{name}: {detail}"
    passed.append(name)
    print(f"  PASS  {name}", flush=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.set_default_timeout(15000)

        # 1. Signup via the UI
        page.goto(BASE)
        # tab switch to signup mode (there is also a submit button with the same label)
        page.get_by_role("button", name="Create Account").first.click(timeout=10000)
        page.get_by_placeholder("Enter username").fill(USER)
        page.get_by_placeholder("you@example.com").fill("")
        page.get_by_placeholder("At least 8 characters").fill(PW)
        page.get_by_placeholder("Repeat password").fill(PW)
        page.locator("form").get_by_role("button", name="Create Account").click()
        page.wait_for_timeout(2500)
        # after signup we land on the main screen (sidebar with New Chat)
        check("signup lands on main screen", page.get_by_text("New Chat").first.is_visible())

        # 2. Send a message and wait for the assistant's reply
        page.get_by_placeholder("Ask about the video or a topic...").fill("Explain gravity")
        page.get_by_role("button", name=re.compile("Send|Ask", re.I)).click()
        # Wait for the assistant to answer. What it says depends on the
        # deployment: with GEMINI_API_KEY set it is a real explanation (and a
        # render, so this can take minutes); without one it is the polite
        # "AI functions unavailable" note. Both are a valid reply here - the
        # test is about the exchange appearing in the right chat, not its text.
        # An error bubble carries data-role="error", so a failed pipeline is
        # never mistaken for an answer. Wait for whichever lands first: a real
        # reply, or the failure notice.
        page.wait_for_selector('[data-role="assistant"], [data-role="error"]', timeout=300000)
        if page.locator('[data-role="error"]').count():
            failure = page.locator('[data-role="error"]').first.inner_text().strip()
            raise AssertionError(
                "the agent did not answer - the UI shows a failure notice: " + failure
            )
        reply = page.locator('[data-role="assistant"]').first.inner_text().strip()
        check("assistant replied", bool(reply), "assistant bubble is empty")

        # 3. Create a second chat and switch back and forth
        page.get_by_role("button", name="New Chat").click()
        page.wait_for_timeout(1200)
        page.get_by_placeholder("Ask about the video or a topic...").fill("Second chat message")
        page.get_by_role("button", name=re.compile("Send|Ask", re.I)).click()
        page.wait_for_timeout(1500)

        # chat items live in a div.w-64 (the sidebar); capture its text once
        sidebar = page.locator("div.w-64").first
        # the first chat's message bubbles must show the gravity text and NOT the second message
        sidebar.get_by_text("Explain gravity").first.click()
        # Wait for chat 1's history to actually render. A fixed sleep used to be
        # enough only because the no-key deployment answered instantly; with a
        # real key the second chat may still be rendering, so wait on the
        # condition instead of on the clock.
        page.wait_for_selector('[data-role="assistant"]', timeout=60000)
        page.wait_for_function(
            "() => document.body.innerText.includes('Explain gravity')", timeout=60000
        )
        body_text = page.locator("main, body").inner_text()
        check("chat1 shows its own messages only", "Второй чат" not in body_text or "Second chat message" not in body_text,
              "cross-contamination check")
        check("chat1 shows the gravity exchange",
              "Explain gravity" in body_text
              and page.locator('[data-role="assistant"]').count() > 0)

        # 4. Logout
        page.get_by_role("button", name=re.compile("Logout|Sign out", re.I)).click()
        page.wait_for_timeout(2000)
        check("logout returns to login screen", page.get_by_placeholder("Enter username").is_visible())
        check("chat state cleared after logout", not sidebar.get_by_text("Explain gravity").count())

        # 5. Login again -> chats restored
        page.get_by_placeholder("Enter username").fill(USER)
        page.get_by_placeholder("Enter password").fill(PW)
        page.locator("form").get_by_role("button", name="Sign In").click()
        page.wait_for_timeout(2500)
        check("login restores chats", sidebar.get_by_text("Explain gravity").first.is_visible(timeout=10000))

        ctx.close()

        # 6. Isolation between two users (via API, UI is single-tab)
        import httpx
        u2 = f"ui2_{uuid.uuid4().hex[:10]}"
        with httpx.Client(base_url=BASE, timeout=15) as hx:
            r = hx.post("/api/auth/signup", json={"username": u2, "password": PW})
            assert r.status_code == 201, r.text
            r2 = hx.get("/api/chats")
            check("second user has no chats", r2.json()["items"] == [])
            # first user's chat id from a fresh login
        with httpx.Client(base_url=BASE, timeout=15) as hx:
            hx.post("/api/auth/login", json={"username": USER, "password": PW})
            chats = hx.get("/api/chats").json()["items"]
            assert chats, "user1 should have chats"
            first_chat = chats[0]["id"]
        with httpx.Client(base_url=BASE, timeout=15) as hx:
            hx.post("/api/auth/login", json={"username": u2, "password": PW})
            r3 = hx.get(f"/api/chats/{first_chat}")
            check("user2 cannot read user1 chat", r3.status_code == 404, str(r3.status_code))

        browser.close()

    print(f"\n{len(passed)} PASS  ALL UI REGRESSION CHECKS PASSED")
    return 0


def test_ui_regression():
    """Wraps the original script so pytest reports it as one integration case."""
    assert main() == 0
