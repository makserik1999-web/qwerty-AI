"""How much of a video stands still, and that it reaches the telemetry.

motion_metric runs ffmpeg's freezedetect over the finished file; these tests
pin how its log is read - a freeze still running at the end of the video
counts to the end - and that render_video records the numbers (and the
render's own duration) without ever failing a render over them.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "agent", REPO_ROOT / "tests" / "stubs",
              REPO_ROOT / "agent" / "manim-mcp-server" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from anyq import motion_metric  # noqa: E402

HEADER = "  Duration: 00:00:32.33, start: 0.000000, bitrate: 512 kb/s\n"


def _event(kind: str, value: float) -> str:
    return f"[freezedetect @ 0x5d41] lavfi.freezedetect.freeze_{kind}: {value}\n"


class TestReadingTheLog:
    def test_freezes_are_summed(self):
        log = (HEADER + _event("start", 2.0) + "[freezedetect @ 0x5d41] "
               "lavfi.freezedetect.freeze_duration: 1.5\n" + _event("end", 3.5)
               + _event("start", 10.0) + _event("end", 10.5))

        assert motion_metric.parse(log) == {
            "static_seconds": 2.0, "static_share": round(2.0 / 32.33, 4), "duration": 32.33,
        }

    def test_a_freeze_running_at_the_end_lasts_to_the_end(self):
        """The last sentence of an old video is a still frame to the last
        second, and freezedetect never reports its end."""
        log = HEADER + _event("start", 30.0)

        assert motion_metric.parse(log)["static_seconds"] == pytest.approx(2.33)

    def test_a_video_that_never_stands_still(self):
        assert motion_metric.parse(HEADER) == {
            "static_seconds": 0.0, "static_share": 0.0, "duration": 32.33,
        }

    def test_no_duration_is_unmeasured_not_zero(self):
        assert motion_metric.parse(_event("start", 1.0)) == {}

    def test_a_given_duration_wins(self):
        assert motion_metric.parse(_event("start", 8.0), duration=10.0)["static_share"] == 0.2

    def test_the_command_is_the_documented_one(self):
        cmd = motion_metric.command("/v.mp4")
        assert "freezedetect=n=-66dB:d=0.3" in cmd

    def test_no_file_is_unmeasured(self):
        assert motion_metric.measure("") == {}
        assert motion_metric.measure("/nonexistent/video.mp4") == {}


# ----------------------------------------------------------- render_video --


class _FakeTool:
    def __init__(self, *a, **k):
        pass

    async def call_mcp_tool(self, name, **kwargs):
        return json.dumps({"status": "ok", "success": True, "video_path": "/media/v.mp4"})


@pytest.fixture
def render(agent_telemetry, monkeypatch):
    from anyq import render as module

    monkeypatch.setattr(module, "MCPTool", _FakeTool)
    monkeypatch.setattr(module, "MANIM_MCP_SERVER_SCRIPT", "/srv/manim_server.py")
    measured = []

    def measure(path):
        measured.append(path)
        return {"static_seconds": 0.6, "static_share": 0.0186, "duration": 32.3}

    monkeypatch.setattr(module.motion_metric, "measure", measure)
    module.measured = measured
    return module


SCRIPT = ("from manim import *\nfrom anyq_narration import VoiceoverScene\n\n"
          "class Demo(VoiceoverScene):\n    def construct(self):\n        pass\n")


async def _run(render, agent_telemetry):
    agent_telemetry.new_run("req", "q")
    result = await render.render_video({"manim_script": SCRIPT, "narration": False})
    agent_telemetry.write()
    lines = Path(agent_telemetry.ANYQ_TELEMETRY_PATH).read_text(encoding="utf-8").splitlines()
    return result, json.loads(lines[-1])


class TestTheTelemetry:
    async def test_render_time_is_always_recorded(self, render, agent_telemetry, monkeypatch):
        monkeypatch.setattr(render, "MOTION_LAYER", False)
        monkeypatch.setattr(render, "MOTION_METRIC", False)

        result, line = await _run(render, agent_telemetry)

        assert result["video_path"] == "/media/v.mp4"
        assert isinstance(line["render_seconds"], float)
        assert line["static_share"] is None and render.measured == []

    async def test_with_the_metric_on_the_stillness_is_recorded(self, render, agent_telemetry,
                                                                monkeypatch):
        monkeypatch.setattr(render, "MOTION_LAYER", False)
        monkeypatch.setattr(render, "MOTION_METRIC", True)

        _, line = await _run(render, agent_telemetry)

        assert render.measured == ["/media/v.mp4"]
        assert line["static_seconds"] == 0.6 and line["static_share"] == 0.0186

    async def test_an_unmeasured_video_still_renders(self, render, agent_telemetry, monkeypatch):
        monkeypatch.setattr(render, "MOTION_METRIC", True)
        monkeypatch.setattr(render.motion_metric, "measure", lambda path: {})

        result, line = await _run(render, agent_telemetry)

        assert result["video_path"] == "/media/v.mp4"
        assert line["static_share"] is None
