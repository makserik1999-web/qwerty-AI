"""Take a stored answer out of the cache. Runs on the server.

    docker compose exec backend python -m app.cache_cli forget "Пифагор теоремасы қалай дәлелденеді?"

Every stored answer to that question goes - every voice, length and quality
it was asked with - so the next person who asks gets a fresh video. For a bad
answer that the library tab cannot reach: a video deleted from the library is
also cleared from here, but only from the moment that rule existed.

The question is matched the way the cache matches it: case, spacing and
punctuation do not matter.
"""

import argparse
import asyncio
import sys
from typing import List

from app.cache.normalize import normalize_question
from app.config import DATABASE_NAME, MONGO_URL
from app.db import db


async def run(argv: List[str], out=None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="python -m app.cache_cli", description="Кэш ответов Akron")
    sub = parser.add_subparsers(dest="command", required=True)
    forget = sub.add_parser("forget", help="убрать из кэша ответы на этот вопрос")
    forget.add_argument("question")
    args = parser.parse_args(argv)

    normalized = normalize_question(args.question)
    if not normalized:
        print("Пустой вопрос.", file=out)
        return 1
    result = await db.db.library_entries.delete_many({"normalized_question": normalized})
    print(f"Убрано ответов: {result.deleted_count}.", file=out)
    if not result.deleted_count:
        print("Такого вопроса в кэше нет - проверьте формулировку.", file=out)
    return 0


async def _main(argv: List[str]) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    db.client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db.db = db.client[DATABASE_NAME]
    try:
        return await run(argv)
    finally:
        db.client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
