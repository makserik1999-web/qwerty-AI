"""The export path against the running stack: queue, encode, download.

The unit tests cover what the API refuses. This covers the part only a real
ffmpeg can answer: that the queued job is picked up, that the file it produces
is the format it claims, and that a GIF of a few seconds does not come back
enormous - the whole reason the size budget exists.
"""

import json
import subprocess
import time
import uuid

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not __import__("os").environ.get("ANYQ_STACK_UP"),
        reason="needs the docker stack - run `make up` and set ANYQ_STACK_UP=1",
    ),
]

BASE = "http://localhost:3000"
PASSWORD = "password123"
POLL_TIMEOUT_SEC = 180


def _mongo(script: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "mongo", "mongosh", "anyq_db", "--quiet", "--eval", script],
        capture_output=True, timeout=60,
    )
    return proc.stdout.decode("utf-8", "replace").strip()


def _newest_video() -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "sh", "-c",
         "ls -S /app/media/outputs/*.mp4 2>/dev/null | head -1"],
        capture_output=True, timeout=60,
    )
    name = proc.stdout.decode().strip().rsplit("/", 1)[-1]
    if not name.endswith(".mp4"):
        pytest.skip("no rendered video in the media volume")
    return name


@pytest.fixture
def exporter_ready():
    """Skip rather than fail when the export worker is not running."""
    proc = subprocess.run(
        ["docker", "compose", "ps", "--status", "running", "--format", "{{.Name}}"],
        capture_output=True, timeout=30,
    )
    if "anyq-exporter" not in proc.stdout.decode():
        pytest.skip("the exporter service is not running")


@pytest.fixture
def signed_in(exporter_ready):
    """A user with a chat holding one message pointing at a real video."""
    import httpx

    video = _newest_video()
    username = f"exp_{uuid.uuid4().hex[:8]}"

    client = httpx.Client(base_url=BASE, timeout=60)
    assert client.post(
        "/api/auth/signup", json={"username": username, "password": PASSWORD}
    ).status_code == 201
    user_id = client.get("/api/auth/me").json()["user"]["id"]

    payload = json.dumps({"uid": user_id, "video": f"/media/{video}"})
    out = _mongo(
        f"const p = {payload}; const now = new Date();"
        "const chat = db.chats.insertOne({user_id: p.uid, title: 'Export', "
        "  created_at: now, updated_at: now, current_video_url: p.video});"
        "const msg = db.messages.insertOne({chat_id: chat.insertedId.toString(), "
        "  role: 'assistant', content: 'Что такое гравитация', screenshots: [], "
        "  video_url: p.video, timestamp: now});"
        "print(msg.insertedId.toString());"
    )
    message_id = out.splitlines()[-1].strip()
    assert len(message_id) == 24, f"unexpected message id: {out!r}"

    yield client, message_id
    client.close()


def _run_export(client, message_id, job_type, params):
    response = client.post(
        "/api/export",
        json={"type": job_type, "message_id": message_id, "params": params},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    deadline = time.time() + POLL_TIMEOUT_SEC
    while time.time() < deadline:
        state = client.get(f"/api/export/{job_id}").json()
        if state["status"] in ("done", "failed"):
            return state
        time.sleep(1.5)
    pytest.fail(f"export {job_id} never finished")


def test_a_gif_is_produced_and_stays_within_budget(signed_in):
    client, message_id = signed_in

    state = _run_export(client, message_id, "gif",
                        {"start": 2.0, "end": 7.0, "fps": 15, "width": 480})

    assert state["status"] == "done", state.get("error")
    assert 0 < state["output_bytes"] <= 20 * 1024 * 1024, "the size budget did not hold"

    download = client.get(state["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/gif"
    # Real GIF bytes, not an empty file with the right name.
    assert download.content[:6] in (b"GIF87a", b"GIF89a")
    assert "attachment;" in download.headers["content-disposition"]


def test_an_mp4_clip_is_much_smaller_than_the_gif(signed_in):
    """The reason mp4 is the preselected format, measured rather than assumed."""
    client, message_id = signed_in
    params = {"start": 2.0, "end": 7.0, "fps": 15, "width": 480}

    gif = _run_export(client, message_id, "gif", params)
    clip = _run_export(client, message_id, "clip", params)

    assert clip["status"] == "done", clip.get("error")
    assert clip["output_bytes"] < gif["output_bytes"], (
        f"mp4 {clip['output_bytes']} was not smaller than gif {gif['output_bytes']}"
    )

    download = client.get(clip["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "video/mp4"
    # An mp4 begins with a box length then "ftyp".
    assert download.content[4:8] == b"ftyp"


def test_the_whole_video_downloads_with_a_readable_name(signed_in):
    client, message_id = signed_in
    # The player links straight at the media path with ?download=1.
    name = _mongo(
        f"const m = db.messages.findOne({{_id: ObjectId('{message_id}')}});"
        "print(m.video_url);"
    ).splitlines()[-1].strip()

    response = client.get(f"{name}?download=1")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    # Named after the question, transliterated for the ASCII half.
    assert "Chto-takoe-gravitatsiya" in disposition
    assert "filename*=UTF-8''" in disposition
