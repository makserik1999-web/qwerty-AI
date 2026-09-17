#!/usr/bin/env python3
"""Publish rendered curated videos into the library.

    ... | docker compose exec -T backend python scripts/register_curated.py

Reads one JSON manifest on stdin:

    {"pipeline_version": "v1",
     "entries": [{"topic_id": "physics.gravity_basics", "language": "ru",
                  "aliases": ["что такое гравитация", ...],
                  "educator_text": "...", "video_url": "/media/x.mp4"}]}

It lives inside the backend image because that is where the database is, and
because the cache keys must be computed by the very code that later looks
them up - a second copy of the normaliser would drift, and the failure would
be a curated video that silently never matches anything.

Reading from stdin rather than from the content tree is deliberate: the
container has no access to content/, and the host driver already knows which
languages a person approved.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache.normalize import cache_key, normalize_question  # noqa: E402
from app.config import DATABASE_NAME, MONGO_URL, PIPELINE_VERSION  # noqa: E402
from app.db import db  # noqa: E402
from app.repositories.library import replace_curated_topic  # noqa: E402


async def publish(manifest: dict) -> dict:
    pipeline_version = manifest.get("pipeline_version") or PIPELINE_VERSION
    report = {"published": [], "skipped": [], "pipeline_version": pipeline_version}

    for entry in manifest.get("entries", []):
        topic_id = entry.get("topic_id", "")
        language = entry.get("language", "")
        video_url = entry.get("video_url", "")

        keys = {}
        dropped = []
        for alias in entry.get("aliases", []):
            normalized = normalize_question(alias)
            if not normalized:
                # An alias that normalises to nothing can never be matched;
                # say so instead of publishing a key nobody can reach.
                dropped.append(alias)
                continue
            # Curated videos are rendered by scripts/seed_library.py, which does
            # not narrate, so they are registered as the silent variant. They
            # will not answer a request made with the voice on - re-render and
            # re-seed the library once narration is part of the seeding flow.
            keys[cache_key(normalized, pipeline_version, "silent")] = normalized

        if not keys:
            report["skipped"].append(
                {"topic_id": topic_id, "language": language, "reason": "no usable aliases"}
            )
            continue

        result = await replace_curated_topic(
            topic_id=topic_id,
            language=language,
            keys=keys,
            educator_text=entry.get("educator_text", ""),
            video_url=video_url,
            pipeline_version=pipeline_version,
        )
        report["published"].append(
            {
                "topic_id": topic_id,
                "language": language,
                "video_url": video_url,
                "aliases": result["written"],
                "retired": result["retired"],
                "unusable_aliases": dropped,
            }
        )

    return report


async def main() -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    try:
        manifest = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        json.dump({"error": f"bad manifest json: {exc}"}, sys.stdout)
        return 2

    db.client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db.db = db.client[DATABASE_NAME]
    try:
        report = await publish(manifest)
    finally:
        db.client.close()

    json.dump(report, sys.stdout, ensure_ascii=False)
    return 0 if report["published"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
