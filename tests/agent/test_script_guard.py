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


class TestSafeJsonLoads:
    """Reading JSON out of a model reply.

    Every caller reads the result with .get(), so a parse failure does not
    raise - it degrades. When gemini-3.7-flash started wrapping its JSON in a
    ```json fence, classify_intent stopped finding "is_science" and rejected
    every question as non-scientific, with no error anywhere.
    """

    def test_plain_json(self, safe_json_loads):
        assert safe_json_loads('{"is_science": true}') == {"is_science": True}

    def test_json_wrapped_in_a_fence(self, safe_json_loads):
        text = '```json\n{"is_science": true, "subject": "Physics"}\n```'
        assert safe_json_loads(text)["is_science"] is True

    def test_json_in_an_unlabelled_fence(self, safe_json_loads):
        assert safe_json_loads('```\n{"a": 1}\n```') == {"a": 1}

    def test_json_after_a_sentence(self, safe_json_loads):
        assert safe_json_loads('Here is the result:\n{"a": 1}') == {"a": 1}

    def test_nested_objects_survive(self, safe_json_loads):
        assert safe_json_loads('```json\n{"a": {"b": 1}}\n```') == {"a": {"b": 1}}

    def test_a_reply_with_no_json_is_empty(self, safe_json_loads):
        assert safe_json_loads("no json here") == {}

    def test_a_json_list_is_not_a_dict(self, safe_json_loads):
        """Callers index by key; a list would raise instead of degrading."""
        assert safe_json_loads("[1, 2, 3]") == {}

    def test_empty_input(self, safe_json_loads):
        assert safe_json_loads("") == {}
