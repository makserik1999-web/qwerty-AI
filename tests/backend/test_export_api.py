"""Queueing an export, and who is allowed to.

The interesting cases here are all refusals. Encoding is the most expensive
thing a logged-in user can ask for, and the result is a file served back by
id - so the checks that matter are "is this your message" and "is this your
job", not the happy path.
"""

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
async def owned_video_message(backend, client, new_user):
    """A signed-in user with a chat holding one video message."""
    user = new_user()
    assert client.post(
        "/api/auth/login", json={"username": user["username"], "password": user["password"]}
    ).status_code == 200

    chat = await backend.db.db.chats.insert_one(
        {"user_id": user["id"], "title": "Gravity", "updated_at": datetime.now(timezone.utc)}
    )
    message = await backend.db.db.messages.insert_one(
        {
            "chat_id": str(chat.inserted_id),
            "role": "assistant",
            "content": "Что такое гравитация",
            "video_url": "/media/rendered_1.mp4",
            "timestamp": datetime.now(timezone.utc),
        }
    )
    return {"user": user, "chat_id": str(chat.inserted_id),
            "message_id": str(message.inserted_id)}


VALID_PARAMS = {"start": 1.0, "end": 6.0, "fps": 15, "width": 640}


def _queue(client, message_id, job_type="gif", **params):
    return client.post(
        "/api/export",
        json={"type": job_type, "message_id": message_id,
              "params": {**VALID_PARAMS, **params}},
    )


# ------------------------------------------------------------ happy path ----


async def test_a_valid_request_is_queued(client, owned_video_message):
    response = _queue(client, owned_video_message["message_id"])

    assert response.status_code == 202, response.text
    assert response.json()["job_id"]


async def test_a_queued_job_is_visible_to_its_owner(client, owned_video_message):
    job_id = _queue(client, owned_video_message["message_id"]).json()["job_id"]

    status = client.get(f"/api/export/{job_id}")

    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["progress"] == 0


# --------------------------------------------------------------- access ----


async def test_an_anonymous_request_is_refused(anon_client, owned_video_message):
    response = _queue(anon_client, owned_video_message["message_id"])
    assert response.status_code == 401


async def test_you_cannot_export_from_someone_elses_message(
    backend, client, new_user, owned_video_message
):
    """The message id is a guessable ObjectId, so ownership is what protects it."""
    other = new_user()
    client.post("/api/auth/login",
                json={"username": other["username"], "password": other["password"]})

    response = _queue(client, owned_video_message["message_id"])

    # 404, not 403: a different answer would confirm the message exists.
    assert response.status_code == 404


async def test_you_cannot_read_someone_elses_job(backend, client, new_user, owned_video_message):
    job_id = _queue(client, owned_video_message["message_id"]).json()["job_id"]

    other = new_user()
    client.post("/api/auth/login",
                json={"username": other["username"], "password": other["password"]})

    assert client.get(f"/api/export/{job_id}").status_code == 404
    assert client.get(f"/api/export/{job_id}/download").status_code == 404


async def test_a_nonsense_job_id_is_not_found(client, owned_video_message):
    assert client.get("/api/export/not-an-objectid").status_code == 404


# ----------------------------------------------------------- validation ----


async def test_an_unknown_export_type_is_refused(client, owned_video_message):
    response = _queue(client, owned_video_message["message_id"], job_type="exe")
    assert response.status_code == 400


async def test_an_empty_selection_is_refused(client, owned_video_message):
    response = _queue(client, owned_video_message["message_id"], start=5.0, end=5.0)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


async def test_a_backwards_selection_is_refused(client, owned_video_message):
    assert _queue(client, owned_video_message["message_id"],
                  start=9.0, end=2.0).status_code == 400


