"""How hard the model is told to think, and who is allowed to hear about it.

The setting exists because of a measurement, not a preference: on the Manim
node the provider default took 24.4s and produced scripts that rendered 2
times in 4, while "low" took 16.5s and rendered 4 in 4 - with longer videos.

Two things must stay true, and both are easy to break by tidying:

- the field rides on `extra_body`, an OpenAI-wire concept, so it must never be
  sent when DEFAULT_LLM_PROVIDER points at the native Gemini provider - that
  path is deliberately kept working;
- a bad value must stop the agent at startup rather than 400 every single
  request, which would surface as "the LLM is down".
"""

import importlib

import pytest


def _reload(monkeypatch, **env):
    """Re-import config and llm_client under a chosen environment.

    Both read os.environ at import time - that is the existing style in this
    codebase - so a reload is the only way to exercise a different setting.
    """
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    import anyq.config
    import anyq.llm_client

    importlib.reload(anyq.config)
    return importlib.reload(anyq.llm_client)


@pytest.fixture(autouse=True)
def _restore(agent_import_path):
    """Leave the modules as the rest of the suite expects to find them."""
    yield
    import anyq.config
    import anyq.llm_client

    importlib.reload(anyq.config)
    importlib.reload(anyq.llm_client)


# ------------------------------------------------------------- when it is on --


def test_the_effort_is_sent_on_openrouter(agent_import_path, monkeypatch):
    client = _reload(monkeypatch, DEFAULT_LLM_PROVIDER="openrouter",
                     LLM_REASONING_EFFORT="low")

    assert client._REASONING_KWARGS == {"extra_body": {"reasoning": {"effort": "low"}}}


def test_the_value_is_passed_through_verbatim(agent_import_path, monkeypatch):
    client = _reload(monkeypatch, DEFAULT_LLM_PROVIDER="openrouter",
                     LLM_REASONING_EFFORT="high")

    assert client._REASONING_KWARGS["extra_body"]["reasoning"]["effort"] == "high"


# ------------------------------------------------------------ when it is off --


def test_nothing_is_sent_to_the_native_gemini_provider(agent_import_path, monkeypatch):
    """DEFAULT_LLM_PROVIDER=gemini is a supported fallback; extra_body would break it."""
    client = _reload(monkeypatch, DEFAULT_LLM_PROVIDER="gemini",
                     LLM_REASONING_EFFORT="low")

    assert client._REASONING_KWARGS == {}


def test_an_empty_setting_sends_nothing(agent_import_path, monkeypatch):
    client = _reload(monkeypatch, DEFAULT_LLM_PROVIDER="openrouter",
                     LLM_REASONING_EFFORT="")

    assert client._REASONING_KWARGS == {}


# ------------------------------------------------------------- bad settings --


def test_a_misspelled_effort_stops_the_agent_at_startup(agent_import_path, monkeypatch):
    """Not on the first question - by then it looks like an upstream outage."""
    monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "lowest")

    import anyq.config

    with pytest.raises(SystemExit):
        importlib.reload(anyq.config)


@pytest.mark.parametrize("effort", ["minimal", "low", "medium", "high"])
def test_every_documented_level_is_accepted(agent_import_path, monkeypatch, effort):
    client = _reload(monkeypatch, DEFAULT_LLM_PROVIDER="openrouter",
                     LLM_REASONING_EFFORT=effort)

    assert client._REASONING_KWARGS["extra_body"]["reasoning"]["effort"] == effort


# ----------------------------------------------------------------- the call --


class TestWhatReachesTheProvider:
    async def test_the_effort_is_attached_to_the_request(self, agent_import_path,
                                                         monkeypatch):
        client = _reload(monkeypatch, DEFAULT_LLM_PROVIDER="openrouter",
                         LLM_REASONING_EFFORT="low")
        seen = {}

        async def fake_chat(messages, **kwargs):
            seen.update(kwargs)
            return "ok"

        monkeypatch.setattr(client.llm, "chat", fake_chat, raising=False)

        assert await client._llm_chat([]) == "ok"
        assert seen["extra_body"] == {"reasoning": {"effort": "low"}}

    async def test_a_caller_that_sets_its_own_extra_body_wins(self, agent_import_path,
                                                              monkeypatch):
        """Otherwise a future per-node override would be silently discarded."""
        client = _reload(monkeypatch, DEFAULT_LLM_PROVIDER="openrouter",
                         LLM_REASONING_EFFORT="low")
        seen = {}

        async def fake_chat(messages, **kwargs):
            seen.update(kwargs)
            return "ok"

        monkeypatch.setattr(client.llm, "chat", fake_chat, raising=False)

        await client._llm_chat([], extra_body={"reasoning": {"effort": "high"}})
        assert seen["extra_body"] == {"reasoning": {"effort": "high"}}

    async def test_no_extra_body_appears_when_the_setting_is_off(self, agent_import_path,
                                                                 monkeypatch):
        client = _reload(monkeypatch, DEFAULT_LLM_PROVIDER="openrouter",
                         LLM_REASONING_EFFORT="")
        seen = {}

        async def fake_chat(messages, **kwargs):
            seen.update(kwargs)
            return "ok"

        monkeypatch.setattr(client.llm, "chat", fake_chat, raising=False)

        await client._llm_chat([])
        assert "extra_body" not in seen
