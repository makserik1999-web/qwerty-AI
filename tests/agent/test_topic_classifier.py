"""Filing a question under a topic: only ids from the list, and caution when unsure."""

import asyncio
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def intent(agent_import_path, monkeypatch):
    import anyq.nodes.intent as module

    def answer(payload):
        async def fake_chat(messages, **kwargs):
            fake_chat.messages = messages
            return SimpleNamespace(content=json.dumps(payload) if isinstance(payload, dict) else payload)
        monkeypatch.setattr(module, "_llm_chat", fake_chat)
        return fake_chat

    module.answer = answer
    return module


def run(coro):
    return asyncio.run(coro)


def test_a_known_topic_is_kept(intent):
    intent.answer({"specificity": "generic", "topic_id": "geom-8-pythagoras", "language": "kk"})
    assert run(intent.classify_request("Пифагор теоремасы деген не?")) == {
        "specificity": "generic", "topic_id": "geom-8-pythagoras", "language": "kk"}


def test_an_invented_topic_is_dropped(intent):
    intent.answer({"specificity": "generic", "topic_id": "geom-8-pythagoras-advanced", "language": "ru"})
    assert run(intent.classify_request("теорема Пифагора"))["topic_id"] is None


def test_an_unclear_answer_counts_as_specific(intent):
    intent.answer({"specificity": "maybe", "topic_id": "geom-8-pythagoras"})
    assert run(intent.classify_request("x"))["specificity"] == "specific"


def test_no_json_at_all_is_specific_with_no_topic(intent):
    intent.answer("I am not sure")
    out = run(intent.classify_request("x"))
    assert out == {"specificity": "specific", "topic_id": None, "language": ""}


def test_the_prompt_carries_the_rules_and_the_list(intent):
    chat = intent.answer({"specificity": "generic", "topic_id": None, "language": "ru"})
    run(intent.classify_request("что такое индукция"))
    system = chat.messages[0].content
    assert "SPECIFIC" in system and "GENERIC" in system
    assert "geom-8-pythagoras-converse" in system  # theorem and its converse are both listed


def test_the_list_is_loaded_once_and_complete(agent_import_path):
    from anyq import topics

    assert len(topics.topics()) > 300
    assert topics.by_id()["phys-8-ohm-law"]["grade"] == 8
