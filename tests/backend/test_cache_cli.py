"""`python -m app.cache_cli forget "<question>"`: every stored answer to it goes."""

import asyncio
import io


def run_db(coro):
    return asyncio.run(coro)


def test_forget_drops_every_variant_of_the_question(backend):
    from app import cache_cli
    from app.services import cache_service

    question = "Пифагор теоремасы қалай дәлелденеді?"
    normalized, _ = cache_service.key_for(question)
    for variant in ("voice=aigul", "silent", "voice=daulet,len=short"):
        run_db(backend.db.db.library_entries.insert_one(
            {"cache_key": f"cli-{variant}", "normalized_question": normalized, "variant": variant}))
    run_db(backend.db.db.library_entries.insert_one(
        {"cache_key": "cli-other", "normalized_question": "басқа сұрақ"}))

    out = io.StringIO()
    # Asked with other case and spacing: matched the way the cache matches.
    assert run_db(cache_cli.run(["forget", "  ПИФАГОР теоремасы  қалай дәлелденеді "], out=out)) == 0
    assert "3" in out.getvalue()
    assert run_db(backend.db.db.library_entries.count_documents({"normalized_question": normalized})) == 0
    assert run_db(backend.db.db.library_entries.count_documents({"cache_key": "cli-other"})) == 1
    run_db(backend.db.db.library_entries.delete_many({"cache_key": "cli-other"}))


def test_nothing_to_forget_says_so(backend):
    from app import cache_cli

    out = io.StringIO()
    assert run_db(cache_cli.run(["forget", "мұндай сұрақ жоқ"], out=out)) == 0
    assert "нет" in out.getvalue()
