"""The semantic layer: same question, different words.

The arithmetic is small; the judgement is not. Two rules are asserted here
because both were derived from measurement and both would be tempting to
"simplify" later:

- matching never crosses languages, because a Kazakh and a Russian phrasing of
  the same question score higher against each other (0.92) than two Russian
  phrasings of the same question do;
- the threshold sits above every observed different-question pair, giving up
  half the paraphrases on purpose, because a false hit answers a question
  nobody asked.
"""

import math

import pytest


@pytest.fixture
def semantic(backend):
    from app.cache import semantic as module

    return module


@pytest.fixture(autouse=True)
async def clean_library(backend):
    await backend.db.db.library_entries.delete_many({})
    yield
    await backend.db.db.library_entries.delete_many({})


def _vector(*values: float) -> list:
    """A short vector, padded so length checks behave like the real thing."""
    return list(values)


async def _store(backend, semantic, key: str, question: str, vector: list,
                 language: str, video: str = "/media/rendered_1.mp4") -> None:
    from app.repositories.library import store_entry

    await store_entry(
        cache_key=key, normalized=question, educator_text=f"answer to {question}",
        video_url=video, language=language,
    )
    await semantic.attach_embedding(key, vector, language)


# ---------------------------------------------------------------- geometry --


def test_normalising_gives_a_unit_vector(semantic):
    unit = semantic.normalise([3.0, 4.0])

    assert math.isclose(math.sqrt(sum(x * x for x in unit)), 1.0)


def test_a_zero_vector_normalises_to_nothing(semantic):
    """Rather than dividing by zero and producing NaNs that compare oddly."""
    assert semantic.normalise([0.0, 0.0, 0.0]) == []


def test_identical_directions_score_one(semantic):
    a = semantic.normalise([1.0, 2.0, 3.0])

    assert math.isclose(semantic.similarity(a, a), 1.0, abs_tol=1e-9)


def test_orthogonal_directions_score_zero(semantic):
    a = semantic.normalise([1.0, 0.0])
    b = semantic.normalise([0.0, 1.0])

    assert math.isclose(semantic.similarity(a, b), 0.0, abs_tol=1e-9)


def test_vectors_of_different_length_never_match(semantic):
    """A stored vector from another model must not produce a plausible score."""
    assert semantic.similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_an_empty_vector_never_matches(semantic):
    assert semantic.similarity([], [1.0]) == 0.0


# ----------------------------------------------------------------- lookup ---


async def test_a_close_question_is_found(backend, semantic):
    await _store(backend, semantic, "k1", "что такое гравитация",
                 _vector(1.0, 0.02, 0.0), "ru")

    match = await semantic.find_similar(_vector(1.0, 0.0, 0.0), "ru")

    assert match is not None
    assert match["normalized_question"] == "что такое гравитация"
    assert match["semantic_score"] >= 0.85


async def test_a_distant_question_is_not_found(backend, semantic):
    await _store(backend, semantic, "k2", "что такое фотосинтез",
                 _vector(0.0, 1.0, 0.0), "ru")

    assert await semantic.find_similar(_vector(1.0, 0.0, 0.0), "ru") is None


async def test_the_closest_of_several_wins(backend, semantic):
    await _store(backend, semantic, "near", "ближе", _vector(1.0, 0.05, 0.0), "ru")
    await _store(backend, semantic, "far", "дальше", _vector(1.0, 0.4, 0.0), "ru")

    match = await semantic.find_similar(_vector(1.0, 0.0, 0.0), "ru")

    assert match["normalized_question"] == "ближе"


# --------------------------------------------------------------- languages --


async def test_matching_never_crosses_languages(backend, semantic):
    """The measured danger: the same question in kk and ru scores 0.92.

    Without this rule that pair would be the FIRST thing any threshold
    matches, and a Kazakh student would be handed a Russian video.
    """
    await _store(backend, semantic, "ru1", "что такое гравитация",
                 _vector(1.0, 0.0, 0.0), "ru")

    # An identical vector, asked in Kazakh.
    assert await semantic.find_similar(_vector(1.0, 0.0, 0.0), "kk") is None


async def test_an_entry_without_a_language_is_never_matched(backend, semantic):
    """Entries stored before languages were recorded must stay invisible."""
    from app.repositories.library import store_entry

    await store_entry(cache_key="old", normalized="старая запись",
                      educator_text="t", video_url=None, language="")
    await backend.db.db.library_entries.update_one(
        {"cache_key": "old"}, {"$set": {"embedding": [1.0, 0.0, 0.0]}}
    )

    assert await semantic.find_similar(_vector(1.0, 0.0, 0.0), "ru") is None


async def test_a_query_without_a_language_matches_nothing(backend, semantic):
    await _store(backend, semantic, "k3", "вопрос", _vector(1.0, 0.0, 0.0), "ru")

    assert await semantic.find_similar(_vector(1.0, 0.0, 0.0), "") is None


# ------------------------------------------------------------- attachment ---


async def test_attaching_stores_a_unit_vector(backend, semantic):
    await _store(backend, semantic, "k4", "вопрос", _vector(3.0, 4.0), "ru")

    entry = await backend.db.db.library_entries.find_one({"cache_key": "k4"})
    length = math.sqrt(sum(x * x for x in entry["embedding"]))

    assert math.isclose(length, 1.0)


