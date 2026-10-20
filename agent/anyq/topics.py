"""The fixed list of school topics, and how a question is matched to one.

A question is filed under a topic only by picking an id from topics.json -
never by embedding similarity. "The Pythagorean theorem" and "the converse of
the Pythagorean theorem" are almost the same vector and two different lessons;
a fixed list keeps them apart and makes every match something a person can
read and check.
"""

import json
import os
from functools import lru_cache
from typing import Any, Dict, List

PATH = os.path.join(os.path.dirname(__file__), "topics.json")


@lru_cache(maxsize=1)
def topics() -> List[Dict[str, Any]]:
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)["topics"]


@lru_cache(maxsize=1)
def by_id() -> Dict[str, Dict[str, Any]]:
    return {t["id"]: t for t in topics()}


@lru_cache(maxsize=1)
def prompt_list() -> str:
    """The list as the classifier sees it: one line per topic, grouped by subject."""
    lines: List[str] = []
    current = ""
    for t in topics():
        if t["subject"] != current:
            current = t["subject"]
            lines.append(f"# {current}")
        lines.append(f"{t['id']} | {t['ru']} | {t['kk']}")
    return "\n".join(lines)
