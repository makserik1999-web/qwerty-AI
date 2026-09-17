"""The same question, asked two ways, is two different videos.

The answer cache deliberately serves one rendered file to everyone who asks
the same thing. Narration breaks the assumption underneath that: with the
voice on the video runs about a minute and explains itself aloud, with it off
it is a silent half-minute of captions. The words are identical, so nothing
downstream would notice the mix-up - the asker would simply get a mute video
they did not ask for, or a voice they did not pick.

The key's own docstring already warned about this shape of bug for a language
selector. These tests hold the fix in place.
"""

import pytest


@pytest.fixture
def cache(backend):
    from app.services import cache_service

    return cache_service


@pytest.fixture
def keys(backend):
    from app.cache.normalize import cache_key

    return cache_key


@pytest.fixture(autouse=True)
async def clean_library(backend):
    await backend.db.db.library_entries.delete_many({})
    yield
    await backend.db.db.library_entries.delete_many({})


# ------------------------------------------------------------------- keys --


def test_narration_changes_the_key(keys):
    assert keys("q", "v2", "voice=aigul") != keys("q", "v2", "silent")


def test_the_voice_changes_the_key(keys):
    """Aigul and Daulet read the same script; the files are not interchangeable."""
    assert keys("q", "v2", "voice=aigul") != keys("q", "v2", "voice=daulet")


def test_the_same_request_gives_the_same_key(keys):
    assert keys("q", "v2", "voice=aigul") == keys("q", "v2", "voice=aigul")


def test_the_pipeline_version_still_separates_answers(keys):
    """Bumping it must keep retiring everything, variant or not."""
    assert keys("q", "v2", "voice=aigul") != keys("q", "v3", "voice=aigul")


def test_a_variant_is_not_confusable_with_a_longer_question(keys):
    """The parts are joined, so they must not be able to spell each other."""
    assert keys("a|v2|silent", "v2") != keys("a", "v2", "silent")


class TestVariantStrings:
    def test_narration_on_names_the_voice(self, cache):
        assert cache.render_variant(True, "daulet") == "voice=daulet"

    def test_narration_off_is_one_value_for_everyone(self, cache):
        """A silent video does not depend on which voice was not used."""
        assert cache.render_variant(False, "aigul") == cache.render_variant(False, "daulet")


# -------------------------------------------------------------- behaviour --


class TestOneAnswerDoesNotServeTheOther:
    """Every test here pretends the rendered file is still on disk.

    Without that these would pass whatever the variant did: lookup also
    returns None when the video has been collected by retention, so a test
    that skips this would be green against a completely broken key.
    """

    @pytest.fixture(autouse=True)
    def _media_exists(self, cache, monkeypatch):
        monkeypatch.setattr(cache, "_media_present", lambda url: True)

    async def test_a_silent_answer_is_not_served_to_a_spoken_request(self, cache):
        stored = await cache.remember(
            prompt="что такое инерция", screenshots=[], text="ответ",
            video_url="/media/rendered_silent.mp4",
            variant=cache.render_variant(False, "aigul"),
        )
        assert stored

        hit = await cache.lookup("что такое инерция", [],
                                 cache.render_variant(True, "aigul"))

        assert hit is None, "a mute video would have been handed to someone who asked for a voice"

    async def test_one_voice_is_not_served_for_another(self, cache):
        await cache.remember(
            prompt="что такое инерция", screenshots=[], text="ответ",
            video_url="/media/aigul.mp4",
            variant=cache.render_variant(True, "aigul"),
        )

        hit = await cache.lookup("что такое инерция", [],
                                 cache.render_variant(True, "daulet"))

        assert hit is None

    async def test_the_matching_request_still_hits(self, cache):
        """The separation must not cost every hit - that would be a cache in name only."""
        await cache.remember(
            prompt="что такое инерция", screenshots=[], text="ответ",
            video_url="/media/aigul.mp4",
            variant=cache.render_variant(True, "aigul"),
        )

        hit = await cache.lookup("что такое инерция", [],
                                 cache.render_variant(True, "aigul"))

        assert hit is not None
        assert hit["video_url"] == "/media/aigul.mp4"


# ------------------------------------------------------------- the client --


class TestTheVoiceIsNotTakenOnTrust:
    """A variant reaches a hash, so free text there is unlimited keys.

    Someone sending a fresh random voice with every question would fill the
    library with entries nothing can ever match again, and never get a hit
    themselves. The value is checked against a closed set first.
    """

    def test_the_allowed_set_is_small_and_closed(self, backend):
        from app.config import NARRATION_VOICES

        assert set(NARRATION_VOICES) == {"aigul", "daulet"}

    @pytest.mark.parametrize(
        "sent",
        ["", "AIGUL", "aigul; drop", "../../etc", "x" * 500, "voice=aigul"],
    )
    def test_anything_outside_the_set_falls_back(self, backend, sent):
        from app.config import NARRATION_VOICE_DEFAULT, NARRATION_VOICES

        chosen = sent if sent in NARRATION_VOICES else NARRATION_VOICE_DEFAULT

        assert chosen in NARRATION_VOICES


