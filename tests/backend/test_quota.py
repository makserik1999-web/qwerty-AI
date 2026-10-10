"""Generation quotas: what they stop, and what they must never charge for.

The point of these limits is that one logged-in account cannot hold the only
agent. So the cases that matter most are the two where a refusal would be
wrong - an answer from the library, and a generation that failed - because
getting those wrong turns a load limit into a punishment for using the
product.
"""

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def quota(backend):
    from app.services import quota as module

    return module


@pytest.fixture(autouse=True)
async def clean_events(backend):
    await backend.db.db.generation_events.delete_many({})
    yield
    await backend.db.db.generation_events.delete_many({})


async def _fill(quota, user_id: str, count: int, age_hours: float = 0.0) -> None:
    """Pretend this user already started `count` generations `age_hours` ago."""
    from app.db import db

    when = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    if count:
        await db.db.generation_events.insert_many([
            {"user_id": user_id, "request_id": f"r{i}-{age_hours}",
             "created_at": when, "expires_at": when + timedelta(days=2)}
            for i in range(count)
        ])


# --------------------------------------------------------------- allowing --


async def test_a_fresh_user_may_generate(quota):
    verdict = await quota.check("u1", in_flight=0, queue_depth=0)

    assert verdict.allowed
    assert verdict.remaining_hour == quota.GENERATION_MAX_PER_HOUR
    assert verdict.remaining_day == quota.GENERATION_MAX_PER_DAY


async def test_the_remaining_count_goes_down_as_it_is_used(quota):
    await _fill(quota, "u2", 3)

    verdict = await quota.check("u2", in_flight=0, queue_depth=0)

    assert verdict.allowed
    assert verdict.remaining_hour == quota.GENERATION_MAX_PER_HOUR - 3


# ------------------------------------------------------------- concurrency --


async def test_a_second_generation_waits_for_the_first(quota):
    """The limit that actually protects the agent."""
    verdict = await quota.check("u3", in_flight=1, queue_depth=1)

    assert not verdict.allowed
    assert "still being made" in verdict.reason
    # Phrased as waiting, not as a denial: nothing was lost.
    assert "used" not in verdict.reason.lower()


async def test_concurrency_is_counted_per_user(quota, backend):
    """Somebody else's render must not block mine."""
    from app.ws.manager import agent_manager

    agent_manager.pending_requests.clear()
    agent_manager.pending_requests["other"] = {"user_id": "stranger"}
    try:
        assert agent_manager.in_flight_for("me") == 0
        assert agent_manager.in_flight_for("stranger") == 1
        assert agent_manager.queue_depth() == 1
    finally:
        agent_manager.pending_requests.clear()


# ------------------------------------------------------------------ limits --


async def test_the_hourly_limit_refuses_once_spent(quota):
    await _fill(quota, "u4", quota.GENERATION_MAX_PER_HOUR)

    verdict = await quota.check("u4", in_flight=0, queue_depth=0)

    assert not verdict.allowed
    assert str(quota.GENERATION_MAX_PER_HOUR) in verdict.reason
    assert verdict.retry_after_sec > 0


async def test_the_hourly_limit_only_counts_the_last_hour(quota):
    await _fill(quota, "u5", quota.GENERATION_MAX_PER_HOUR, age_hours=2)

    verdict = await quota.check("u5", in_flight=0, queue_depth=0)

    assert verdict.allowed


async def test_the_daily_limit_survives_the_hourly_window(quota):
    """Spread over the day, the hourly limit never trips - the daily one must."""
    await _fill(quota, "u6", quota.GENERATION_MAX_PER_DAY, age_hours=5)

    verdict = await quota.check("u6", in_flight=0, queue_depth=0)

    assert not verdict.allowed
    assert str(quota.GENERATION_MAX_PER_DAY) in verdict.reason


