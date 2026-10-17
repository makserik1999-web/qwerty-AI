"""Written papers left no trace at all, and adding one nearly broke videos.

`_handle_assessment` never called telemetry: a СОР returned 201 and nothing was
recorded, so how long one takes, how often the model comes back with fewer
questions than were asked for, and how often it fails outright could only be
answered by measuring again from scratch.

The hazard in fixing that is the reason these tests lead with it. The run
record was a single module-level slot, on the stated reasoning that the agent
"processes one websocket message at a time". That stopped being true when the
agent was split into a reader and a worker: an assessment now runs as its own
task ALONGSIDE a render. A second new_run() would have overwritten the video's
record, the graph's record() calls would have landed on the assessment, and
write() would have flushed a mixture of the two - quietly, into the only log
that exists.

A ContextVar is the shape of that problem: a task gets its own binding, while
a task spawned INSIDE a request still shares the same dict, which is what the
educate_and_script parallel group needs.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "agent", REPO_ROOT / "tests" / "stubs"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from anyq import telemetry  # noqa: E402


@pytest.fixture(autouse=True)
def log(tmp_path, monkeypatch):
    """Point the log at a temp file and hand back a reader for it."""
    path = tmp_path / "runs.jsonl"
    monkeypatch.setattr(telemetry, "ANYQ_TELEMETRY_PATH", str(path))
    telemetry._current.set(None)
    yield path
    telemetry._current.set(None)


def lines(path):
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln]


# ------------------------------------------- one record cannot clobber another --


class TestTwoRequestsAtOnce:
    async def test_a_video_and_an_assessment_do_not_share_a_record(self, log):
        """The bug this would have introduced, driven directly.

        Both tasks are started before either finishes, which is exactly what
        the reader/worker split made possible.
        """
        started = asyncio.Event()

        async def video():
            telemetry.new_run("vid-1", "почему лед не тает")
            started.set()
            await asyncio.sleep(0)          # let the assessment run its new_run
            telemetry.record(subject="physics", status="complete")
            telemetry.write()

        async def assessment():
            await started.wait()
            telemetry.new_run("ass-1", "Ньютон заңдары", kind="assessment")
            telemetry.record(subject="math", items_requested=5,
                             items_produced=5, status="complete")
            telemetry.write()

        await asyncio.gather(video(), assessment())

        written = {r["request_id"]: r for r in lines(log)}
        assert set(written) == {"vid-1", "ass-1"}
        assert written["vid-1"]["subject"] == "physics", (
            "the assessment overwrote the video's record"
        )
        assert written["ass-1"]["subject"] == "math"
        assert written["vid-1"]["kind"] == "video"
        assert written["ass-1"]["kind"] == "assessment"

    async def test_a_task_started_inside_a_request_shares_its_record(self, log):
        """The other half, and the one a ContextVar could have broken.

        educate_and_script runs two nodes concurrently inside ONE request.
        They inherit the binding, so they write to the same dict - if they did
        not, half of every video's line would be missing.
        """
        telemetry.new_run("vid-2", "q")

        async def node_a():
            telemetry.record(subject="physics")

        async def node_b():
            telemetry.record(language="ru")

        await asyncio.gather(node_a(), node_b())
        telemetry.record(status="complete")
        telemetry.write()

        (written,) = lines(log)
        assert written["subject"] == "physics"
        assert written["language"] == "ru"

    async def test_finishing_one_does_not_end_the_other(self, log):
        telemetry.new_run("outer", "q")

        async def other():
            telemetry.new_run("inner", "q2", kind="assessment")
            telemetry.write()

        await asyncio.create_task(other())

        telemetry.record(status="complete")
        telemetry.write()
        assert {r["request_id"] for r in lines(log)} == {"inner", "outer"}


# --------------------------------------------------- what an assessment records --


class TestWhatAPaperLeavesBehind:
    async def test_the_line_says_which_kind_of_request_it_was(self, log):
        telemetry.new_run("a1", "topic", kind="assessment")
        telemetry.write()
        assert lines(log)[0]["kind"] == "assessment"

    async def test_a_video_line_still_says_video_without_being_told(self, log):
        """Every existing caller passes no kind, and every existing reader
        expects the shape it had."""
        telemetry.new_run("v1", "q")
        telemetry.write()
        assert lines(log)[0]["kind"] == "video"

    async def test_a_short_paper_is_countable(self, log):
        """_validate reports a short paper rather than padding it. That is the
        right behaviour and was invisible: nobody could count how often the
        model returned four questions when five were asked for."""
        telemetry.new_run("a2", "topic", kind="assessment")
        telemetry.record(items_requested=5, items_produced=4, status="complete")
        telemetry.write()

        written = lines(log)[0]
        assert (written["items_requested"], written["items_produced"]) == (5, 4)

    async def test_the_topic_is_hashed_and_not_stored(self, log):
        """The same privacy rule as a question: length and a sha256, never the
        text. A topic is a teacher's own wording."""
        topic = "Ньютонның екінші заңы"
        telemetry.new_run("a3", topic, kind="assessment")
        telemetry.write()

        written = lines(log)[0]
        assert topic not in json.dumps(written, ensure_ascii=False)
        assert written["user_message_len"] == len(topic)

    async def test_a_failure_is_recorded_as_one(self, log):
        telemetry.new_run("a4", "topic", kind="assessment")
        telemetry.record(error_type="TimeoutError")
        telemetry.write()

        written = lines(log)[0]
        assert written["status"] == "error", "status defaults to error and stays"
        assert written["error_type"] == "TimeoutError"

    async def test_the_video_fields_are_left_alone_rather_than_invented(self, log):
        """One line shape for both kinds, so a reader needs no branch - but an
        assessment must not claim a render happened."""
        telemetry.new_run("a5", "topic", kind="assessment")
        telemetry.record(items_requested=5, items_produced=5, status="complete")
        telemetry.write()

        written = lines(log)[0]
        assert written["video_needed"] is False
        assert written["render_ok"] is False
        assert written["render_attempt"] is None
        assert written["video_length"] == ""


class TestTheHandlerActuallyCallsIt:
    """The tests above prove the mechanism; this proves it is wired up."""

    def test_handle_assessment_opens_and_closes_a_run(self):
        source = (REPO_ROOT / "agent" / "agent_ws_client.py").read_text(encoding="utf-8")
        handler = source[source.index("async def _handle_assessment"):]
        handler = handler[:handler.index("\nasync def ", 1)]
        assert 'kind="assessment"' in handler
        assert "telemetry.write()" in handler
        # In a finally, so a paper that raises still leaves a line saying so.
        assert "finally:" in handler

    def test_generate_assessment_records_the_counts(self):
        source = (REPO_ROOT / "agent" / "anyq" / "assessments.py").read_text(
            encoding="utf-8"
        )
        assert "items_requested=count" in source
        assert "items_produced=" in source
        assert "error_type=" in source
