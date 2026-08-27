"""The graph's own steps: intent, video decision, educator text, script, output.

Moved verbatim out of science_manim_graph_agent.py, together with the
ScienceVideoState TypedDict the steps are typed against.
"""

import re
from typing import Any, Dict, List, Optional, TypedDict

from spoon_ai.schema import Message

from anyq.config import DOC_SNIPPET_MODE
from anyq.language import (
    _REJECT_MESSAGES,
    _RENDER_FALLBACK_MESSAGES,
    _language_name,
    _resolve_output_language,
)
from anyq.llm_client import _llm_chat
from anyq.prompts import (
    REWRITE_CYRILLIC_IN_TEX_SYSTEM_PROMPT,
    REWRITE_FORBIDDEN_HELPERS_SYSTEM_PROMPT,
    REWRITE_WITHOUT_LATEX_SYSTEM_PROMPT,
    build_manim_system_prompt,
)
from anyq.script_guard import (
    _contains_forbidden_manim,
    _contains_latex_objects,
    _ensure_unicode_font,
    _latex_toolchain_healthy,
    _safe_json_loads,
    _strip_code_fences,
    _tex_contains_cyrillic,
)


class ScienceVideoState(TypedDict, total=False):
    # input
    user_message: str
    image_path: str
    image_paths: List[str]
    image_context: str
    image_analysis_json: str
    image_analysis_jsons: List[str]

    # language
    output_language: str

    # intent
    is_science: bool
    subject: str
    intent_reason: str
    video_needed: bool
    video_reason: str

    # educator
    educator_text: str

    # manim
    manim_script: str
    video_path: str
    mcp_raw_result: str
    render_error: str
    render_attempt: int

    # output
    final_text: str
    final_video_path: str


async def classify_intent(state: ScienceVideoState) -> Dict[str, Any]:
    q = (state.get("user_message") or "").strip()
    if not q:
        raise ValueError("user_message is required")
    img_ctx = (state.get("image_context") or "").strip()

    if DOC_SNIPPET_MODE == "1":
        return {"is_science": True, "subject": "physics", "intent_reason": "(stub)"}

    resp = await _llm_chat(
        [
            Message(
                role="system",
                content=(
                    "Classify if the user request is scientific/educational.\n"
                    "Return ONLY valid JSON with keys:\n"
                    '- "is_science": boolean\n'
                    '- "subject": string\n'
                    '- "reason": string\n'
                ),
            ),
            Message(role="user", content=(q + ("\n\nImage context:\n" + img_ctx if img_ctx else ""))),
        ]
    )
    payload = _safe_json_loads(resp.content)
    return {
        "is_science": bool(payload.get("is_science")),
        "subject": str(payload.get("subject") or "other"),
        "intent_reason": str(payload.get("reason") or ""),
    }


def route_after_intent(state: ScienceVideoState) -> str:
    return "science" if state.get("is_science") else "reject"


_SIMPLE_ARITH_RE = re.compile(r"^\s*-?\d+(\s*[+\-*/]\s*-?\d+)+\s*\??\s*$")


def _heuristic_video_needed(query: str) -> Optional[Dict[str, Any]]:
    """
    Always return True for video generation for science questions.
    Only skip video for empty queries.
    """
    q = (query or "").strip()
    if not q:
        return {"video_needed": False, "video_reason": "empty query"}

    # ALWAYS generate videos for science questions - no exceptions
    return {"video_needed": True, "video_reason": "science question - always generate video"}


async def decide_video_needed(state: ScienceVideoState) -> Dict[str, Any]:
    """
    Decide if video is needed. For science questions, ALWAYS generate video.
    """
    q = (state.get("user_message") or "").strip()
    
    if not state.get("is_science"):
        return {"video_needed": False, "video_reason": "non-science"}

    # For science questions, ALWAYS generate videos
    heuristic = _heuristic_video_needed(q)
    if heuristic is not None:
        return heuristic

    # Fallback: always generate video for science
    return {"video_needed": True, "video_reason": "science question - always generate video"}


def route_after_video_needed(state: ScienceVideoState) -> str:
    return "video" if state.get("video_needed") else "no_video"


async def reject_non_science(state: ScienceVideoState) -> Dict[str, Any]:
    language = _resolve_output_language(state)
    msg = _REJECT_MESSAGES.get(language, _REJECT_MESSAGES["kk"])
    return {"final_text": msg, "final_video_path": "", "output_language": language}


async def educator_answer(state: ScienceVideoState) -> Dict[str, Any]:
    q = (state.get("user_message") or "").strip()
    subject = (state.get("subject") or "science").strip()
    img_ctx = (state.get("image_context") or "").strip()

    if DOC_SNIPPET_MODE == "1":
        return {"educator_text": f"(stub educator explanation for {subject})"}

    language = _resolve_output_language(state)

    resp = await _llm_chat(
        [
            Message(
                role="system",
                content=(
                    "You are an excellent educator.\n"
                    "Write a clear step-by-step explanation broken into distinct\n"
                    "visual stages - each stage should be something that can be\n"
                    "drawn or animated on screen, in the order a viewer should see\n"
                    "it. Be thorough: cover the setup, each reasoning step, and the\n"
                    "conclusion, rather than jumping to the result.\n"
                    "Output plain text.\n"
                    f"\nLANGUAGE: Write the ENTIRE answer in {_language_name(language)}.\n"
                    "Use natural, fluent wording - do not translate literally.\n"
                    "Keep mathematical formulas, symbols, units and variable names\n"
                    "in standard notation (Latin/Greek letters); translate only the words.\n"
                    "Scientific terms may keep their international form where that is\n"
                    "what a native speaker would actually use.\n"
                ),
            ),
            Message(
                role="user",
                content=(
                    f"Subject: {subject}\nRequest: {q}"
                    + (f"\n\nImage context:\n{img_ctx}" if img_ctx else "")
                ),
            ),
        ]
    )
    return {"educator_text": resp.content.strip(), "output_language": language}


