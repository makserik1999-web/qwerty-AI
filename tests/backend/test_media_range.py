"""Byte-range serving for /media.

Seeking in the browser depends entirely on these responses: without a 206 the
player has to download everything before the point it wants to jump to.
"""

import pytest


@pytest.fixture
def video(backend, client, new_user):
    """An authenticated client plus a known media file and its size."""
    new_user()
    path = backend.MEDIA_DIR / "rendered_1.mp4"
    return {"name": path.name, "size": path.stat().st_size}


def test_full_request_advertises_range_support(client, video):
    response = client.get(f"/media/{video['name']}")
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["etag"]
    assert "immutable" in response.headers["cache-control"]


def test_range_returns_partial_content(client, video):
    response = client.get(f"/media/{video['name']}", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-3/{video['size']}"
    assert response.headers["content-length"] == "4"
    assert response.content == b"fake"


def test_open_ended_range_runs_to_the_end(client, video):
    size = video["size"]
    response = client.get(f"/media/{video['name']}", headers={"Range": "bytes=5-"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 5-{size - 1}/{size}"
    assert len(response.content) == size - 5


def test_suffix_range_returns_the_tail(client, video):
    size = video["size"]
    response = client.get(f"/media/{video['name']}", headers={"Range": "bytes=-5"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes {size - 5}-{size - 1}/{size}"
    assert response.content == b"bytes"


def test_range_past_the_end_is_416(client, video):
    size = video["size"]
    response = client.get(f"/media/{video['name']}", headers={"Range": f"bytes={size}-"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{size}"


def test_end_beyond_the_file_is_clamped(client, video):
    size = video["size"]
    response = client.get(f"/media/{video['name']}", headers={"Range": "bytes=0-99999"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-{size - 1}/{size}"


def test_unparsable_range_serves_the_whole_file(client, video):
    response = client.get(f"/media/{video['name']}", headers={"Range": "pages=1-2"})
    assert response.status_code == 200
    assert len(response.content) == video["size"]


def test_if_range_with_a_stale_validator_serves_the_whole_file(client, video):
    response = client.get(
        f"/media/{video['name']}",
        headers={"Range": "bytes=0-3", "If-Range": '"not-the-current-etag"'},
    )
    assert response.status_code == 200
    assert len(response.content) == video["size"]


def test_if_range_with_the_current_validator_still_slices(client, video):
    etag = client.get(f"/media/{video['name']}").headers["etag"]
    response = client.get(
        f"/media/{video['name']}", headers={"Range": "bytes=0-3", "If-Range": etag}
    )
    assert response.status_code == 206


def test_range_still_requires_authentication(anon_client, video):
    response = anon_client.get(f"/media/{video['name']}", headers={"Range": "bytes=0-3"})
    assert response.status_code == 401


class TestDownloadNaming:
    """`?download=1` names the file after the question - whose question matters.

    The answer cache serves one rendered file to everyone who asks the same
    thing, so a lookup by video_url alone finds whichever user got there first.
    Naming a download after a stranger's wording is a small leak with a large
    surface: it lands in a folder, in a screenshot, in a shared drive.
    """

    async def _chat_with_video(self, backend, user_id, question, video="rendered_1.mp4"):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        chat = await backend.db.db.chats.insert_one(
            {"user_id": user_id, "title": "t", "updated_at": now}
        )
        await backend.db.db.messages.insert_one(
            {"chat_id": str(chat.inserted_id), "role": "user", "content": question,
             "timestamp": now - timedelta(seconds=1)}
        )
        await backend.db.db.messages.insert_one(
            {"chat_id": str(chat.inserted_id), "role": "assistant", "content": "answer",
             "video_url": f"/media/{video}", "timestamp": now}
        )

    async def test_the_download_is_named_after_your_own_question(
        self, backend, client, new_user
    ):
        user = new_user()
        client.post("/api/auth/login",
                    json={"username": user["username"], "password": user["password"]})
        await self._chat_with_video(backend, user["id"], "Что такое гравитация")

        response = client.get("/media/rendered_1.mp4?download=1")

        assert response.status_code == 200
        assert "Chto-takoe-gravitatsiya" in response.headers["content-disposition"]

    async def test_another_users_question_never_becomes_your_filename(
        self, backend, client, new_user
    ):
        stranger = new_user()
        await self._chat_with_video(backend, stranger["id"], "Мой личный вопрос")

        mine = new_user()
        client.post("/api/auth/login",
                    json={"username": mine["username"], "password": mine["password"]})
        # Same video file, reached through the cache - no message of my own.
        response = client.get("/media/rendered_1.mp4?download=1")

        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert "lichnyy" not in disposition.lower()
        assert "anyq-export" in disposition, "should fall back to the neutral name"

    async def test_a_plain_request_is_not_an_attachment(self, client, new_user):
        """Playback must not download: the header would break the player."""
        user = new_user()
        client.post("/api/auth/login",
                    json={"username": user["username"], "password": user["password"]})

        response = client.get("/media/rendered_1.mp4")

        assert response.status_code == 200
        assert "content-disposition" not in response.headers
