"""The AST safety validator: what it must accept and what it must never run.

Converted from `logs/local_check.py`. These cases are the security boundary
between an LLM-generated script and the render sandbox, so each rejection gets
its own test and its own name in the report.
"""

import pytest

GOOD_SCRIPT = """
from manim import *
Text.set_default(font="DejaVu Sans")
class Demo(Scene):
    def construct(self):
        t = Text("Hello")
        self.play(Write(t))
        self.wait(1)
"""

REJECTED_SCRIPTS = {
    "import_os": "import os\nclass X(Scene):\n    def construct(self):\n        pass\n",
    "from_subprocess": (
        "from subprocess import run\nclass X(Scene):\n    def construct(self):\n        pass\n"
    ),
    "eval_call": (
        "from manim import *\nclass X(Scene):\n    def construct(self):\n        eval('1+1')\n"
    ),
    "module_level_print": (
        "from manim import *\nprint('hi')\nclass X(Scene):\n    def construct(self):\n        pass\n"
    ),
    "open_call": (
        "from manim import *\nclass X(Scene):\n"
        "    def construct(self):\n        f = open('/etc/passwd')\n"
    ),
    "socket_import": (
        "from manim import *\nimport socket\nclass X(Scene):\n    def construct(self):\n        pass\n"
    ),
    "dunder_attribute_access": (
        "from manim import *\nclass X(Scene):\n    def construct(self):\n"
        "        x = 'a'\n        y = getattr(x, '__class__')\n"
    ),
    "requests_import": (
        "from manim import *\nimport requests\nclass X(Scene):\n"
        "    def construct(self):\n        pass\n"
    ),
}


def test_a_legitimate_manim_script_is_accepted(validate_manim_script):
    ok, reason = validate_manim_script(GOOD_SCRIPT)
    assert ok, f"a valid script was rejected: {reason}"


@pytest.mark.parametrize("name", sorted(REJECTED_SCRIPTS))
def test_dangerous_script_is_rejected(validate_manim_script, name):
    ok, reason = validate_manim_script(REJECTED_SCRIPTS[name])
    assert not ok, f"{name} should never be accepted"
    assert reason, "a rejection must explain itself"
