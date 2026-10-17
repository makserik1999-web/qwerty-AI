"""A portrait video is laid out for a narrow, tall frame - and a box always
fits what is written in it, whichever way up the video is."""

import pytest


@pytest.fixture
def prompts(agent_import_path):
    import anyq.prompts as module

    return module


def test_portrait_swaps_only_the_frame_rules(prompts):
    wide = prompts.build_manim_system_prompt(True, "Kazakh")
    tall = prompts.build_manim_system_prompt(True, "Kazakh", portrait=True)
    assert "x in [-7, 7]" in wide and "PORTRAIT" not in wide
    assert "PORTRAIT (9:16" in tall and "x in [-4, 4]" in tall and "x in [-7, 7]" not in tall
    # Everything outside L6/L7 is the same prompt.
    cut = lambda p: p[: p.index("L6.")] + p[p.index("L8.") :]  # noqa: E731
    assert cut(wide) == cut(tall)


def test_both_say_a_box_fits_its_text(prompts):
    for portrait in (False, True):
        text = prompts.build_manim_system_prompt(True, "Russian", portrait=portrait)
        assert "SurroundingRectangle(label" in text and "L9." in text