async def test_attaching_without_a_language_is_refused(backend, semantic):
    from app.repositories.library import store_entry

    await store_entry(cache_key="k5", normalized="q", educator_text="t", video_url=None)

    assert not await semantic.attach_embedding("k5", [1.0, 0.0], "")


async def test_attaching_to_a_missing_entry_reports_failure(semantic):
    assert not await semantic.attach_embedding("nope", [1.0, 0.0], "ru")


# ------------------------------------------------------ measured behaviour --

# The calibration set behind the threshold, as cosine scores rather than live
# API calls: the numbers are what was measured on gemini-embedding-001, and
# the point of keeping them is that changing the threshold changes this test.
MEASURED_SAME = [0.701, 0.752, 0.801, 0.823, 0.860, 0.893, 0.929, 0.937]
MEASURED_DIFFERENT = [0.633, 0.682, 0.734, 0.741, 0.743, 0.747, 0.771, 0.781, 0.797]


def test_the_threshold_admits_no_measured_collision(backend):
    """Not one genuinely different question may pass. This is the whole point."""
    from app.config import CACHE_SEMANTIC_THRESHOLD

    passing = [s for s in MEASURED_DIFFERENT if s >= CACHE_SEMANTIC_THRESHOLD]

    assert not passing, f"these different questions would match: {passing}"


def test_the_threshold_still_catches_real_paraphrases(backend):
    """A threshold so high it matches nothing would be safe and useless."""
    from app.config import CACHE_SEMANTIC_THRESHOLD

    caught = [s for s in MEASURED_SAME if s >= CACHE_SEMANTIC_THRESHOLD]

    assert len(caught) >= len(MEASURED_SAME) / 3, (
        f"only {len(caught)}/{len(MEASURED_SAME)} paraphrases would be found"
    )


def test_the_bands_overlap_so_no_threshold_is_perfect(backend):
    """Documents why half the paraphrases are given up rather than tuned away."""
    assert min(MEASURED_SAME) < max(MEASURED_DIFFERENT), (
        "if these ever separate, the threshold can be lowered - re-measure first"
    )


# ------------------------------------------------- agent capability gate ---


class TestEmbedCapability:
    """The backend must not send an embed request to an agent that predates it.

    An older build reads every frame as a question, so an embed request would
    become a ninety-second render of the words "what is gravity" - during a
    rolling deploy, for every cache miss.
    """

    async def test_no_embed_request_without_the_declared_feature(self, backend):
        from app.ws.manager import agent_manager

        agent_manager.agent_connection = object()  # never used - the gate is first
        agent_manager.agent_features = set()
        try:
            assert await agent_manager.request_embedding("что такое атом", 0.1) is None
        finally:
            agent_manager.agent_connection = None
            agent_manager.agent_features = set()

    async def test_no_embed_request_without_an_agent(self, backend):
        from app.ws.manager import agent_manager

        agent_manager.agent_connection = None
        agent_manager.agent_features = {"embed"}
        try:
            assert await agent_manager.request_embedding("что такое атом", 0.1) is None
        finally:
            agent_manager.agent_features = set()

    async def test_a_late_reply_is_given_up_on(self, backend):
        """The fallback is a normal generation; waiting is the worse outcome."""
        import asyncio

        from app.ws.manager import agent_manager

        class SilentAgent:
            async def send_json(self, payload):
                return None

        agent_manager.agent_connection = SilentAgent()
        agent_manager.agent_features = {"embed"}
        try:
            started = asyncio.get_running_loop().time()
            assert await agent_manager.request_embedding("вопрос", 0.2) is None
            assert asyncio.get_running_loop().time() - started < 2.0
            # And nothing is left behind waiting for an answer that never came.
            assert agent_manager.pending_embeddings == {}
        finally:
            agent_manager.agent_connection = None
            agent_manager.agent_features = set()


class TestEmbeddingIsWrittenInTheBackground:
    """remember() must not wait for the agent's embedding reply.

    It is called from the agent's receive loop, and the reply can only arrive
    through that same loop. Awaiting it there is a deadlock that resolves as a
    silent timeout: the answer is stored, no vector is ever attached, and the
    semantic layer quietly does nothing.
    """

    async def test_remembering_returns_without_waiting_for_the_agent(self, backend):
        import asyncio

        from app.services import cache_service
        from app.ws.manager import agent_manager

        class SilentAgent:
            async def send_json(self, payload):
                return None

        agent_manager.agent_connection = SilentAgent()
        agent_manager.agent_features = {"embed"}
        try:
            started = asyncio.get_running_loop().time()
            stored = await cache_service.remember(
                prompt="что такое инерция", screenshots=[],
                text="ответ", video_url="/media/rendered_1.mp4",
            )
            elapsed = asyncio.get_running_loop().time() - started

            assert stored
            # The agent never answers; if this waited for it, the embed
            # timeout (seconds) would show up right here.
            assert elapsed < 1.0, f"remember() blocked for {elapsed:.1f}s"
        finally:
            agent_manager.agent_connection = None
            agent_manager.agent_features = set()
            await backend.db.db.library_entries.delete_many({})

    async def test_a_background_task_is_actually_kept(self, backend):
        """asyncio holds only a weak reference; an unheld task can vanish."""
        from app.services import cache_service

        cache_service._schedule_embedding("some-key", "какой-то вопрос")

        assert cache_service._embedding_tasks, "the task was not held anywhere"
        for task in list(cache_service._embedding_tasks):
            task.cancel()