async def test_a_refusal_still_points_at_the_library(quota):
    """A limit should say what does still work, not only what does not."""
    await _fill(quota, "u7", quota.GENERATION_MAX_PER_DAY)

    verdict = await quota.check("u7", in_flight=0, queue_depth=0)

    assert "library" in verdict.reason.lower()


async def test_a_full_queue_is_reported_honestly(quota):
    verdict = await quota.check("u8", in_flight=0, queue_depth=quota.GENERATION_QUEUE_MAX)

    assert not verdict.allowed
    assert "busy" in verdict.reason.lower()


# ----------------------------------------------------------------- refunds --


async def test_a_failed_generation_gives_the_quota_back(quota, backend):
    await quota.record("u9", "req-1")
    assert (await quota.check("u9", 0, 0)).remaining_hour == quota.GENERATION_MAX_PER_HOUR - 1

    refunded = await quota.refund("req-1")

    assert refunded
    assert (await quota.check("u9", 0, 0)).remaining_hour == quota.GENERATION_MAX_PER_HOUR


async def test_refunding_twice_is_harmless(quota):
    await quota.record("u10", "req-2")
    assert await quota.refund("req-2")
    assert not await quota.refund("req-2")


async def test_a_refund_for_an_unknown_request_does_nothing(quota):
    await quota.record("u11", "req-3")

    assert not await quota.refund("never-existed")
    assert (await quota.check("u11", 0, 0)).remaining_hour == quota.GENERATION_MAX_PER_HOUR - 1


# -------------------------------------------------------------- the endpoint --


async def test_the_usage_endpoint_reports_what_is_left(client, new_user, quota):
    user = new_user()
    client.post("/api/auth/login",
                json={"username": user["username"], "password": user["password"]})
    await quota.record(user["id"], "req-endpoint")

    body = client.get("/api/quota").json()

    assert body["limit_hour"] == quota.GENERATION_MAX_PER_HOUR
    assert body["used_hour"] == 1
    assert body["remaining_hour"] == quota.GENERATION_MAX_PER_HOUR - 1


async def test_the_usage_endpoint_needs_a_session(anon_client):
    assert anon_client.get("/api/quota").status_code == 401


async def test_one_users_generations_do_not_spend_anothers(quota):
    await _fill(quota, "heavy", quota.GENERATION_MAX_PER_HOUR)

    assert not (await quota.check("heavy", 0, 0)).allowed
    assert (await quota.check("light", 0, 0)).allowed


# ------------------------------------------------------------ signup limit --


class TestSignupLimit:
    """An open signup endpoint is how a bounded per-user quota becomes unbounded.

    The limit is deliberately loose: a school computer room shares one address,
    so a tight per-IP cap would lock out a class signing up together while
    barely slowing a script down. The limit that bounds cost is the per-user
    generation quota, not this one.
    """

    def test_accounts_can_be_created_up_to_the_limit(self, backend, client):
        import uuid

        limit = backend.config.SIGNUP_MAX_PER_HOUR
        for _ in range(limit):
            response = client.post(
                "/api/auth/signup",
                json={"username": f"s_{uuid.uuid4().hex[:12]}", "password": "password123"},
            )
            assert response.status_code == 201, response.text

    def test_the_next_account_is_refused(self, backend, client):
        import uuid

        limit = backend.config.SIGNUP_MAX_PER_HOUR
        for _ in range(limit):
            client.post(
                "/api/auth/signup",
                json={"username": f"s_{uuid.uuid4().hex[:12]}", "password": "password123"},
            )

        response = client.post(
            "/api/auth/signup",
            json={"username": f"s_{uuid.uuid4().hex[:12]}", "password": "password123"},
        )

        assert response.status_code == 429
        assert str(limit) in response.json()["detail"]

    def test_a_whole_classroom_fits_under_the_limit(self, backend):
        """25 students behind one NAT must not lock each other out."""
        assert backend.config.SIGNUP_MAX_PER_HOUR >= 25
