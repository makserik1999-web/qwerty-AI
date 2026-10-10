"""What a quota looks like to the person hitting it.

A limit that only shows up as a refusal is a limit the user learns about by
being stopped. So the two things checked here are that the budget appears
before it runs out, and that it stays out of the way while there is plenty -
a counter on screen at all times turns every question into a transaction.
"""

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


def _spend(user_id: str, count: int) -> None:
    subprocess.run(
        ["docker", "compose", "exec", "-T", "mongo", "mongosh", "anyq_db", "--quiet",
         "--eval",
         f"const now = new Date(); const rows = [];"
         f"for (let i = 0; i < {count}; i++) rows.push({{user_id: '{user_id}', "
         "  request_id: 'ui-' + i, created_at: now, "
         "  expires_at: new Date(now.getTime() + 2*864e5)});"
         "db.generation_events.insertMany(rows);"],
        capture_output=True, timeout=60,
    )


@pytest.fixture
def signed_in():
    """A browser logged into a fresh account, plus a way to spend its budget."""
    import httpx
    from playwright.sync_api import sync_playwright

    username = f"qui_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE, timeout=30) as hx:
        assert hx.post(
            "/api/auth/signup", json={"username": username, "password": PASSWORD}
        ).status_code == 201
        user_id = hx.get("/api/auth/me").json()["user"]["id"]
        limits = hx.get("/api/quota").json()

    def sign_in(page):
        page.goto(BASE)
        page.get_by_placeholder("Enter username").fill(username)
        page.get_by_placeholder("Enter password").fill(PASSWORD)
        page.locator("form").get_by_role("button", name="Sign In").click()
        page.wait_for_selector("text=New Chat", timeout=20000)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        page.set_default_timeout(20000)
        yield page, user_id, limits, sign_in
        browser.close()


def test_a_full_budget_is_not_advertised(signed_in):
    """Nothing to warn about yet, so nothing on screen."""
    page, _, _, sign_in = signed_in
    sign_in(page)

    page.wait_for_timeout(1500)

    assert page.locator('[data-testid="quota-remaining"]').count() == 0


def test_a_low_budget_is_shown_before_it_runs_out(signed_in):
    page, user_id, limits, sign_in = signed_in
    # Two left of the hourly allowance.
    _spend(user_id, limits["limit_hour"] - 2)
    sign_in(page)

    page.wait_for_selector('[data-testid="quota-remaining"]', timeout=15000)
    text = page.locator('[data-testid="quota-remaining"]').inner_text()

    assert "2 of" in text
    assert str(limits["limit_hour"]) in text


def test_running_out_says_so_and_points_at_the_library(signed_in):
    page, user_id, limits, sign_in = signed_in
    _spend(user_id, limits["limit_day"])
    sign_in(page)

    page.get_by_placeholder("Ask about the video or a topic...").fill(
        f"Explain {uuid.uuid4().hex[:10]}"
    )
    page.get_by_role("button", name="Send").click()

    page.wait_for_selector('[data-role="error"]', timeout=20000)
    message = page.locator('[data-role="error"]').last.inner_text()

    assert "today" in message.lower()
    # A refusal should say what still works.
    assert "library" in message.lower()
