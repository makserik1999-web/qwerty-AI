"""Telemetry must never persist the raw user message.

Converted from `logs/local_check.py`. The run log is written to disk and shipped
in container logs, so the question text is only ever recorded as a hash plus a
length.
"""

import json


def test_run_log_hashes_the_user_message(agent_telemetry):
    agent_telemetry.new_run("req-1", "my secret text")
    agent_telemetry.record(status="complete")
    agent_telemetry.write()

    with open(agent_telemetry.ANYQ_TELEMETRY_PATH, encoding="utf-8") as handle:
        entry = json.loads(handle.readline())

    assert "user_message" not in entry, "the raw question must never be logged"
    assert entry["user_message_sha256"], "the hash is what makes the entry traceable"
    assert entry["user_message_len"] == len("my secret text")
    assert entry["status"] == "complete"
