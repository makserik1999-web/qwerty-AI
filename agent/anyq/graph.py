"""Graph wiring: the nodes and edges, and the compiled app.

Sequence: vision -> intent -> video_needed -> (reject | video path).
The video path is strictly sequential: educator_video -> manim_script ->
render -> output, so generate_manim_script sees the educator explanation the
pipeline just produced (and educator_answer runs exactly once per request).
"""

from spoon_ai.graph import END, StateGraph

from anyq import progress
from anyq.nodes import (
    ScienceVideoState,
    classify_intent,
    decide_video_needed,
    educator_answer,
    format_output,
    generate_manim_script,
    reject_non_science,
    route_after_intent,
    route_after_video_needed,
)
from anyq.render import render_video
from anyq.vision import analyze_image_with_gemini


def _staged(stage: str, node):
    """Report a stage on the way into a node, then run it unchanged.

    Wrapped here rather than inside the nodes so that the nodes stay pure
    functions of their state and know nothing about a socket. Only the three
    transitions the interface shows are wrapped; the rest are too fast to be
    worth a frame.
    """

    async def run(state):
        await progress.report(stage)
        return await node(state)

    run.__name__ = getattr(node, "__name__", stage)
    return run


def build_app():
    graph = StateGraph(ScienceVideoState)
    graph.add_node("vision", analyze_image_with_gemini)
    graph.add_node("intent", _staged("understand", classify_intent))
    graph.add_node("video_needed", decide_video_needed)
    graph.add_node("reject", reject_non_science)
    graph.add_node("educator_text", educator_answer)
    graph.add_node("educator_video", _staged("write", educator_answer))
    graph.add_node("manim_script", _staged("render", generate_manim_script))
    graph.add_node("render", render_video)
    graph.add_node("output", format_output)

    graph.set_entry_point("vision")
    graph.add_edge("vision", "intent")
    graph.add_conditional_edges(
        "intent",
        route_after_intent,
        {"reject": "reject", "science": "video_needed"},
    )
    graph.add_edge("reject", END)

    graph.add_conditional_edges(
        "video_needed",
        route_after_video_needed,
        {"no_video": "educator_text", "video": "educator_video"},
    )

    graph.add_edge("educator_text", "output")
    graph.add_edge("educator_video", "manim_script")
    graph.add_edge("manim_script", "render")
    graph.add_edge("render", "output")
    graph.add_edge("output", END)

    return graph.compile()


app = build_app()


async def run_once(user_message: str) -> ScienceVideoState:
    return await app.invoke({"user_message": user_message})