"""The trial mark on a video, and the clean render kept beside it."""

import asyncio
import re
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def wm(agent_import_path):
    import anyq.watermark as module

    return module


def test_the_marked_copy_sits_next_to_the_clean_one(wm):
    assert wm.marked_path("/media/outputs/rendered_7.mp4") == "/media/outputs/rendered_7_trial.mp4"


def test_the_text_goes_through_a_file_and_the_audio_is_kept(wm):
    cmd = wm.command("in.mp4", "out.mp4", "/tmp/wm_x.txt", 720)
    vf = cmd[cmd.index("-vf") + 1]
    assert "textfile=/tmp/wm_x.txt" in vf and ":text=" not in vf
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert "+faststart" in cmd


def test_the_mark_scales_with_the_video(wm):
    small = wm.command("i", "o", "t", 480)
    large = wm.command("i", "o", "t", 1080)
    size = lambda cmd: int(cmd[cmd.index("-vf") + 1].split("fontsize=")[1].split(":")[0])  # noqa: E731
    assert size(large) > size(small)


def test_apply_returns_the_marked_and_the_clean_path(wm, monkeypatch, tmp_path):
    src = tmp_path / "rendered_1.mp4"
    src.write_bytes(b"video")
    written = {}

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, stdout="720\n", stderr="")
        # Up to the next option, not the next colon: a Windows temp path has one.
        textfile = re.search(r"textfile=(.*?):fontsize=", cmd[cmd.index("-vf") + 1]).group(1)
        written["text"] = Path(textfile).read_text(encoding="utf-8")
        Path(cmd[-1]).write_bytes(b"marked")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(wm.subprocess, "run", fake_run)
    shown, clean = asyncio.run(wm.apply(str(src), "Akron · сынақ"))

    assert shown.endswith("rendered_1_trial.mp4") and clean == str(src)
    assert written["text"] == "Akron · сынақ"


def test_a_failed_mark_falls_back_to_the_clean_video(wm, monkeypatch, tmp_path):
    src = tmp_path / "rendered_2.mp4"
    src.write_bytes(b"video")

    def failing(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no font")

    monkeypatch.setattr(wm.subprocess, "run", failing)
    shown, clean = asyncio.run(wm.apply(str(src), "Akron · сынақ"))
    assert shown == clean == str(src)


def test_no_text_means_no_work(wm, monkeypatch):
    monkeypatch.setattr(wm.subprocess, "run", lambda *a, **k: pytest.fail("ffmpeg ran"))
    assert asyncio.run(wm.apply("/x/rendered_3.mp4", None)) == ("/x/rendered_3.mp4", "/x/rendered_3.mp4")
