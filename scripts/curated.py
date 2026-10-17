"""Reading and checking the curated content tree.

Curated topics are the videos a person has watched and approved, so the cost
of a mistake here is not a wasted render - it is a wrong caption sitting in
the library until someone notices. Everything that can be checked without
rendering is checked here, before Manim is ever started:

- the strings files agree with each other and with the keys scene.py uses
- scene.py carries no literal text of its own, so nothing bypasses translation
- the animation and each language have an explicit review record

This module is deliberately import-only: it reads files and returns findings,
it never renders, writes or touches the database. That is what makes it
testable without Docker, and it is where the tests live.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

# The line in scene.py that seed_library.py rewrites with the chosen language.
STRINGS_MARKER = "# anyq:strings"

# Languages the product speaks. A topic may declare a subset.
KNOWN_LANGUAGES = ("kk", "ru", "en")

_SCENE_CLASS_RE = re.compile(
    r"class\s+(\w+)\s*\(\s*(?:Scene|ThreeDScene|MovingCameraScene|ZoomedScene)\s*\)"
)


@dataclass
class Topic:
    """One directory under content/curated/<subject>/<name>/."""

    topic_id: str
    subject: str
    path: Path
    languages: List[str]
    aliases: Dict[str, List[str]]
    review: Dict[str, Dict[str, Any]]
    grade_range: List[int] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    # ---- files -------------------------------------------------------------

    @property
    def scene_path(self) -> Path:
        return self.path / str(self.raw.get("manim_script", "scene.py"))

    def strings_path(self, language: str) -> Path:
        pattern = str(self.raw.get("strings", "strings.{lang}.yaml"))
        return self.path / pattern.replace("{lang}", language)

    def text_path(self, language: str) -> Path:
        pattern = str(self.raw.get("educator_text", "text.{lang}.md"))
        return self.path / pattern.replace("{lang}", language)

    # ---- review ------------------------------------------------------------

    def animation_approved(self) -> bool:
        return bool(self.review.get("animation", {}).get("approved"))

    def language_approved(self, language: str) -> bool:
        """A language is publishable only if the motion was approved too.

        The captions are reviewed per language, but they sit on top of one
        shared animation - an unapproved animation is unapproved in every
        language, however good the wording is.
        """
        if not self.animation_approved():
            return False
        return bool(self.review.get(language, {}).get("approved"))

    def approved_languages(self) -> List[str]:
        return [lang for lang in self.languages if self.language_approved(lang)]


def load_strings(topic: Topic, language: str) -> Dict[str, str]:
    data = yaml.safe_load(topic.strings_path(language).read_text(encoding="utf-8"))
    return data or {}


def load_text(topic: Topic, language: str) -> str:
    return topic.text_path(language).read_text(encoding="utf-8").strip()


def used_string_keys(scene_source: str) -> Set[str]:
    """Every S["..."] the animation reads.

    Parsed rather than grepped, so a key inside a comment or a docstring is
    not mistaken for one the animation actually needs.
    """
    try:
        tree = ast.parse(scene_source)
    except SyntaxError:
        return set()

    keys: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        if not (isinstance(node.value, ast.Name) and node.value.id == "S"):
            continue
        index = node.slice
        if isinstance(index, ast.Constant) and isinstance(index.value, str):
            keys.add(index.value)
    return keys


def _non_ascii_literals(scene_source: str) -> List[str]:
    """String literals in scene.py that contain non-ASCII text.

    A Cyrillic literal here would be shown in all three languages at once,
    which is the one failure this layout exists to prevent. The module
    docstring is skipped: prose about the file is not content.
    """
    try:
        tree = ast.parse(scene_source)
    except SyntaxError:
        return []

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docstrings:
                continue
            if not node.value.isascii():
                found.append(node.value)
    return found


def compose_script(topic: Topic, language: str) -> str:
    """scene.py with S bound to one language's strings.

    The marker line is replaced rather than appended to, so the composed
    script has exactly one definition of S and the line numbers in a Manim
    traceback still line up with the file on disk.
    """
    source = topic.scene_path.read_text(encoding="utf-8")
    strings = load_strings(topic, language)

    marker_lines = [i for i, line in enumerate(source.splitlines()) if STRINGS_MARKER in line]
    if len(marker_lines) != 1:
        raise ValueError(
            f"{topic.scene_path} must contain the {STRINGS_MARKER!r} marker exactly "
            f"once, found {len(marker_lines)}"
        )

    # json.dumps produces a literal that is valid Python for str->str data,
    # and keeps the non-ASCII readable in a traceback. Kept on ONE line: an
    # indented dict would push every following line down, and then a Manim
    # traceback would point at the wrong line of scene.py.
    literal = json.dumps(strings, ensure_ascii=False, sort_keys=True)
    lines = source.splitlines()
    lines[marker_lines[0]] = f"S = {literal}  {STRINGS_MARKER}"
    return "\n".join(lines) + "\n"


def scene_class_name(scene_source: str) -> Optional[str]:
    match = _SCENE_CLASS_RE.search(scene_source)
    return match.group(1) if match else None


def validate_topic(topic: Topic) -> List[str]:
    """Everything wrong with this topic, in the order it would bite.

    Returns an empty list for a topic that is safe to render.
    """
    problems: List[str] = []

    if not topic.topic_id:
        problems.append("topic_id is missing")
    if not topic.subject:
        problems.append("subject is missing")
    if not topic.languages:
        problems.append("languages is empty - nothing to render")

    for lang in topic.languages:
        if lang not in KNOWN_LANGUAGES:
            problems.append(f"unknown language {lang!r} (known: {', '.join(KNOWN_LANGUAGES)})")

    if not topic.scene_path.is_file():
        problems.append(f"missing animation script {topic.scene_path.name}")
        return problems

    source = topic.scene_path.read_text(encoding="utf-8")

    if not scene_class_name(source):
        problems.append(f"{topic.scene_path.name} has no Scene subclass, so nothing can render")

    marker_count = sum(1 for line in source.splitlines() if STRINGS_MARKER in line)
    if marker_count != 1:
        problems.append(
            f"{topic.scene_path.name} must contain {STRINGS_MARKER!r} exactly once "
            f"(found {marker_count})"
        )

    for literal in _non_ascii_literals(source):
        preview = literal if len(literal) <= 40 else literal[:37] + "..."
        problems.append(
            f"{topic.scene_path.name} contains the literal text {preview!r} - move it "
            f"into strings.<lang>.yaml, otherwise every language shows it"
        )

    needed = used_string_keys(source)
    per_language: Dict[str, Set[str]] = {}

    for lang in topic.languages:
        strings_file = topic.strings_path(lang)
        text_file = topic.text_path(lang)

        if not strings_file.is_file():
            problems.append(f"[{lang}] missing {strings_file.name}")
            continue
        if not text_file.is_file():
            problems.append(f"[{lang}] missing {text_file.name}")

        try:
            strings = load_strings(topic, lang)
        except yaml.YAMLError as exc:
            problems.append(f"[{lang}] {strings_file.name} is not valid YAML: {exc}")
            continue

        non_str = sorted(k for k, v in strings.items() if not isinstance(v, str))
        if non_str:
            problems.append(
                f"[{lang}] these values are not text: {', '.join(non_str)}"
            )

        per_language[lang] = set(strings)

        missing = sorted(needed - set(strings))
        if missing:
            problems.append(
                f"[{lang}] {strings_file.name} is missing keys the animation reads: "
                f"{', '.join(missing)}"
            )
        unused = sorted(set(strings) - needed)
        if unused:
            problems.append(
                f"[{lang}] {strings_file.name} defines keys the animation never reads: "
                f"{', '.join(unused)} - a renamed key leaves the old text behind"
            )

        if text_file.is_file() and not text_file.read_text(encoding="utf-8").strip():
            problems.append(f"[{lang}] {text_file.name} is empty")

        if not topic.aliases.get(lang):
            problems.append(
                f"[{lang}] no aliases - the video would be published but unreachable"
            )

    # Key sets must agree, or one language silently renders a different video.
    if len(per_language) > 1:
        reference_lang = topic.languages[0]
        reference = per_language.get(reference_lang, set())
        for lang, keys in per_language.items():
            if lang == reference_lang:
                continue
            if keys != reference:
                only_here = sorted(keys - reference)
                only_there = sorted(reference - keys)
                detail = []
                if only_here:
                    detail.append(f"extra: {', '.join(only_here)}")
                if only_there:
                    detail.append(f"absent: {', '.join(only_there)}")
                problems.append(
                    f"[{lang}] key set differs from [{reference_lang}] ({'; '.join(detail)})"
                )

    for slot in ["animation", *topic.languages]:
        if slot not in topic.review:
            problems.append(
                f"review has no entry for {slot!r} - nothing is published without one"
            )

    return problems


def load_topic(topic_dir: Path) -> Topic:
    raw = yaml.safe_load((topic_dir / "topic.yaml").read_text(encoding="utf-8")) or {}
    aliases = raw.get("aliases") or {}
    return Topic(
        topic_id=str(raw.get("topic_id", "")),
        subject=str(raw.get("subject", "")),
        path=topic_dir,
        languages=list(raw.get("languages") or []),
        aliases={k: list(v or []) for k, v in aliases.items()},
        review=dict(raw.get("review") or {}),
        grade_range=list(raw.get("grade_range") or []),
        raw=raw,
    )


def discover_topics(root: Path) -> List[Topic]:
    """Every topic under content/curated/, sorted for a stable seeding order."""
    if not root.is_dir():
        return []
    topics = [load_topic(p.parent) for p in sorted(root.glob("*/*/topic.yaml"))]
    return sorted(topics, key=lambda t: t.topic_id)