async def generate_manim_script(state: ScienceVideoState) -> Dict[str, Any]:
    q = (state.get("user_message") or "").strip()
    subject = (state.get("subject") or "science").strip()
    educator_text = (state.get("educator_text") or "").strip()
    img_ctx = (state.get("image_context") or "").strip()

    # Instrumentation: how much of the educator explanation is actually
    # visible here. Empty means this node ran before educator_answer's
    # result was merged into the state.
    print(f"[manim_script] educator_text length at entry: {len(educator_text)}", flush=True)

    if DOC_SNIPPET_MODE == "1":
        return {
            "manim_script": """
from manim import *

class Demo(Scene):
    def construct(self):
        t = Text("Science demo")
        self.play(Write(t))
        self.wait(1)
""".strip()
        }

    allow_latex = _latex_toolchain_healthy()
    language = _resolve_output_language(state)
    language_name = _language_name(language)

    system_prompt = build_manim_system_prompt(allow_latex, language_name)

    resp = await _llm_chat(
        [
            Message(role="system", content=system_prompt),
            Message(
                role="user",
                content=(
                    f"Create a Manim animation for:\n\n"
                    f"Subject: {subject}\n"
                    f"User request: {q}\n\n"
                    + (f"Image context:\n{img_ctx}\n\n" if img_ctx else "")
                    + f"Explanation to visualize:\n{educator_text}\n\n"
                    + f"All on-screen wording must be in {language_name}.\n"
                ),
            ),
        ]
    )

    script = _strip_code_fences(resp.content)
    lines = [ln.rstrip() for ln in script.splitlines() if ln.strip() != ""]
    if not lines:
        raise RuntimeError("LLM returned empty Manim script")
    if lines[0].strip() != "from manim import *":
        script = "from manim import *\n\n" + script

    # Safety: Replace Title with Text if no LaTeX
    if (not allow_latex) and ("Title(" in script):
        script = script.replace("Title(", "Text(")
        script = re.sub(
            r"^(\s*\w+\s*=\s*Text\([^\n]*\))\s*$",
            r"\1.to_edge(UP)",
            script,
            flags=re.MULTILINE,
        )

    # Repair forbidden helpers
    if _contains_forbidden_manim(script):
        rewrite = await _llm_chat(
            [
                Message(
                    role="system",
                    content=REWRITE_FORBIDDEN_HELPERS_SYSTEM_PROMPT,
                ),
                Message(role="user", content=f"Rewrite:\n\n{script}"),
            ]
        )
        script2 = _strip_code_fences(rewrite.content)
        if script2 and not _contains_forbidden_manim(script2):
            if script2.split("\n")[0].strip() != "from manim import *":
                script2 = "from manim import *\n\n" + script2
            script = script2

    # Remove Tex/MathTex if no LaTeX
    if (not allow_latex) and _contains_latex_objects(script):
        rewrite = await _llm_chat(
            [
                Message(
                    role="system",
                    content=REWRITE_WITHOUT_LATEX_SYSTEM_PROMPT,
                ),
                Message(role="user", content=f"Rewrite:\n\n{script}"),
            ]
        )
        script2 = _strip_code_fences(rewrite.content)
        if script2 and not _contains_latex_objects(script2):
            if script2.split("\n")[0].strip() != "from manim import *":
                script2 = "from manim import *\n\n" + script2
            script = script2

    # Cyrillic inside Tex/MathTex will not compile - move those words into Text().
    if _tex_contains_cyrillic(script):
        rewrite = await _llm_chat(
            [
                Message(
                    role="system",
                    content=REWRITE_CYRILLIC_IN_TEX_SYSTEM_PROMPT,
                ),
                Message(role="user", content=f"Rewrite:\n\n{script}"),
            ]
        )
        script2 = _strip_code_fences(rewrite.content)
        if script2 and not _tex_contains_cyrillic(script2):
            if script2.split("\n")[0].strip() != "from manim import *":
                script2 = "from manim import *\n\n" + script2
            script = script2

    script = _ensure_unicode_font(script)
    return {"manim_script": script}


async def format_output(state: ScienceVideoState) -> Dict[str, Any]:
    if not state.get("is_science"):
        return {}

    text = (state.get("educator_text") or "").strip()
    video_path = (state.get("video_path") or "").strip()

    # Render failed even after the repair attempts: keep the explanation the
    # user already earned, and append a friendly note instead of an error.
    if state.get("video_needed") and not video_path:
        language = _resolve_output_language(state)
        note = _RENDER_FALLBACK_MESSAGES.get(language, _RENDER_FALLBACK_MESSAGES["kk"])
        text = f"{text}\n\n---\n\n{note}" if text else note

    return {
        "final_text": text,
        "final_video_path": video_path if state.get("video_needed") else None,
    }
