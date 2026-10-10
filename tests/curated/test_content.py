"""The curated content tree, and the checks that guard it.

A curated video costs a person's viewing time to approve, so the expensive
failure is not a crash - it is a render that succeeds and ships wrong text.
Every check here exists to catch one of those before Manim is started:

- a caption key that exists in one language and not another
- a translation hardcoded into the shared animation
- an alias that can never match a typed question

The real content under content/curated/ is validated too, so adding a topic
with a typo fails the suite instead of failing at seeding time.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import curated  # noqa: E402

CONTENT_ROOT = REPO_ROOT / "content" / "curated"


# ---------------------------------------------------------------- fixtures --


def _write_topic(root: Path, *, scene: str, strings: dict, texts: dict,
                 languages=("kk", "ru"), aliases=None, review=None) -> curated.Topic:
    """A complete topic directory on disk, ready to load."""
    topic_dir = root / "physics" / "demo"
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "scene.py").write_text(scene, encoding="utf-8")

    for lang, values in strings.items():
        lines = [f'{k}: "{v}"' for k, v in values.items()]
        (topic_dir / f"strings.{lang}.yaml").write_text("\n".join(lines), encoding="utf-8")
    for lang, body in texts.items():
        (topic_dir / f"text.{lang}.md").write_text(body, encoding="utf-8")

    if aliases is None:
        aliases = {lang: [f"what is demo {lang}"] for lang in languages}
    if review is None:
        review = {"animation": {"approved": True}}
        review.update({lang: {"approved": True} for lang in languages})

    import yaml
    (topic_dir / "topic.yaml").write_text(
        yaml.safe_dump(
            {
                "topic_id": "physics.demo",
                "subject": "physics",
                "languages": list(languages),
                "aliases": aliases,
                "review": review,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return curated.load_topic(topic_dir)


SCENE = '''"""A demo animation."""

from manim import *

S = {}  # anyq:strings


class Demo(Scene):
    def construct(self):
        self.play(Write(Text(S["title"])))
        self.play(Write(Text(S["body"])))
'''


@pytest.fixture
def good_topic(tmp_path):
    return _write_topic(
        tmp_path,
        scene=SCENE,
        strings={"kk": {"title": "Тақырып", "body": "Мәтін"},
                 "ru": {"title": "Заголовок", "body": "Текст"}},
        texts={"kk": "Қазақша түсіндірме", "ru": "Русское объяснение"},
    )


# ------------------------------------------------------- the real content --


def test_every_shipped_topic_is_valid():
    """Content in the repo must always be safe to render."""
    topics = curated.discover_topics(CONTENT_ROOT)
    assert topics, "no curated topics found - the library would be empty"

    failures = {t.topic_id: curated.validate_topic(t) for t in topics}
    failures = {k: v for k, v in failures.items() if v}
    assert not failures, f"invalid curated content: {failures}"


def test_shipped_topics_declare_all_three_languages():
    """The product answers in kk, ru and en; a curated topic should too."""
    for topic in curated.discover_topics(CONTENT_ROOT):
        assert set(topic.languages) == {"kk", "ru", "en"}, topic.topic_id


# ------------------------------------------------------------ composition --


def test_composed_script_carries_the_chosen_language(good_topic):
    script = curated.compose_script(good_topic, "ru")

    assert "Заголовок" in script
    assert "Тақырып" not in script, "one language must not leak into another"
    assert script.count(curated.STRINGS_MARKER) == 1


def test_composition_leaves_the_animation_alone(good_topic):
    """Only the strings line changes, so tracebacks still match the file."""
    original = good_topic.scene_path.read_text(encoding="utf-8").splitlines()
    composed = curated.compose_script(good_topic, "kk").splitlines()

    assert len(composed) == len(original)
    differing = [i for i, (a, b) in enumerate(zip(original, composed, strict=True)) if a != b]
    assert len(differing) == 1
    assert curated.STRINGS_MARKER in composed[differing[0]]


def test_each_language_composes_to_a_different_script(good_topic):
    kk = curated.compose_script(good_topic, "kk")
    ru = curated.compose_script(good_topic, "ru")
    assert kk != ru


def test_a_script_without_the_marker_is_refused(tmp_path):
    topic = _write_topic(
        tmp_path,
        scene="from manim import *\n\n\nclass Demo(Scene):\n    def construct(self):\n        pass\n",
        strings={"kk": {}, "ru": {}},
        texts={"kk": "t", "ru": "t"},
    )
    with pytest.raises(ValueError, match="marker"):
        curated.compose_script(topic, "ru")


# -------------------------------------------------------------- validation --


def test_a_key_missing_from_one_language_is_reported(tmp_path):
    """The failure this layout exists to prevent."""
    topic = _write_topic(
        tmp_path,
        scene=SCENE,
        strings={"kk": {"title": "Тақырып", "body": "Мәтін"},
                 "ru": {"title": "Заголовок"}},  # body missing
        texts={"kk": "t", "ru": "t"},
    )
    problems = curated.validate_topic(topic)
    assert any("body" in p and "[ru]" in p for p in problems), problems


def test_a_leftover_key_is_reported(tmp_path):
    """A renamed key would otherwise leave the old text sitting in the file."""
    topic = _write_topic(
        tmp_path,
        scene=SCENE,
        strings={"kk": {"title": "Т", "body": "М", "old_caption": "ескі"},
                 "ru": {"title": "З", "body": "Т", "old_caption": "старый"}},
        texts={"kk": "t", "ru": "t"},
    )
    problems = curated.validate_topic(topic)
    assert any("old_caption" in p for p in problems), problems


def test_text_hardcoded_in_the_animation_is_reported(tmp_path):
    """A literal here would show up in all three languages at once."""
    topic = _write_topic(
        tmp_path,
        scene=SCENE.replace('Text(S["body"])', 'Text("Сила тяжести")'),
        strings={"kk": {"title": "Т"}, "ru": {"title": "З"}},
        texts={"kk": "t", "ru": "t"},
    )
    problems = curated.validate_topic(topic)
    assert any("Сила тяжести" in p for p in problems), problems


def test_an_ascii_literal_in_the_animation_is_allowed(tmp_path):
    """Colours and font names are not translatable content."""
    topic = _write_topic(
        tmp_path,
        scene=SCENE.replace("Text(S[\"body\"])", 'Text(S["body"], font="DejaVu Sans")'),
        strings={"kk": {"title": "Т", "body": "М"}, "ru": {"title": "З", "body": "Т"}},
        texts={"kk": "t", "ru": "t"},
    )
    assert curated.validate_topic(topic) == []


def test_a_language_without_aliases_is_reported(tmp_path):
    """Published but unreachable is the worst of both outcomes."""
    topic = _write_topic(
        tmp_path,
        scene=SCENE,
        strings={"kk": {"title": "Т", "body": "М"}, "ru": {"title": "З", "body": "Т"}},
        texts={"kk": "t", "ru": "t"},
        aliases={"kk": ["сұрақ"], "ru": []},
    )
    problems = curated.validate_topic(topic)
    assert any("[ru]" in p and "aliases" in p for p in problems), problems


def test_a_missing_scene_class_is_reported(tmp_path):
    topic = _write_topic(
        tmp_path,
        scene='from manim import *\n\nS = {}  # anyq:strings\n\n\nclass Demo:\n    pass\n',
        strings={"kk": {}, "ru": {}},
        texts={"kk": "t", "ru": "t"},
    )
    problems = curated.validate_topic(topic)
    assert any("Scene" in p for p in problems), problems


def test_an_empty_educator_text_is_reported(tmp_path):
    topic = _write_topic(
        tmp_path,
        scene=SCENE,
        strings={"kk": {"title": "Т", "body": "М"}, "ru": {"title": "З", "body": "Т"}},
        texts={"kk": "   \n", "ru": "ok"},
    )
    problems = curated.validate_topic(topic)
    assert any("text.kk.md" in p and "empty" in p for p in problems), problems


# ------------------------------------------------------------------ review --


def test_nothing_is_approved_without_an_explicit_record(tmp_path):
    topic = _write_topic(
        tmp_path, scene=SCENE,
        strings={"kk": {"title": "Т", "body": "М"}, "ru": {"title": "З", "body": "Т"}},
        texts={"kk": "t", "ru": "t"},
        review={"animation": {"approved": True}, "kk": {"approved": True},
                "ru": {"approved": False}},
    )
    assert topic.approved_languages() == ["kk"]


def test_an_unapproved_animation_blocks_every_language(tmp_path):
    """Captions sit on top of the motion; bad motion is bad in all of them."""
    topic = _write_topic(
        tmp_path, scene=SCENE,
        strings={"kk": {"title": "Т", "body": "М"}, "ru": {"title": "З", "body": "Т"}},
        texts={"kk": "t", "ru": "t"},
        review={"animation": {"approved": False}, "kk": {"approved": True},
                "ru": {"approved": True}},
    )
    assert topic.approved_languages() == []


def test_a_missing_review_slot_is_reported(tmp_path):
    topic = _write_topic(
        tmp_path, scene=SCENE,
        strings={"kk": {"title": "Т", "body": "М"}, "ru": {"title": "З", "body": "Т"}},
        texts={"kk": "t", "ru": "t"},
        review={"animation": {"approved": True}, "kk": {"approved": True}},
    )
    problems = curated.validate_topic(topic)
    assert any("'ru'" in p and "review" in p for p in problems), problems


# ------------------------------------------------------------------ keys ----


def test_keys_are_read_from_code_not_from_comments():
    source = 'from manim import *\n\nS = {}  # anyq:strings\n\n\nclass D(Scene):\n' \
             '    def construct(self):\n        # S["ghost"] was here\n' \
             '        """S["also_ghost"]"""\n        Text(S["real"])\n'
    assert curated.used_string_keys(source) == {"real"}
