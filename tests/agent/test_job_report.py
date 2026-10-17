"""What the agent tells the backend about each generation, for the task log.

The render time, the type of a failure (a class name, never the message), and
how many characters went to Azure - every synthesis, a repair attempt's too.
And a heartbeat, so the admin panel can say whether the agent is busy.
"""

import asyncio
import json

import pytest


@pytest.fixture
def client(agent_import_path):
    import agent_ws_client

    return agent_ws_client


class TestTheReport:
    def test_the_runner_adds_the_time_to_any_answer(self, client, monkeypatch):
        async def answered(payload):
            return {"request_id": payload["request_id"], "status": "error",
                    "error_type": "RenderError", "tts_chars": 120}

        monkeypatch.setattr(client, "process_request", answered)
        resp = asyncio.run(client._run_one_generation({"request_id": "r1", "text": "q"}))
        assert resp["error_type"] == "RenderError" and resp["tts_chars"] == 120
        assert isinstance(resp["elapsed_sec"], float)

    def test_a_timeout_says_so(self, client, monkeypatch):
        async def slow(payload):
            await asyncio.sleep(5)

        monkeypatch.setattr(client, "process_request", slow)
        monkeypatch.setattr(client, "REQUEST_DEADLINE_SEC", 0.01)
        resp = asyncio.run(client._run_one_generation({"request_id": "r2", "text": "q"}))
        assert resp["status"] == "error" and resp["error_type"] == "timeout"
        assert "elapsed_sec" in resp and "tts_chars" in resp

    def test_characters_are_counted_once(self, client):
        from anyq import narration

        narration._spent_chars = 300
        assert narration.take_spent() == 300
        assert narration.take_spent() == 0

    def test_the_heartbeat_is_declared(self, client, monkeypatch):
        sent = []

        class _Socket:
            async def send(self, raw):
                sent.append(json.loads(raw))

            async def recv(self):
                return json.dumps({"type": "auth_ok"})

        monkeypatch.setattr(client, "AGENT_SECRET", "s")
        assert asyncio.run(client._authenticate(_Socket()))
        assert "heartbeat" in sent[0]["features"]
