"""
Science Manim Graph Agent - Generates educational videos using Manim.

This agent:
1. Analyzes user questions (optionally with images)
2. Classifies if the question is science/educational
3. Decides if a video is needed
4. Generates educator explanation + Manim script
5. Renders the video using MCP
"""

import asyncio
import json
import os
import re
import mimetypes
import time
from typing import Any, Dict, Optional, TypedDict, List, Tuple

from spoon_ai.graph import END, StateGraph
from spoon_ai.schema import Message
from spoon_ai.tools.mcp_tool import MCPTool

# Environment, language helpers, prompt text, the LLM client and the Manim
# script guards now live in the anyq package.
# Importing anyq.config is also what calls load_dotenv().
# DEFAULT_OUTPUT_LANGUAGE, _detect_language, MANIM_API_REFERENCE, _LANGUAGE_NAMES,
# _KAZAKH_ONLY_CHARS and _FONT_PREFERENCES are re-exported from here for the
# modules that import them from science_manim_graph_agent (e.g. agent_ws_client).
from anyq.config import (  # noqa: F401 - re-exported
    DEFAULT_OUTPUT_LANGUAGE,
    DOC_SNIPPET_MODE,
    GEMINI_API_KEY,
    GEMINI_VISION_MODEL,
    MANIM_ALLOW_LATEX,
    MANIM_EXECUTABLE,
    MANIM_MCP_PYTHON,
    MANIM_MCP_SERVER_SCRIPT,
    _LLM_RETRIES,
    _LLM_RETRY_BASE_DELAY,
    _RENDER_REPAIR_ATTEMPTS,
)
from anyq.language import (  # noqa: F401 - re-exported
    _FONT_PREFERENCES,
    _KAZAKH_ONLY_CHARS,
    _LANGUAGE_NAMES,
    _REJECT_MESSAGES,
    _RENDER_FALLBACK_MESSAGES,
    _detect_language,
    _language_name,
    _pick_unicode_font,
    _resolve_output_language,
)
from anyq.llm_client import (  # noqa: F401 - re-exported
    _TRANSIENT_LLM_MARKERS,
    _is_transient_llm_error,
    _llm_chat,
    llm,
)
from anyq.prompts import (  # noqa: F401 - re-exported
    MANIM_API_REFERENCE,
    RENDER_REPAIR_SYSTEM_PROMPT,
    REWRITE_CYRILLIC_IN_TEX_SYSTEM_PROMPT,
    REWRITE_FORBIDDEN_HELPERS_SYSTEM_PROMPT,
    REWRITE_WITHOUT_LATEX_SYSTEM_PROMPT,
    build_manim_system_prompt,
)
from anyq.script_guard import (  # noqa: F401 - re-exported
    _CODE_FENCE_RE,
    _TEX_CALL_RE,
    _contains_forbidden_manim,
    _contains_latex_objects,
    _ensure_unicode_font,
    _latex_is_available,
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

    # output
    final_text: str
    final_video_path: str


def _guess_image_mime_type(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if mime:
        return mime
    return "image/jpeg"


def _analyze_one_image_sync(*, image_path: str, user_q: str, api_key: str, model: str) -> Tuple[str, str]:
    """
    Synchronous helper that calls Gemini with (text + image).
    """
    from google import genai
    from google.genai import types

    mime_type = _guess_image_mime_type(image_path)
    with open(image_path, "rb") as f:
        img_bytes = f.read()

    prompt = (
        "Analyze the provided image for helping answer the user's question.\n"
        "IMPORTANT: the image may contain student highlights/annotations.\n\n"
        "Return ONLY valid JSON with keys:\n"
        '- "summary": string (1-2 sentences)\n'
        '- "highlighted_or_annotated": string\n'
        '- "extracted_text": string\n'
        '- "science_subject_guess": string\n'
        '- "question_focus_guess": string\n'
        f"User question: {user_q}"
    )

    contents = [
        types.Part.from_text(text=prompt),
        types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
    ]

    with genai.Client(api_key=api_key) as client:
        # Same transient-error retry as _llm_chat, but this call is synchronous
        # (it already runs in a worker thread via asyncio.to_thread).
        for attempt in range(_LLM_RETRIES + 1):
            try:
                resp = client.models.generate_content(model=model, contents=contents)
                break
            except Exception as exc:  # noqa: BLE001 - re-raised below
                if attempt >= _LLM_RETRIES or not _is_transient_llm_error(exc):
                    raise
                delay = _LLM_RETRY_BASE_DELAY * (2 ** attempt)
                print(
                    f"[vision] transient error (attempt {attempt + 1}/{_LLM_RETRIES + 1}), "
                    f"retrying in {delay:.0f}s: {exc}",
                    flush=True,
                )
                time.sleep(delay)

    text = getattr(resp, "text", None) or ""
    payload = _safe_json_loads(text)
    if not payload:
        return (text.strip(), text.strip())

    image_context = (
        f"Image summary: {payload.get('summary','')}\n"
        f"Student highlights: {payload.get('highlighted_or_annotated','')}\n"
        f"Extracted text: {payload.get('extracted_text','')}\n"
        f"Focus guess: {payload.get('question_focus_guess','')}\n"
    ).strip()

    return (image_context, json.dumps(payload, ensure_ascii=False))


async def analyze_image_with_gemini(state: ScienceVideoState) -> Dict[str, Any]:
    """Optional first step: analyze an image with Gemini."""
    image_paths: List[str] = []
    if state.get("image_paths"):
        image_paths = [p.strip() for p in (state.get("image_paths") or []) if str(p).strip()]
    elif state.get("image_path"):
        image_paths = [str(state.get("image_path") or "").strip()]

    if not image_paths:
        return {}

    if DOC_SNIPPET_MODE == "1":
        return {"image_context": "(stub)", "image_analysis_json": "{}"}

    for p in image_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Image file not found: {p}")

    api_key = GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for image analysis")

    user_q = (state.get("user_message") or "").strip()
    model = GEMINI_VISION_MODEL

    tasks = [
        asyncio.to_thread(_analyze_one_image_sync, image_path=p, user_q=user_q, api_key=api_key, model=model)
        for p in image_paths
    ]
    results = await asyncio.gather(*tasks)

    contexts: List[str] = []
    jsons: List[str] = []
    for idx, (ctx, js) in enumerate(results, start=1):
        contexts.append(f"[Image {idx}: {image_paths[idx-1]}]\n{ctx}".strip())
        jsons.append(js)

    combined_context = "\n\n".join([c for c in contexts if c.strip()]).strip()
    return {
        "image_context": combined_context,
        "image_analysis_json": jsons[0] if jsons else "",
        "image_analysis_jsons": jsons,
    }


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


def _error_tail(text: str, limit: int = 400) -> str:
    """Last part of an error - the actual exception lives at the end."""
    s = (text or "").strip()
    return s[-limit:] if len(s) > limit else s


async def render_video(state: ScienceVideoState) -> Dict[str, Any]:
    script = (state.get("manim_script") or "").strip()
    if not script:
        raise ValueError("manim_script is required")

    server_script_path = MANIM_MCP_SERVER_SCRIPT
    if not server_script_path:
        raise RuntimeError(
            "Missing MANIM_MCP_SERVER_SCRIPT environment variable."
        )

    python_exe = MANIM_MCP_PYTHON
    env: Dict[str, str] = {}
    if MANIM_EXECUTABLE:
        env["MANIM_EXECUTABLE"] = MANIM_EXECUTABLE

    tool = MCPTool(
        name="manim_mcp",
        description="Render Manim animation via MCP",
        mcp_config={
            "command": python_exe,
            "args": [server_script_path],
            "env": env,
            "connection_timeout": 300,
            "max_retries": 2,
        },
    )

    # Render, and if Manim rejects the script, feed the error back to the model
    # and let it repair the script. Most failures are a single wrong keyword or
    # a hallucinated API, which the model fixes when shown the traceback.
    last_error = ""
    for attempt in range(_RENDER_REPAIR_ATTEMPTS + 1):
        raw = await tool.call_mcp_tool("execute_manim_code", manim_code=script)
        payload = _safe_json_loads(raw)

        if payload.get("status") == "ok":
            return {
                "video_path": str(payload.get("video_path") or ""),
                "mcp_raw_result": raw,
                "render_error": "",
            }

        last_error = str(payload.get("stderr") or payload.get("error") or raw)
        if attempt >= _RENDER_REPAIR_ATTEMPTS:
            break

        print(
            f"[render] failed (attempt {attempt + 1}/{_RENDER_REPAIR_ATTEMPTS + 1}), "
            f"asking model to repair: {_error_tail(last_error)}",
            flush=True,
        )

        repaired = await _llm_chat(
            [
                Message(
                    role="system",
                    content=RENDER_REPAIR_SYSTEM_PROMPT,
                ),
                Message(
                    role="user",
                    content=(
                        f"ERROR:\n{_error_tail(last_error, 2000)}\n\n"
                        f"SCRIPT:\n{script}"
                    ),
                ),
            ]
        )
        fixed = _strip_code_fences(repaired.content)
        if not fixed:
            break
        if fixed.split("\n")[0].strip() != "from manim import *":
            fixed = "from manim import *\n\n" + fixed
        script = _ensure_unicode_font(fixed)

    # Repair exhausted: do NOT raise. Returning the error lets format_output
    # show a friendly message instead of aborting the graph with a traceback.
    print(f"[render] giving up after repair attempts: {_error_tail(last_error)}", flush=True)
    return {"video_path": "", "mcp_raw_result": "", "render_error": last_error}


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


def build_app():
    graph = StateGraph(ScienceVideoState)
    graph.add_node("vision", analyze_image_with_gemini)
    graph.add_node("intent", classify_intent)
    graph.add_node("video_needed", decide_video_needed)
    graph.add_node("reject", reject_non_science)
    graph.add_node("educator_text", educator_answer)
    graph.add_node("educator_video", educator_answer)
    graph.add_node("manim_script", generate_manim_script)
    graph.add_node("render", render_video)
    graph.add_node("output", format_output)

    graph.add_parallel_group(
        "educate_and_script",
        ["educator_video", "manim_script"],
        {"join_strategy": "all_complete", "error_strategy": "fail_fast"},
    )

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
    graph.add_edge("educator_video", "render")
    graph.add_edge("render", "output")
    graph.add_edge("output", END)

    return graph.compile()


app = build_app()


async def run_once(user_message: str) -> ScienceVideoState:
    return await app.invoke({"user_message": user_message})


if __name__ == "__main__":
    import asyncio

    async def main():
        print("Science Manim Graph Agent (Anyq + MCP)")
        while True:
            user_message = input("you> ").strip()
            if not user_message:
                continue
            result = await app.invoke({"user_message": user_message})
            text = (result.get("final_text") or "").strip()
            vp = result.get("final_video_path")
            if text:
                print("\n" + text + "\n")
            print(f"Video: {vp}\n")

    asyncio.run(main())

