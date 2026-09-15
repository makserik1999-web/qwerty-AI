"""The graph's own steps: intent, video decision, educator text, script, output.

Was one 645-line module. The steps themselves moved byte for byte - this split
is a change of address and nothing else - and this file keeps every name that
was importable from `anyq.nodes` importable from `anyq.nodes`, so graph.py,
assessments.py, science_manim_graph_agent.py and check.sh do not know it
happened.

The private names below are re-exported on purpose, not by accident: the
length-budget tests reach for them, and dropping them here to keep the surface
tidy would break the tests that hold that behaviour in place.

One thing this cannot preserve. A test that replaces a dependency has to
replace it in the module that LOOKS IT UP, and that module is now
`anyq.nodes.script` rather than `anyq.nodes` - `monkeypatch.setattr(nodes,
"_llm_chat", ...)` patches this namespace, which the step no longer reads.
tests/agent/test_length_budget.py patches `nodes.script` for that reason, and
every assertion in it is unchanged.
"""

from anyq.nodes.educator import educator_answer
from anyq.nodes.intent import (
    _heuristic_video_needed,
    classify_intent,
    decide_video_needed,
    reject_non_science,
    route_after_intent,
    route_after_video_needed,
)
from anyq.nodes.output import format_output
from anyq.nodes.script import (
    _LENGTH_REWRITE_ATTEMPTS,
    _ensure_spoken_lines_are_literal,
    _fit_narration_budget,
    _narration_chars,
    _one_length_rewrite,
    _resolve_video_length,
    generate_manim_script,
)
from anyq.nodes.state import USER_CONTENT_NOTICE, ScienceVideoState, _wrap

__all__ = [
    "USER_CONTENT_NOTICE",
    "ScienceVideoState",
    "_wrap",
    "classify_intent",
    "route_after_intent",
    "decide_video_needed",
    "route_after_video_needed",
    "reject_non_science",
    "educator_answer",
    "generate_manim_script",
    "format_output",
    # Reached for by tests rather than by the graph.
    "_LENGTH_REWRITE_ATTEMPTS",
    "_ensure_spoken_lines_are_literal",
    "_fit_narration_budget",
    "_heuristic_video_needed",
    "_narration_chars",
    "_one_length_rewrite",
    "_resolve_video_length",
]