async def test_an_over_long_selection_is_refused(client, backend, owned_video_message):
    """Refused while the dialog is open, not a minute later in the worker."""
    limit = backend.config.EXPORT_MAX_CLIP_SEC
    response = _queue(client, owned_video_message["message_id"], start=0.0, end=limit + 5)

    assert response.status_code == 400
    assert str(int(limit)) in response.json()["detail"]


@pytest.mark.parametrize("bad", [{"fps": 60}, {"width": 4096}, {"fps": 0}])
async def test_out_of_range_encoder_settings_are_refused(client, owned_video_message, bad):
    assert _queue(client, owned_video_message["message_id"], **bad).status_code == 400


async def test_a_message_without_a_video_is_refused(backend, client, owned_video_message):
    text_only = await backend.db.db.messages.insert_one(
        {"chat_id": owned_video_message["chat_id"], "role": "assistant",
         "content": "text", "video_url": None, "timestamp": datetime.now(timezone.utc)}
    )
    response = _queue(client, str(text_only.inserted_id))

    assert response.status_code == 400
    assert "no video" in response.json()["detail"].lower()


async def test_a_collected_video_reports_gone(backend, client, owned_video_message):
    """Retention may have removed the file since the chat was written."""
    from bson import ObjectId
    await backend.db.db.messages.update_one(
        # By id: the mock database is shared for the session, and matching on
        # video_url would rewrite another test's message.
        {"_id": ObjectId(owned_video_message["message_id"])},
        {"$set": {"video_url": "/media/rendered_missing.mp4"}},
    )
    response = _queue(client, owned_video_message["message_id"])

    assert response.status_code == 410


# ---------------------------------------------------------- rate limiting --


async def test_the_hourly_export_budget_is_enforced(backend, client, owned_video_message):
    limit = backend.config.EXPORT_MAX_PER_HOUR
    for _ in range(limit):
        assert _queue(client, owned_video_message["message_id"]).status_code == 202

    response = _queue(client, owned_video_message["message_id"])

    assert response.status_code == 429
    assert str(limit) in response.json()["detail"]


async def test_the_budget_only_counts_the_last_hour(backend, client, owned_video_message):
    limit = backend.config.EXPORT_MAX_PER_HOUR
    for _ in range(limit):
        _queue(client, owned_video_message["message_id"])
    # Age the jobs out of the window.
    await backend.db.db.export_jobs.update_many(
        {}, {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(hours=2)}}
    )

    assert _queue(client, owned_video_message["message_id"]).status_code == 202


# -------------------------------------------------------------- download ---


async def test_an_unfinished_export_is_not_downloadable(client, owned_video_message):
    job_id = _queue(client, owned_video_message["message_id"]).json()["job_id"]

    response = client.get(f"/api/export/{job_id}/download")

    assert response.status_code == 409


async def test_a_finished_export_downloads_with_a_readable_name(
    backend, client, owned_video_message
):
    job_id = _queue(client, owned_video_message["message_id"]).json()["job_id"]
    result = backend.config.EXPORT_DIR
    result.mkdir(parents=True, exist_ok=True)
    (result / "gif_abc123.gif").write_bytes(b"GIF89a-not-really")
    from bson import ObjectId
    await backend.db.db.export_jobs.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"status": "done", "output_path": "gif_abc123.gif", "output_bytes": 17}},
    )

    response = client.get(f"/api/export/{job_id}/download")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    # The question, transliterated - not the generated "gif_abc123.gif".
    assert "Chto-takoe-gravitatsiya.gif" in disposition
    assert "filename*=UTF-8''" in disposition


async def test_a_job_pointing_outside_the_export_dir_is_refused(
    backend, client, owned_video_message
):
    """Defence in depth: the worker writes this name, but it is still checked."""
    job_id = _queue(client, owned_video_message["message_id"]).json()["job_id"]
    from bson import ObjectId
    await backend.db.db.export_jobs.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"status": "done", "output_path": "../../etc/passwd"}},
    )

    assert client.get(f"/api/export/{job_id}/download").status_code == 404
