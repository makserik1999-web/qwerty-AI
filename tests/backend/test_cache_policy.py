"""What the cache is allowed to keep, serve and promote.

The admission rules are the part that decides whether the disk fills up with
answers nobody asks for twice, so they get asserted directly rather than
inferred from a hit rate.
"""

import pytest


@pytest.fixture
def cache(backend):
    from app.services import cache_service

    return cache_service


@pytest.fixture
def library(backend):
    from app.repositories import library as lib

    return lib


@pytest.fixture(autouse=True)
async def clean_cache(backend):
    """Each test starts with an empty cache."""
    await backend.db.db.library_entries.delete_many({})
    await backend.db.db.question_stats.delete_many({})
    yield


# ============== admission ==============
def test_a_plain_question_is_cacheable(cache):
    allowed, reason = cache.cacheable_request("Explain gravity", [])
    assert allowed, reason


def test_a_question_with_a_screenshot_is_not_cacheable(cache):
    """The answer is about that image, so it must never be reused."""
    allowed, reason = cache.cacheable_request("what is wrong here", [{"image_base64": "x"}])
    assert not allowed
    assert reason == "has_screenshots"


def test_a_very_long_prompt_is_not_cacheable(cache):
    allowed, reason = cache.cacheable_request("solve " + "x" * 400, [])
    assert not allowed
    assert reason == "too_long"


@pytest.mark.parametrize(
    "prompt",
    ["check my homework please", "реши мою задачу", "проверь моё задание"],
)
def test_personal_requests_are_not_cacheable(cache, prompt):
    allowed, reason = cache.cacheable_request(prompt, [])
    assert not allowed, f"{prompt!r} should not be shared between users"
    assert reason == "looks_personal"


def test_an_empty_prompt_is_not_cacheable(cache):
    assert not cache.cacheable_request("", [])[0]
    assert not cache.cacheable_request("   ", [])[0]


# ============== writing ==============
@pytest.mark.asyncio
async def test_an_answer_with_a_video_is_stored(cache, backend, monkeypatch):
    monkeypatch.setattr(cache, "_media_present", lambda url: True)
    stored = await cache.remember("Explain gravity", [], "Gravity explained", "/media/a.mp4")
    assert stored

    hit = await cache.lookup("explain  GRAVITY!", [])
    assert hit is not None, "a differently typed form of the same question should hit"
    assert hit["educator_text"] == "Gravity explained"
    assert hit["video_url"] == "/media/a.mp4"


@pytest.mark.asyncio
async def test_a_text_only_answer_is_not_stored(cache):
    """Refusals, degraded-mode notices and rejections all arrive as text only.

    Reusing one would hand the next person a "cannot help with that" for a
    question the pipeline might well answer.
    """
    assert not await cache.remember("Explain gravity", [], "AI is unavailable", None)
    assert await cache.lookup("Explain gravity", []) is None


@pytest.mark.asyncio
async def test_an_empty_answer_is_not_stored(cache):
    assert not await cache.remember("Explain gravity", [], "   ", "/media/a.mp4")


@pytest.mark.asyncio
async def test_a_screenshot_answer_is_not_stored(cache):
    stored = await cache.remember("what is this", [{"image_base64": "x"}], "text", "/media/a.mp4")
    assert not stored


# ============== serving ==============
@pytest.mark.asyncio
async def test_a_missing_video_file_is_not_served(cache, monkeypatch):
    """Retention may have removed the file; a dead link is worse than a miss."""
    monkeypatch.setattr(cache, "_media_present", lambda url: True)
    await cache.remember("Explain gravity", [], "text", "/media/gone.mp4")

    monkeypatch.setattr(cache, "_media_present", lambda url: False)
    assert await cache.lookup("Explain gravity", []) is None


@pytest.mark.asyncio
async def test_lookup_counts_the_question_even_on_a_miss(cache, backend):
    """The miss is what tells us whether this question is worth keeping."""
    await cache.lookup("Explain entropy", [])
    await cache.lookup("explain ENTROPY", [])

    _, key = cache.key_for("Explain entropy")
    stats = await backend.db.db.question_stats.find_one({"_id": key})
    assert stats["hits"] == 2, "differently typed forms must share one counter"


# ============== tiers ==============
@pytest.mark.asyncio
async def test_a_new_entry_starts_ephemeral(cache, backend, monkeypatch, library):
    monkeypatch.setattr(cache, "_media_present", lambda url: True)
    await cache.remember("Explain gravity", [], "text", "/media/a.mp4")

    _, key = cache.key_for("Explain gravity")
    entry = await backend.db.db.library_entries.find_one({"cache_key": key})
    assert entry["tier"] == library.TIER_EPHEMERAL
    assert entry["expires_at"] is not None, "generated answers must age out"


