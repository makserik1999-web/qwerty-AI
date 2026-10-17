"""Media retention: what gets deleted under disk pressure, and what never does.

Deleting the wrong file is expensive and irreversible - a curated video costs
a person's review time, and a video someone is watching right now costs their
trust. Both protections are asserted rather than assumed.
"""

import time
from pathlib import Path

import pytest


@pytest.fixture
def retention(backend):
    from app.services import retention as module

    return module


@pytest.fixture
def library(backend):
    from app.repositories import library as lib

    return lib


@pytest.fixture
async def media(backend, tmp_path, monkeypatch):
    """An isolated media directory, with the config pointed at it."""
    monkeypatch.setattr(backend.config, "MEDIA_DIR", tmp_path)
    await backend.db.db.library_entries.delete_many({})
    await backend.db.db.messages.delete_many({})
    yield tmp_path


def _write(directory: Path, name: str, size: int, age_hours: float = 100.0) -> Path:
    path = directory / name
    path.write_bytes(b"x" * size)
    old = time.time() - age_hours * 3600
    import os

    os.utime(path, (old, old))
    return path


async def test_nothing_is_deleted_while_under_budget(retention, media, monkeypatch):
    _write(media, "a.mp4", 1000)
    monkeypatch.setattr(retention, "MEDIA_MAX_BYTES", 10_000)

    result = await retention.collect_garbage()

    assert result["status"] == "under_budget"
    assert result["deleted"] == 0
    assert (media / "a.mp4").exists()


async def test_files_are_deleted_once_over_the_high_water_mark(retention, media, monkeypatch):
    for i in range(5):
        _write(media, f"f{i}.mp4", 1000)
    monkeypatch.setattr(retention, "MEDIA_MAX_BYTES", 4000)  # 5000 used, 90% of 4000 exceeded

    result = await retention.collect_garbage()

    assert result["status"] == "collected"
    assert result["deleted"] >= 1
    assert result["used_bytes"] <= 4000 * retention.MEDIA_GC_LOW_WATER


async def test_a_curated_video_is_never_deleted(retention, media, library, monkeypatch):
    _write(media, "curated.mp4", 5000)
    _write(media, "throwaway.mp4", 5000)
    await library.store_entry(
        cache_key="c", normalized="gravity", educator_text="reviewed",
        video_url="/media/curated.mp4", tier=library.TIER_CURATED,
    )
    monkeypatch.setattr(retention, "MEDIA_MAX_BYTES", 1000)

    await retention.collect_garbage()

    assert (media / "curated.mp4").exists(), "a hand-reviewed video must survive collection"
    assert not (media / "throwaway.mp4").exists()


async def test_a_freshly_rendered_video_is_never_deleted(retention, media, monkeypatch):
    """Someone may be watching it right now."""
    _write(media, "brand_new.mp4", 5000, age_hours=0.1)
    _write(media, "old.mp4", 5000, age_hours=200)
    monkeypatch.setattr(retention, "MEDIA_MAX_BYTES", 1000)

    await retention.collect_garbage()

    assert (media / "brand_new.mp4").exists()
    assert not (media / "old.mp4").exists()


async def test_popular_files_outlive_unused_ones(retention, media, library, monkeypatch):
    _write(media, "popular.mp4", 5000)
    _write(media, "ignored.mp4", 5000)
    await library.store_entry(
        cache_key="p", normalized="popular", educator_text="t",
        video_url="/media/popular.mp4",
    )
    await library.store_entry(
        cache_key="i", normalized="ignored", educator_text="t",
        video_url="/media/ignored.mp4",
    )
    await retention.db.db.library_entries.update_one(
        {"cache_key": "p"}, {"$set": {"hits": 50}}
    )
    # Sized so collection triggers (10000 > 90% of 8000) but stops after one
    # deletion (5000 fits under the 75% low-water target of 6000). Any tighter
    # budget legitimately requires deleting both.
    monkeypatch.setattr(retention, "MEDIA_MAX_BYTES", 8000)

    await retention.collect_garbage()

    assert (media / "popular.mp4").exists(), "the file people actually watch should be kept"
    assert not (media / "ignored.mp4").exists()


async def test_deleting_a_file_clears_the_references_to_it(retention, media, backend, monkeypatch):
    """An old chat should lose the video, not gain a broken player."""
    _write(media, "doomed.mp4", 5000)
    await backend.db.db.messages.insert_one(
        {"chat_id": "c1", "role": "assistant", "content": "text", "video_url": "/media/doomed.mp4"}
    )
    await backend.db.db.chats.insert_one(
        {"user_id": "u1", "title": "t", "current_video_url": "/media/doomed.mp4"}
    )
    monkeypatch.setattr(retention, "MEDIA_MAX_BYTES", 100)

    await retention.collect_garbage()

    message = await backend.db.db.messages.find_one({"chat_id": "c1"})
    assert message["video_url"] is None, "a message must not point at a deleted file"
    assert message["content"] == "text", "the explanation itself must survive"

    chat = await backend.db.db.chats.find_one({"user_id": "u1"})
    assert chat["current_video_url"] is None


async def test_a_dry_run_reports_without_deleting(retention, media, monkeypatch):
    for i in range(5):
        _write(media, f"f{i}.mp4", 1000)
    monkeypatch.setattr(retention, "MEDIA_MAX_BYTES", 1000)

    result = await retention.collect_garbage(dry_run=True)

    assert result["deleted"] >= 1
    assert result["dry_run"] is True
    assert len(list(media.iterdir())) == 5, "a dry run must not touch the disk"


async def test_being_unable_to_free_enough_is_reported(retention, media, library, monkeypatch):
    """All curated and still over budget: say so instead of deleting anyway."""
    _write(media, "curated.mp4", 10_000)
    await library.store_entry(
        cache_key="c", normalized="g", educator_text="t",
        video_url="/media/curated.mp4", tier=library.TIER_CURATED,
    )
    monkeypatch.setattr(retention, "MEDIA_MAX_BYTES", 1000)

    result = await retention.collect_garbage()

    assert result["status"] == "still_over_budget"
    assert (media / "curated.mp4").exists()
