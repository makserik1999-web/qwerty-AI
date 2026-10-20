"""The agent asks for the key of the provider it actually uses.

It used to check GEMINI_API_KEY whatever DEFAULT_LLM_PROVIDER said. A server
with only an OpenRouter key - the default provider, and the one production
runs on - answered every text question with "add GEMINI_API_KEY", and every
screenshot failed with "GEMINI_API_KEY is required for image analysis".
"""

import asyncio
import json

import httpx
import pytest


@pytest.fixture
def client(agent_import_path, monkeypatch):
    import agent_ws_client

    return agent_ws_client


class TestTheKeyThatIsChecked:
    def test_openrouter_provider_needs_the_openrouter_key(self, client, monkeypatch):
        monkeypatch.setattr(client, "DEFAULT_LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        assert client._llm_key_name() == "OPENROUTER_API_KEY"
        assert client._llm_key_configured()

    def test_openrouter_provider_without_its_key_is_not_configured(self, client, monkeypatch):
        """A Gemini key does not make an OpenRouter deployment work."""
        monkeypatch.setattr(client, "DEFAULT_LLM_PROVIDER", "openrouter")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")

        assert not client._llm_key_configured()

    def test_gemini_provider_still_needs_the_gemini_key(self, client, monkeypatch):
        monkeypatch.setattr(client, "DEFAULT_LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")

        assert client._llm_key_name() == "GEMINI_API_KEY"
        assert client._llm_key_configured()

    def test_no_provider_keeps_the_old_check(self, client, monkeypatch):
        monkeypatch.setattr(client, "DEFAULT_LLM_PROVIDER", "")

        assert client._llm_key_name() == "GEMINI_API_KEY"

    def test_a_blank_key_is_not_a_key(self, client, monkeypatch):
        monkeypatch.setattr(client, "DEFAULT_LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("OPENROUTER_API_KEY", "   ")

        assert not client._llm_key_configured()

    def test_the_message_names_the_missing_key(self, client, monkeypatch):
        monkeypatch.setattr(client, "DEFAULT_LLM_PROVIDER", "openrouter")

        message = client._no_key_message()
        assert "OPENROUTER_API_KEY" in message
        assert "GEMINI" not in message


class TestTextQuestionGate:
    async def test_without_the_key_the_reply_is_the_polite_message(self, client, monkeypatch):
        monkeypatch.setattr(client, "DEFAULT_LLM_PROVIDER", "openrouter")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setattr(client, "DOC_SNIPPET_MODE", "0")

        reply = await client.process_request({"request_id": "r1", "text": "что такое сила"})

        assert reply["status"] == "complete"
        assert "OPENROUTER_API_KEY" in reply["text"]
        assert reply["video_path"] == ""


# ------------------------------------------------------------------ vision --


@pytest.fixture
def vision(agent_import_path):
    import anyq.vision as vision

    return vision


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "task.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return path


def _reply(content, finish_reason="stop"):
    return {"choices": [{"finish_reason": finish_reason, "message": {"content": content}}]}


class TestVisionThroughOpenRouter:
    def _patch_post(self, monkeypatch, responses):
        """Answer each httpx.post with the next response, recording requests."""
        sent = []

        def fake_post(url, json=None, headers=None, timeout=None):
            sent.append({"url": url, "json": json, "headers": headers})
            status, body = responses.pop(0)
            return httpx.Response(status, json=body, request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx, "post", fake_post)
        return sent

    def test_the_image_travels_as_a_data_url_with_the_bearer_key(self, vision, image, monkeypatch):
        payload = {"summary": "A right triangle", "extracted_text": "a=3, b=4",
                   "highlighted_or_annotated": "", "question_focus_guess": "hypotenuse"}
        sent = self._patch_post(monkeypatch, [(200, _reply(json.dumps(payload)))])

        context, raw = vision._analyze_one_image_openrouter_sync(
            image_path=str(image), user_q="найди гипотенузу",
            api_key="sk-or-test", model="google/gemini-3.8-flash",
        )

        request = sent[0]
        assert request["url"] == "https://openrouter.ai/api/v1/chat/completions"
        assert request["headers"]["Authorization"] == "Bearer sk-or-test"
        assert request["json"]["model"] == "google/gemini-3.8-flash"
        parts = request["json"]["messages"][0]["content"]
        assert parts[0]["type"] == "text" and "найди гипотенузу" in parts[0]["text"]
        assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "Image summary: A right triangle" in context
        assert "Extracted text: a=3, b=4" in context
        assert json.loads(raw)["summary"] == "A right triangle"

    def test_a_transient_failure_is_retried(self, vision, image, monkeypatch):
        monkeypatch.setattr(vision, "_LLM_RETRY_BASE_DELAY", 0)
        sent = self._patch_post(monkeypatch, [
            (503, {"error": {"message": "overloaded"}}),
            (200, _reply('{"summary": "ok"}')),
        ])

        context, _ = vision._analyze_one_image_openrouter_sync(
            image_path=str(image), user_q="q", api_key="k", model="m")

        assert len(sent) == 2
        assert "Image summary: ok" in context

    def test_finish_reason_error_is_retried_not_returned_empty(self, vision, image, monkeypatch):
        monkeypatch.setattr(vision, "_LLM_RETRY_BASE_DELAY", 0)
        sent = self._patch_post(monkeypatch, [
            (200, _reply("", finish_reason="error")),
            (200, _reply('{"summary": "second try"}')),
        ])

        context, _ = vision._analyze_one_image_openrouter_sync(
            image_path=str(image), user_q="q", api_key="k", model="m")

        assert len(sent) == 2
        assert "second try" in context

    def test_a_bad_key_is_not_retried(self, vision, image, monkeypatch):
        sent = self._patch_post(monkeypatch, [(401, {"error": {"message": "No auth credentials"}})])

        with pytest.raises(RuntimeError, match="401"):
            vision._analyze_one_image_openrouter_sync(
                image_path=str(image), user_q="q", api_key="bad", model="m")
        assert len(sent) == 1


class TestWhichProviderReadsTheImage:
    def _run(self, vision, image):
        return asyncio.run(vision.analyze_image_with_gemini({"image_path": str(image), "user_message": "q"}))

    def _record(self, monkeypatch, vision, name):
        calls = []

        def fake(**kwargs):
            calls.append((name, kwargs["api_key"], kwargs["model"]))
            return ("ctx", "{}")

        monkeypatch.setattr(vision, name, fake)
        return calls

    def test_gemini_key_keeps_the_google_path(self, vision, image, monkeypatch):
        monkeypatch.setattr(vision, "GEMINI_API_KEY", "AIza-test")
        monkeypatch.setattr(vision, "OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setattr(vision, "DOC_SNIPPET_MODE", "0")
        google = self._record(monkeypatch, vision, "_analyze_one_image_sync")
        openrouter = self._record(monkeypatch, vision, "_analyze_one_image_openrouter_sync")

        self._run(vision, image)

        assert google and not openrouter
        assert google[0][1] == "AIza-test"

    def test_only_an_openrouter_key_uses_openrouter(self, vision, image, monkeypatch):
        monkeypatch.setattr(vision, "GEMINI_API_KEY", "")
        monkeypatch.setattr(vision, "OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setattr(vision, "OPENROUTER_MODEL", "google/gemini-3.8-flash")
        monkeypatch.setattr(vision, "DOC_SNIPPET_MODE", "0")
        google = self._record(monkeypatch, vision, "_analyze_one_image_sync")
        openrouter = self._record(monkeypatch, vision, "_analyze_one_image_openrouter_sync")

        result = self._run(vision, image)

        assert openrouter and not google
        assert openrouter[0][1:] == ("sk-or-test", "google/gemini-3.8-flash")
        assert "ctx" in result["image_context"]

    def test_no_key_at_all_names_both(self, vision, image, monkeypatch):
        monkeypatch.setattr(vision, "GEMINI_API_KEY", "")
        monkeypatch.setattr(vision, "OPENROUTER_API_KEY", "")
        monkeypatch.setattr(vision, "DOC_SNIPPET_MODE", "0")

        with pytest.raises(RuntimeError, match="GEMINI_API_KEY or OPENROUTER_API_KEY"):
            self._run(vision, image)
