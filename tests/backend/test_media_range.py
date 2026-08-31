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