@pytest.mark.asyncio
async def test_a_repeated_question_is_promoted_to_warm(cache, backend, monkeypatch, library):
    """Only questions that actually come back earn long-term storage."""
    monkeypatch.setattr(cache, "_media_present", lambda url: True)
    await cache.remember("Explain gravity", [], "text", "/media/a.mp4")

    _, key = cache.key_for("Explain gravity")
    for _ in range(3):
        await cache.lookup("Explain gravity", [])

    entry = await backend.db.db.library_entries.find_one({"cache_key": key})
    assert entry["tier"] == library.TIER_WARM
    assert entry["hits"] >= 1


@pytest.mark.asyncio
async def test_a_curated_entry_never_expires(backend, library):
    await library.store_entry(
        cache_key="curated-key",
        normalized="gravity",
        educator_text="hand checked",
        video_url="/media/a.mp4",
        tier=library.TIER_CURATED,
    )
    entry = await backend.db.db.library_entries.find_one({"cache_key": "curated-key"})
    assert entry["expires_at"] is None, "a reviewed video must never be swept away"


@pytest.mark.asyncio
async def test_a_generated_answer_cannot_overwrite_a_curated_one(backend, library):
    await library.store_entry(
        cache_key="k", normalized="gravity", educator_text="hand checked",
        video_url="/media/good.mp4", tier=library.TIER_CURATED,
    )
    await library.store_entry(
        cache_key="k", normalized="gravity", educator_text="model output",
        video_url="/media/meh.mp4", tier=library.TIER_EPHEMERAL,
    )
    entry = await backend.db.db.library_entries.find_one({"cache_key": "k"})
    assert entry["educator_text"] == "hand checked"
    assert entry["tier"] == library.TIER_CURATED


# ============== invalidation ==============
@pytest.mark.asyncio
async def test_bumping_the_pipeline_version_retires_old_answers(cache, backend, monkeypatch):
    monkeypatch.setattr(cache, "_media_present", lambda url: True)
    await cache.remember("Explain gravity", [], "old pipeline", "/media/a.mp4")
    assert await cache.lookup("Explain gravity", []) is not None

    # A prompt or model change means stored output no longer matches what the
    # pipeline would produce now. Derived rather than written out: this test
    # once pinned "v2", which stopped being a bump the day the default became
    # v2 and quietly turned the assertion into a tautology.
    monkeypatch.setattr(cache, "PIPELINE_VERSION", cache.PIPELINE_VERSION + "-next")
    assert await cache.lookup("Explain gravity", []) is None


@pytest.mark.parametrize(
    "prompt",
    [
        # Russian declines both words; every form is the same private request.
        "реши мою задачу",
        "проверь моё задание",
        "помоги с моей контрольной",
        "разбери мои примеры",
        "my homework question 4",
        "менің тапсырмам дұрыс па",
    ],
)
def test_personal_requests_survive_declension(cache, prompt):
    allowed, reason = cache.cacheable_request(prompt, [])
    assert not allowed, f"{prompt!r} must not be shared between users"
    assert reason == "looks_personal"


@pytest.mark.parametrize(
    "prompt",
    [
        # General topics that merely contain a similar word must still cache.
        "что такое задача трёх тел",
        "explain the travelling salesman problem",
        "как решать квадратные уравнения",
    ],
)
def test_general_topics_are_not_mistaken_for_personal(cache, prompt):
    allowed, reason = cache.cacheable_request(prompt, [])
    assert allowed, f"{prompt!r} is a general topic, reason given: {reason}"


# ============== statistics endpoint ==============
def test_cache_stats_are_not_readable_by_an_ordinary_user(client, new_user):
    """Top questions are other people's questions."""
    new_user()
    assert client.get("/api/admin/cache/stats").status_code == 404


def test_cache_stats_require_authentication(anon_client):
    assert anon_client.get("/api/admin/cache/stats").status_code == 401


@pytest.mark.asyncio
async def test_cache_stats_report_tiers_and_top_questions(
    backend, client, new_user, cache, monkeypatch
):
    user = new_user()
    monkeypatch.setattr(backend.config, "ADMIN_USERS", {user["username"]})
    monkeypatch.setattr(cache, "_media_present", lambda url: True)

    await cache.remember("Explain gravity", [], "text", "/media/a.mp4")
    await cache.lookup("Explain gravity", [])
    await cache.lookup("Explain gravity", [])

    import app.api.library as library_api

    monkeypatch.setattr(library_api, "ADMIN_USERS", {user["username"]})
    stats = client.get("/api/admin/cache/stats").json()

    assert stats["entries_total"] >= 1
    assert stats["questions_seen"] >= 1
    assert any(q["hits"] >= 2 for q in stats["top_questions"])
