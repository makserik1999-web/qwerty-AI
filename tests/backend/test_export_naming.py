"""Naming a downloaded file after the question it answers.

Two things are being protected. A file called `video_a3f19c.mp4` is lost the
moment it reaches a downloads folder, so the question has to survive into the
name. And a filename reaches an HTTP header, where a newline is not a typo but
header injection - so what gets in there is checked, not trusted.
"""

import pytest


@pytest.fixture
def naming(backend):
    from app.services import export_naming

    return export_naming


# --------------------------------------------------------- transliteration --


def test_kazakh_letters_survive_transliteration(naming):
    """The letters Russian tables do not have, which is the whole point."""
    assert naming.transliterate("әғқңөұүһі") == "agqnouuhi"


def test_russian_is_transliterated(naming):
    assert naming.transliterate("Что такое гравитация") == "Chto takoe gravitatsiya"


def test_latin_text_is_left_alone(naming):
    assert naming.transliterate("What is gravity") == "What is gravity"


def test_case_is_preserved(naming):
    assert naming.transliterate("Жер") == "Zher"


# ---------------------------------------------------------------- filenames --


def test_the_question_becomes_the_filename(naming):
    assert naming.download_filename("Что такое гравитация?", ".mp4") == \
        "Что-такое-гравитация.mp4"


def test_a_path_separator_cannot_survive(naming):
    """Otherwise a name would become a path."""
    name = naming.download_filename("../../etc/passwd", ".mp4")
    assert "/" not in name and "\\" not in name and ".." not in name


def test_an_empty_title_falls_back(naming):
    assert naming.download_filename("", ".gif") == "anyq-export.gif"
    assert naming.download_filename("???", ".gif") == "anyq-export.gif"


def test_a_long_title_is_trimmed(naming):
    name = naming.download_filename("а" * 300, ".mp4")
    assert len(name) <= naming.MAX_STEM + len(".mp4")


def test_the_ascii_name_carries_the_meaning(naming):
    """A client that ignores filename* still gets something readable."""
    # Spaces become dashes here, the same as in download_filename: by the time
    # a name reaches a header it should not need quoting to survive.
    assert naming.ascii_filename("Гравитация деген не.mp4") == \
        "Gravitatsiya-degen-ne.mp4"


def test_an_all_cyrillic_name_never_becomes_empty_ascii(naming):
    assert naming.ascii_filename("Жер.mp4").startswith("Zher")


# ------------------------------------------------------- header safety ------


@pytest.mark.parametrize(
    "hostile",
    [
        'x"; drop=1; filename="evil.exe',
        "line\r\nX-Injected: yes",
        "null\x00byte",
        "tab\tseparated",
    ],
)
def test_a_hostile_title_cannot_break_the_header(naming, hostile):
    header = naming.content_disposition(naming.download_filename(hostile, ".mp4"))

    assert "\r" not in header and "\n" not in header and "\x00" not in header
    # Exactly one quoted filename: a smuggled quote would create a second.
    assert header.count('"') == 2


def test_the_header_carries_both_spellings(naming):
    header = naming.content_disposition("Гравитация.mp4")

    assert header.startswith("attachment; ")
    assert 'filename="Gravitatsiya.mp4"' in header
    assert "filename*=UTF-8''" in header
    # The unicode half is percent-encoded, not raw.
    assert "%D0%93" in header
