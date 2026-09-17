#!/usr/bin/env python3
"""Render and publish the curated library.

    python scripts/seed_library.py --check      # validate content, render nothing
    python scripts/seed_library.py --preview    # render every language, publish nothing
    python scripts/seed_library.py              # render + publish approved languages
    python scripts/seed_library.py --list       # what is published right now

Runs on the host and drives the two containers, because that is where the
three pieces live: the content tree is here, Manim is in the agent, and the
database is in the backend. Nothing here parses YAML inside a container, so
no production image grows a dependency for a tool only an operator runs.

Two rules the workflow is built around:

- Nothing is published until a person has approved it in topic.yaml. --preview
  exists because you cannot approve a video you have not watched, and the
  video does not exist until something renders it.
- A language is published as soon as it is approved, without waiting for the
  others. Kazakh and Russian can be live while English is still being read.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import curated  # noqa: E402

CONTENT_ROOT = REPO_ROOT / "content" / "curated"


class ContainerError(RuntimeError):
    pass


def _compose(service: str, args: List[str], stdin_text: str = "", timeout: int = 1800) -> str:
    """Run a command in a compose service, speaking UTF-8 in both directions.

    Bytes rather than text mode on purpose: the default console encoding on
    Windows is not UTF-8, and letting it near Kazakh captions corrupts them
    silently rather than failing.
    """
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", service, *args],
        input=stdin_text.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
        timeout=timeout,
    )
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 and not out:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ContainerError(f"{service}: {err[-500:] or f'exit {proc.returncode}'}")
    return out


def _json_from(service: str, args: List[str], stdin_text: str = "") -> Dict[str, Any]:
    raw = _compose(service, args, stdin_text)
    # Manim is chatty; the JSON object is the last line of stdout.
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise ContainerError(f"{service}: no JSON in output: {raw[-500:]}")


def render(topic: curated.Topic, language: str, quality: str) -> Dict[str, Any]:
    script = curated.compose_script(topic, language)
    request = json.dumps({"script": script, "quality": quality}, ensure_ascii=False)
    return _json_from("agent", ["python", "/app/scripts/render_curated.py"], request)


def published_state() -> Dict[str, Dict[str, Any]]:
    out = _compose(
        "backend",
        ["python", "-c",
         "import asyncio,json,sys;sys.path.insert(0,'/app');"
         "from motor.motor_asyncio import AsyncIOMotorClient;"
         "from app.config import MONGO_URL,DATABASE_NAME;from app.db import db;"
         "from app.repositories.library import curated_topics;"
         "db.client=AsyncIOMotorClient(MONGO_URL);db.db=db.client[DATABASE_NAME];"
         "print(json.dumps(asyncio.run(curated_topics()),ensure_ascii=False))"],
    )
    for line in reversed(out.splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line)
    return {}


def video_exists(video_url: str) -> bool:
    name = (video_url or "").rsplit("/", 1)[-1]
    if not name:
        return False
    out = _compose(
        "backend", ["sh", "-c", f'test -f "/app/media/outputs/{name}" && echo yes || echo no']
    )
    return out.strip().endswith("yes")


def report_problems(topics: List[curated.Topic]) -> int:
    total = 0
    for topic in topics:
        problems = curated.validate_topic(topic)
        total += len(problems)
        head = f"{topic.topic_id} ({topic.path.relative_to(REPO_ROOT)})"
        if problems:
            print(f"\n  {head}")
            for problem in problems:
                print(f"      {problem}")
        else:
            approved = topic.approved_languages()
            state = ", ".join(approved) if approved else "nothing approved yet"
            print(f"  ok  {head}  [{state}]")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate content and stop")
    parser.add_argument("--preview", action="store_true",
                        help="render every declared language and publish nothing")
    parser.add_argument("--list", action="store_true", help="show what is published")
    parser.add_argument("--topic", default="", help="limit to one topic_id")
    parser.add_argument("--quality", default="h", choices=["l", "m", "h"],
                        help="render quality (default h: 1080p60)")
    parser.add_argument("--rerender", action="store_true",
                        help="render again even when a published video still exists")
    args = parser.parse_args()

    if args.list:
        state = published_state()
        if not state:
            print("nothing published")
            return 0
        for slot in sorted(state):
            row = state[slot]
            print(f"  {slot:44} {row['aliases']:>3} aliases  {row['hits']:>5} hits  "
                  f"{row['video_url']}")
        return 0

    topics = curated.discover_topics(CONTENT_ROOT)
    if args.topic:
        topics = [t for t in topics if t.topic_id == args.topic]
        if not topics:
            print(f"no topic with id {args.topic!r} under {CONTENT_ROOT}")
            return 2
    if not topics:
        print(f"no topics under {CONTENT_ROOT}")
        return 0

    print(f"checking {len(topics)} topic(s):")
    problems = report_problems(topics)
    if problems:
        print(f"\n{problems} problem(s) found - nothing was rendered.")
        return 1
    if args.check:
        return 0

    # --preview renders what nobody has approved yet, precisely so it can be
    # approved; the normal run only touches what already was.
    published = {} if args.preview else published_state()
    manifest: Dict[str, Any] = {"entries": []}
    rendered, reused, failed = 0, 0, 0

    for topic in topics:
        languages = topic.languages if args.preview else topic.approved_languages()
        if not languages:
            print(f"\n{topic.topic_id}: no approved language, skipping "
                  f"(run --preview to render it for review)")
            continue

        print(f"\n{topic.topic_id}: {', '.join(languages)}")
        for language in languages:
            existing = published.get(f"{topic.topic_id}/{language}", {})
            video_url = existing.get("video_url", "")

            if video_url and not args.rerender and video_exists(video_url):
                # The animation is frozen in git, so a published video only
                # needs re-rendering when the scene changed - not when the
                # pipeline version did. Re-registering is enough for that.
                print(f"  {language}: reusing {video_url} (--rerender to force)")
                reused += 1
            else:
                print(f"  {language}: rendering at -q{args.quality} ...", flush=True)
                try:
                    result = render(topic, language, args.quality)
                except ContainerError as exc:
                    print(f"  {language}: FAILED - {exc}")
                    failed += 1
                    continue
                if not result.get("success"):
                    print(f"  {language}: FAILED - {result.get('error', '')[-400:]}")
                    failed += 1
                    continue
                video_url = result["video_url"]
                print(f"  {language}: rendered {video_url}")
                rendered += 1

            manifest["entries"].append({
                "topic_id": topic.topic_id,
                "language": language,
                "aliases": topic.aliases.get(language, []),
                "educator_text": curated.load_text(topic, language),
                "video_url": video_url,
            })

    print(f"\nrendered {rendered}, reused {reused}, failed {failed}")

    if args.preview:
        print("\npreview only - nothing was published. Watch these, then set")
        print("approved: true in topic.yaml and run seed_library.py again:")
        for entry in manifest["entries"]:
            print(f"  [{entry['language']}] http://localhost:3000{entry['video_url']}")
        return 1 if failed else 0

    if not manifest["entries"]:
        print("nothing to publish")
        return 1 if failed else 0

    report = _json_from(
        "backend", ["python", "scripts/register_curated.py"],
        json.dumps(manifest, ensure_ascii=False),
    )
    print(f"\npublished under pipeline_version={report.get('pipeline_version')}:")
    for row in report.get("published", []):
        note = f", retired {row['retired']}" if row["retired"] else ""
        print(f"  {row['topic_id']} [{row['language']}] {row['aliases']} aliases{note}")
        for alias in row.get("unusable_aliases", []):
            print(f"      dropped unmatchable alias: {alias!r}")
    for row in report.get("skipped", []):
        print(f"  SKIPPED {row['topic_id']} [{row['language']}]: {row['reason']}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