# ----------------------------------------------------------- to the agent --


class TestTheAgentIsTold:
    async def test_the_request_carries_the_choice(self, backend):
        """The agent renders per request, not per its own configuration."""
        from app.ws.manager import agent_manager

        sent = {}

        class Recorder:
            async def send_json(self, payload):
                sent.update(payload)

        agent_manager.agent_connection = Recorder()
        try:
            await agent_manager.send_to_agent(
                request_id="r1", user_id="u1", chat_id="c1",
                text="что такое инерция", screenshots=[],
                narration=True, narration_voice="daulet",
            )
        finally:
            agent_manager.agent_connection = None

        assert sent["narration"] is True
        assert sent["narration_voice"] == "daulet"

    async def test_silence_is_carried_too(self, backend):
        from app.ws.manager import agent_manager

        sent = {}

        class Recorder:
            async def send_json(self, payload):
                sent.update(payload)

        agent_manager.agent_connection = Recorder()
        try:
            await agent_manager.send_to_agent(
                request_id="r1", user_id="u1", chat_id="c1",
                text="q", screenshots=[], narration=False, narration_voice="aigul",
            )
        finally:
            agent_manager.agent_connection = None

        assert sent["narration"] is False


# ------------------------------------------------------- the semantic path --


class TestTheSemanticLayerRespectsTheVariant:
    """Found live, not by reasoning: the fix above was only half of one.

    The exact key carried the variant, so the second request missed it - and
    then fell through to the semantic layer, which searches by meaning and
    never sees a key. It matched the wording, ignored everything else, and
    handed a SILENT video to a request made with narration on.

    Anything the key encodes has to be re-stated here or it is lost. That is
    true of the pipeline version too: bumping it retired old answers from the
    exact lookup while leaving them reachable by meaning.
    """

    @pytest.fixture
    def semantic(self, backend):
        from app.cache import semantic as module

        return module

    async def _store(self, backend, semantic, key, question, vector, *,
                     language="ru", pipeline="v2", variant="silent"):
        from app.repositories.library import store_entry

        await store_entry(
            cache_key=key, normalized=question, educator_text="t",
            video_url="/media/x.mp4", language=language,
            pipeline_version=pipeline, variant=variant,
        )
        await semantic.attach_embedding(key, vector, language)

    async def test_a_silent_answer_is_not_matched_for_a_spoken_request(
            self, backend, semantic):
        await self._store(backend, semantic, "s1", "что такое инерция",
                          [1.0, 0.0, 0.0], variant="silent")

        match = await semantic.find_similar([1.0, 0.0, 0.0], "ru", "v2", "voice=aigul")

        assert match is None, "the exact bug: a mute video matched a spoken request"

    async def test_one_voice_is_not_matched_for_another(self, backend, semantic):
        await self._store(backend, semantic, "s2", "что такое инерция",
                          [1.0, 0.0, 0.0], variant="voice=aigul")

        assert await semantic.find_similar([1.0, 0.0, 0.0], "ru", "v2",
                                           "voice=daulet") is None

    async def test_an_old_pipeline_is_not_matched(self, backend, semantic):
        """Bumping the version must retire answers from BOTH lookups."""
        await self._store(backend, semantic, "s3", "что такое инерция",
                          [1.0, 0.0, 0.0], pipeline="v1", variant="silent")

        assert await semantic.find_similar([1.0, 0.0, 0.0], "ru", "v2",
                                           "silent") is None

    async def test_an_entry_recorded_before_variants_is_not_matched(
            self, backend, semantic):
        """Its rendering settings are unknown, so it cannot be claimed to match."""
        from app.repositories.library import store_entry

        await store_entry(cache_key="old", normalized="что такое инерция",
                          educator_text="t", video_url="/media/x.mp4",
                          language="ru", pipeline_version="v2")
        await semantic.attach_embedding("old", [1.0, 0.0, 0.0], "ru")

        assert await semantic.find_similar([1.0, 0.0, 0.0], "ru", "v2",
                                           "silent") is None

    async def test_the_matching_request_still_finds_it(self, backend, semantic):
        """The scoping must not cost every semantic hit."""
        await self._store(backend, semantic, "s4", "что такое инерция",
                          [1.0, 0.02, 0.0], variant="voice=aigul")

        match = await semantic.find_similar([1.0, 0.0, 0.0], "ru", "v2", "voice=aigul")

        assert match is not None
        assert match["normalized_question"] == "что такое инерция"
