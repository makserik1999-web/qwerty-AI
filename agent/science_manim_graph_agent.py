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
import shutil
import sys
import mimetypes
import subprocess
import tempfile
import time
from typing import Any, Dict, Optional, TypedDict, List, Tuple

from spoon_ai.graph import END, StateGraph
from spoon_ai.llm import LLMManager
from spoon_ai.schema import Message
from spoon_ai.tools.mcp_tool import MCPTool

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


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


llm = LLMManager()

# Gemini intermittently returns 503 UNAVAILABLE ("experiencing high demand").
# A single failure otherwise aborts the whole graph, so retry transient errors
# with exponential backoff before giving up.
_LLM_RETRIES = int(os.getenv("GEMINI_RETRY_ATTEMPTS", "3"))
_LLM_RETRY_BASE_DELAY = float(os.getenv("GEMINI_RETRY_BASE_DELAY", "2"))

_TRANSIENT_LLM_MARKERS = (
    "503",
    "unavailable",
    "overloaded",
    "high demand",
    "429",
    "resource_exhausted",
    "rate limit",
    "500",
    "internal error",
    "502",
    "504",
    "deadline exceeded",
    "timeout",
)


def _is_transient_llm_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_LLM_MARKERS)


async def _llm_chat(messages, **kwargs):
    """llm.chat() with backoff retry on transient upstream errors."""
    last_exc: Optional[BaseException] = None
    for attempt in range(_LLM_RETRIES + 1):
        try:
            return await llm.chat(messages, **kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last_exc = exc
            if attempt >= _LLM_RETRIES or not _is_transient_llm_error(exc):
                raise
            delay = _LLM_RETRY_BASE_DELAY * (2 ** attempt)
            print(
                f"[llm] transient error (attempt {attempt + 1}/{_LLM_RETRIES + 1}), "
                f"retrying in {delay:.0f}s: {exc}",
                flush=True,
            )
            await asyncio.sleep(delay)
    raise last_exc  # pragma: no cover - loop always returns or raises

# ============== Output language ==============
# Explanations and all on-screen wording follow the user's language;
# Kazakh is the product default.
DEFAULT_OUTPUT_LANGUAGE = (os.getenv("DEFAULT_OUTPUT_LANGUAGE", "kk") or "kk").strip().lower()

_LANGUAGE_NAMES = {
    "kk": "Kazakh (қазақ тілі)",
    "ru": "Russian (русский язык)",
    "en": "English",
}

# Letters unique to Kazakh Cyrillic - distinguish Kazakh from Russian input.
_KAZAKH_ONLY_CHARS = set("әғқңөұүһі")


def _detect_language(text: str) -> Optional[str]:
    low = (text or "").lower()
    if any(ch in _KAZAKH_ONLY_CHARS for ch in low):
        return "kk"
    if any("Ѐ" <= ch <= "ӿ" for ch in low):
        return "ru"
    return None


def _resolve_output_language(state: "ScienceVideoState") -> str:
    """Explicit choice > language of the question > configured default."""
    explicit = str(state.get("output_language") or "").strip().lower()
    if explicit in _LANGUAGE_NAMES:
        return explicit
    detected = _detect_language(str(state.get("user_message") or ""))
    if detected:
        return detected
    return DEFAULT_OUTPUT_LANGUAGE if DEFAULT_OUTPUT_LANGUAGE in _LANGUAGE_NAMES else "kk"


def _language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code, _LANGUAGE_NAMES["kk"])


# ============== Fonts ==============
# Manim's default font does not reliably cover Kazakh Cyrillic (ә ғ қ ң ө ұ ү һ і),
# which renders as missing-glyph boxes. Pick a font that does.
_FONT_PREFERENCES = (
    "Arial Unicode MS",
    "Noto Sans",
    "DejaVu Sans",
    "PT Sans",
    "Helvetica",
    "Arial",
    "Verdana",
)

_cached_font: Optional[str] = None


def _pick_unicode_font() -> str:
    global _cached_font
    if _cached_font:
        return _cached_font

    override = os.getenv("MANIM_TEXT_FONT", "").strip()
    if override:
        _cached_font = override
        return _cached_font

    available = set()
    try:
        import manimpango

        available = set(manimpango.list_fonts())
    except Exception:
        pass

    for font in _FONT_PREFERENCES:
        if font in available:
            _cached_font = font
            return _cached_font

    _cached_font = "DejaVu Sans"
    return _cached_font


_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\n|\n```$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    cleaned = _CODE_FENCE_RE.sub("", (text or "")).strip()
    lines = [ln.rstrip() for ln in cleaned.splitlines()]
    while lines and lines[0].strip().lower() in {"python", "py"}:
        lines.pop(0)
    return "\n".join(lines).strip()


def _safe_json_loads(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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

    if os.getenv("DOC_SNIPPET_MODE") == "1":
        return {"image_context": "(stub)", "image_analysis_json": "{}"}

    for p in image_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Image file not found: {p}")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for image analysis")

    user_q = (state.get("user_message") or "").strip()
    model = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-pro")

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

    if os.getenv("DOC_SNIPPET_MODE") == "1":
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


_REJECT_MESSAGES = {
    "kk": (
        "Мен тек ғылыми тақырыптар бойынша оқу бейнелерін жасай аламын "
        "(математика, физика, химия, биология, информатика, инженерия, статистика).\n\n"
        "Сұрауыңызды ғылыми ұғым ретінде қайта тұжырымдаңыз."
    ),
    "ru": (
        "Я могу создавать обучающие видео только по научным темам "
        "(математика, физика, химия, биология, информатика, инженерия, статистика).\n\n"
        "Пожалуйста, переформулируйте запрос как научное понятие."
    ),
    "en": (
        "I can help create educational videos only for scientific topics "
        "(math, physics, chemistry, biology, CS, engineering, statistics).\n\n"
        "Please rephrase your request as a scientific concept."
    ),
}


async def reject_non_science(state: ScienceVideoState) -> Dict[str, Any]:
    language = _resolve_output_language(state)
    msg = _REJECT_MESSAGES.get(language, _REJECT_MESSAGES["kk"])
    return {"final_text": msg, "final_video_path": "", "output_language": language}


async def educator_answer(state: ScienceVideoState) -> Dict[str, Any]:
    q = (state.get("user_message") or "").strip()
    subject = (state.get("subject") or "science").strip()
    img_ctx = (state.get("image_context") or "").strip()

    if os.getenv("DOC_SNIPPET_MODE") == "1":
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


_TEX_CALL_RE = re.compile(r"\b(?:MathTex|Tex)\s*\(((?:[^()]|\([^()]*\))*)\)", re.DOTALL)


def _tex_contains_cyrillic(script: str) -> bool:
    """Cyrillic inside Tex()/MathTex() fails to compile - the TeX template has no
    Cyrillic support. Words belong in Text() instead."""
    for match in _TEX_CALL_RE.finditer(script or ""):
        if any("Ѐ" <= ch <= "ӿ" for ch in match.group(1)):
            return True
    return False


def _ensure_unicode_font(script: str) -> str:
    """Force a Kazakh/Cyrillic-capable font globally, so on-screen text never
    depends on the model remembering to pass font=."""
    if not script.strip():
        return script
    if "Text.set_default(" in script:
        return script

    font = _pick_unicode_font()
    directive = f'Text.set_default(font="{font}")'

    lines = script.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().startswith("from manim import"):
            lines.insert(idx + 1, "")
            lines.insert(idx + 2, directive)
            return "\n".join(lines)

    return f'from manim import *\n\n{directive}\n\n{script}'


def _contains_latex_objects(script: str) -> bool:
    s = script or ""
    return ("Tex(" in s) or ("MathTex(" in s)


def _contains_forbidden_manim(script: str) -> bool:
    s = script or ""
    forbidden = ["Checkmark", "Exmark", "Cross", "wait_for_input", "input(", "breakpoint("]
    return any(tok in s for tok in forbidden)


def _latex_is_available() -> bool:
    return shutil.which("latex") is not None


def _latex_toolchain_healthy() -> bool:
    if os.getenv("MANIM_ALLOW_LATEX") != "1":
        return False

    env = os.environ.copy()
    texbin = "/Library/TeX/texbin"
    if os.path.isdir(texbin):
        env["PATH"] = f"{texbin}:{env.get('PATH', '')}"

    if shutil.which("latex", path=env.get("PATH")) is None:
        return False
    if shutil.which("dvisvgm", path=env.get("PATH")) is None:
        return False

    tex = r"""
\documentclass[preview]{standalone}
\usepackage{amsmath}
\begin{document}
Test $x^2$
\end{document}
""".strip()

    try:
        with tempfile.TemporaryDirectory(prefix="latex_check_") as td:
            tex_path = os.path.join(td, "check.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(tex)

            cp = subprocess.run(
                ["latex", "-interaction=nonstopmode", "-halt-on-error", "check.tex"],
                cwd=td,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return cp.returncode == 0
    except Exception:
        return False


MANIM_API_REFERENCE = '''
=== MANIM COMMUNITY v0.19 API REFERENCE ===

CRITICAL RULES:
1. NEVER use deprecated methods like get_sides(), get_point_from_angle() with arguments
2. ALWAYS use simple, well-tested patterns shown below
3. NEVER use Checkmark, Exmark, Cross, wait_for_input, input(), breakpoint()
4. Use reliable patterns, and keep animations under 150 lines

=== WORKING EXAMPLES ===

EXAMPLE 1: Basic Shapes and Text
```python
from manim import *

class BasicShapes(Scene):
    def construct(self):
        # Title
        title = Text("Basic Shapes", font_size=48)
        self.play(Write(title))
        self.wait(0.5)
        self.play(title.animate.to_edge(UP))
        
        # Create shapes
        circle = Circle(radius=1, color=BLUE, fill_opacity=0.5)
        square = Square(side_length=2, color=RED)
        triangle = Triangle(color=GREEN, fill_opacity=0.5)
        
        # Position shapes
        circle.shift(LEFT * 3)
        triangle.shift(RIGHT * 3)
        
        # Animate
        self.play(Create(circle), Create(square), Create(triangle))
        self.wait(1)
        self.play(FadeOut(circle), FadeOut(square), FadeOut(triangle), FadeOut(title))
```

EXAMPLE 2: Mathematical Equations (with LaTeX)
```python
from manim import *

class MathEquations(Scene):
    def construct(self):
        # Title
        title = Tex("Pythagorean Theorem", font_size=48)
        self.play(Write(title))
        self.wait(0.5)
        self.play(title.animate.to_edge(UP))
        
        # Equation
        equation = MathTex("a^2", "+", "b^2", "=", "c^2", font_size=64)
        equation.set_color_by_tex("a", RED)
        equation.set_color_by_tex("b", GREEN)
        equation.set_color_by_tex("c", BLUE)
        
        self.play(Write(equation))
        self.wait(1)
        
        # Box around equation
        box = SurroundingRectangle(equation, color=YELLOW, buff=0.3)
        self.play(Create(box))
        self.wait(1)
```

EXAMPLE 3: Graphs and Functions
```python
from manim import *

class GraphExample(Scene):
    def construct(self):
        # Create axes
        axes = Axes(
            x_range=[-4, 4, 1],
            y_range=[-2, 2, 1],
            x_length=8,
            y_length=4,
            axis_config={"include_numbers": True}
        )
        
        # Plot sine function
        sine_graph = axes.plot(lambda x: np.sin(x), color=BLUE)
        sine_label = axes.get_graph_label(sine_graph, label="\\sin(x)")
        
        self.play(Create(axes))
        self.wait(0.5)
        self.play(Create(sine_graph), Write(sine_label))
        self.wait(1)
```

EXAMPLE 4: Transformations
```python
from manim import *

class TransformExample(Scene):
    def construct(self):
        circle = Circle(color=BLUE, fill_opacity=0.5)
        square = Square(color=RED, fill_opacity=0.5)
        
        self.play(Create(circle))
        self.wait(0.5)
        self.play(Transform(circle, square))
        self.wait(0.5)
        self.play(circle.animate.scale(2))
        self.wait(0.5)
        self.play(circle.animate.shift(RIGHT * 2))
        self.wait(1)
```

EXAMPLE 5: Right Triangle with Labels
```python
from manim import *

class RightTriangle(Scene):
    def construct(self):
        # Create triangle using vertices
        A = np.array([-2, -1, 0])
        B = np.array([2, -1, 0])
        C = np.array([-2, 1.5, 0])
        
        triangle = Polygon(A, B, C, color=WHITE, fill_opacity=0.3)
        
        # Create sides as separate lines for labeling
        side_a = Line(A, C, color=RED)
        side_b = Line(A, B, color=GREEN)
        side_c = Line(B, C, color=BLUE)
        
        # Labels
        label_a = MathTex("a", color=RED).next_to(side_a, LEFT)
        label_b = MathTex("b", color=GREEN).next_to(side_b, DOWN)
        label_c = MathTex("c", color=BLUE).next_to(side_c, UR, buff=0.1)
        
        # Right angle marker
        right_angle = Square(side_length=0.3, color=WHITE)
        right_angle.move_to(A + np.array([0.15, 0.15, 0]))
        
        # Animate
        self.play(Create(triangle))
        self.play(Create(side_a), Create(side_b), Create(side_c))
        self.play(Write(label_a), Write(label_b), Write(label_c))
        self.play(Create(right_angle))
        self.wait(1)
```

EXAMPLE 6: Moving Dot Along Path
```python
from manim import *

class MovingDot(Scene):
    def construct(self):
        # Create a circle path
        circle = Circle(radius=2, color=BLUE)
        dot = Dot(color=RED).move_to(circle.point_from_proportion(0))
        
        self.play(Create(circle))
        self.add(dot)
        
        # Move dot along circle
        self.play(MoveAlongPath(dot, circle), run_time=3, rate_func=linear)
        self.wait(1)
```

EXAMPLE 7: Number Line and ValueTracker
```python
from manim import *

class NumberLineExample(Scene):
    def construct(self):
        # Create number line
        number_line = NumberLine(x_range=[-5, 5, 1], include_numbers=True)
        
        # Moving dot
        tracker = ValueTracker(-5)
        dot = Dot(color=RED)
        dot.add_updater(lambda d: d.move_to(number_line.n2p(tracker.get_value())))
        
        self.play(Create(number_line))
        self.add(dot)
        self.play(tracker.animate.set_value(5), run_time=3)
        self.wait(1)
```

=== KEY API PATTERNS ===
- Create shapes: Circle(), Square(), Triangle(), Polygon(), Line(), Arrow(), Dot()
- Text: Text("text"), Tex("LaTeX"), MathTex("a^2 + b^2")
- Positioning: .shift(LEFT/RIGHT/UP/DOWN * n), .to_edge(UP/DOWN/LEFT/RIGHT), .move_to(point)
- Animations: Create(), Write(), FadeIn(), FadeOut(), Transform(), ReplacementTransform()
- Movement: .animate.shift(), .animate.scale(), .animate.rotate(), MoveAlongPath()
- Axes: Axes(x_range, y_range), axes.plot(func), axes.get_graph_label()
- Colors: RED, BLUE, GREEN, YELLOW, WHITE, PURPLE, ORANGE, PINK
- Waiting: self.wait(seconds)

=== AVOID THESE DEPRECATED/BROKEN PATTERNS ===
- polygon.get_sides() - BROKEN, use Line() between vertices instead
- circle.get_point_from_angle(angle) - BROKEN, use circle.point_from_proportion(angle/TAU)
- get_edge_center() with complex objects - may fail
- get_corner_in_dir() - BROKEN, don't use
- get_vertices() with move_to(aligned_edge=...) - BROKEN, use simple positioning
- Title() - use Text() instead
- ANY method that requires an argument inside move_to() except basic coordinates

=== SAFE PATTERNS TO USE INSTEAD ===
- For positioning at corners/vertices: calculate positions manually using np.array coordinates
- For right angle markers: create a small Square and position it with .move_to(corner_position)
- For vertex labels: use .next_to(vertex_position, direction) with explicit coordinates
- ALWAYS use simple, explicit positioning with coordinates like np.array([x, y, 0])
'''


async def generate_manim_script(state: ScienceVideoState) -> Dict[str, Any]:
    q = (state.get("user_message") or "").strip()
    subject = (state.get("subject") or "science").strip()
    educator_text = (state.get("educator_text") or "").strip()
    img_ctx = (state.get("image_context") or "").strip()

    if os.getenv("DOC_SNIPPET_MODE") == "1":
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

    system_prompt = f"""{MANIM_API_REFERENCE}

You are an expert Manim Community script writer.

INSTRUCTIONS:
1. Return ONLY valid Python code. No markdown, no explanations.
2. Must start with: from manim import *
3. Must define exactly ONE Scene class.
4. Keep it under 150 lines.
5. Use ONLY the patterns shown in the API reference above.
6. Always use reliable patterns - avoid deprecated or obscure methods.
7. Use full-screen transitions, avoid overlaps.

=== DEPTH OF THE ANIMATION (IMPORTANT) ===
A. Inside that ONE Scene, animate the full reasoning as MULTIPLE SEQUENTIAL
   STEPS. Never jump straight to a finished static picture with a formula.
B. Structure the scene as:
   - BUILD-UP: introduce the objects one at a time, each with its own
     self.play(...) call, so the viewer sees the setup being constructed.
   - TRANSFORMATION: show the actual reasoning/derivation happening - move,
     rotate, split, recolour, or Transform()/ReplacementTransform() the
     objects step by step. This is the heart of the animation: each logical
     step in the explanation gets its own on-screen step.
   - CONCLUSION: end by stating the result, highlighting the key formula or
     relationship you have just demonstrated.
C. Give each step a short caption in the target language via Text(), fading
   the previous caption out (FadeOut) before showing the next one.
D. Use MANY self.play(...) calls with self.wait(0.5-1.5) between them, so the
   animation is paced and readable rather than instantaneous.
E. Aim for a substantial, detailed animation - typically 8-15 distinct
   animated steps - while staying inside the line limit and using only the
   safe patterns from the API reference.

=== LAYOUT AND SCREEN MANAGEMENT (CRITICAL) ===
Overlapping text is the most common failure. Obey these rules strictly:
L1. THE SINGLE-CAPTION RULE (MANDATORY - use this pattern).
    Create the bottom caption ONCE, then keep REUSING that same mobject for
    every later step by morphing it with Transform. Because only one caption
    object ever exists, it is structurally impossible for an old caption to be
    left behind on screen:

        caption = Text("First step", font_size=26).to_edge(DOWN, buff=0.5)
        self.play(FadeIn(caption))
        self.wait(1)

        # every later step - reuse the SAME object, never create a second one
        self.play(Transform(caption, Text("Second step", font_size=26).to_edge(DOWN, buff=0.5)))
        self.wait(1)

        self.play(Transform(caption, Text("Third step", font_size=26).to_edge(DOWN, buff=0.5)))
        self.wait(1)

    Rules for this pattern:
    - Create the caption variable EXACTLY ONCE, before the first step.
    - For EVERY subsequent step use Transform(caption, Text(...).to_edge(DOWN, buff=0.5)).
    - NEVER reassign `caption = ...` after it is created.
    - NEVER call Write()/FadeIn() on a second caption object.
    - Always give the replacement Text the SAME .to_edge(DOWN, buff=0.5)
      position and the same font_size, so it stays in the caption zone.
L2. FALLBACK PATTERN (only if you truly cannot use Transform): if you create a
    NEW Text per step, then the previous caption MUST be removed BEFORE the new
    one appears - in the SAME self.play(...) call:
        self.play(FadeOut(old_caption), FadeIn(new_caption))
    This applies to EVERY step without exception, including the last step and
    any branch/skipped step. An old caption must never survive into the next
    step. Prefer L1 - it is the reliable one.
L3. FIXED ZONES - never put two things in the same place:
    - Title: .to_edge(UP)
    - Explanatory caption: .to_edge(DOWN)
    - Main diagram / formulas: the centre of the screen
    Keep captions ALWAYS in the same zone so they never collide.
L4. NEVER leave multiple objects at the default centre position. Every
    mobject must be explicitly placed with .to_edge(), .to_corner(),
    .next_to(other, DIRECTION, buff=0.3), .shift(), .move_to(np.array([x,y,0]))
    or grouped with VGroup(...).arrange(DOWN, buff=0.4).
L5. LABELS GO OUTSIDE THEIR SHAPE. Attach a label with
    .next_to(shape, DIRECTION, buff=0.25) - do not stack two labels on the
    same shape, and do not place a formula box on top of a filled shape.
L6. STAY INSIDE THE FRAME. The visible area is about x in [-7, 7] and
    y in [-4, 4]. Keep every object within it. If a diagram is large, wrap it
    in a VGroup and call .scale(0.7) and/or .move_to(ORIGIN) so nothing is
    clipped at the edges.
L7. LONG TEXT MUST FIT. Use font_size=24-30 for captions, font_size=36-48 for
    titles. If a sentence is long, shorten it or split it into two shorter
    captions shown one after another - never let text run off screen or across
    the diagram.
L8. When the diagram itself changes (new shapes added), fade out or shift the
    parts that are no longer needed, so the screen never becomes cluttered.
8. {"LaTeX is available. Use MathTex/Tex for equations." if allow_latex else "LaTeX NOT available. Use Text() only, not Tex or MathTex."}
9. NEVER use deprecated methods. Follow the examples exactly.

=== LANGUAGE OF ON-SCREEN TEXT (CRITICAL) ===
10. EVERY human-readable string shown on screen - titles, labels, captions,
    axis labels, legends, annotations - MUST be written in {language_name}.
    Do not leave them in English.
11. Put ALL natural-language wording inside Text(). NEVER place non-Latin
    characters (Cyrillic, including Kazakh letters ә ғ қ ң ө ұ ү һ і) inside
    Tex() or MathTex() - the LaTeX compiler has no Cyrillic support configured
    and the render WILL fail.
12. Mathematics stays untranslated and in LaTeX: keep formulas, equations,
    variables, operators, digits and units in MathTex() with standard notation
    (e.g. MathTex(r"E_k = \\frac{{mv^2}}{{2}}")). Translate the WORDS around the
    formula, never the formula itself.
13. To label a formula, use a separate Text() in {language_name} positioned
    next to the MathTex() - do not mix the two in one mobject.
14. Do NOT pass a `font=` argument to Text(); the correct Unicode font is
    configured globally by the runtime.
"""

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
                    content=(
                        "Rewrite the Manim script without forbidden items.\n"
                        "MUST NOT use: Checkmark, Exmark, Cross, wait_for_input, input().\n"
                    ),
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
                    content="Rewrite without Tex/MathTex. Use Text() instead.\n",
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
                    content=(
                        "The Manim script puts Cyrillic text inside Tex()/MathTex(), "
                        "which cannot compile.\n"
                        "Move every Cyrillic word into a separate Text() mobject, "
                        "positioned with .next_to(...).\n"
                        "Keep all mathematics in MathTex() with untranslated LaTeX "
                        "notation. Return ONLY Python code.\n"
                    ),
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


# How many times to ask the model to repair a script Manim refused to render.
_RENDER_REPAIR_ATTEMPTS = int(os.getenv("MANIM_REPAIR_ATTEMPTS", "2"))

# Shown when rendering fails even after repair - the user must never see a
# traceback.
_RENDER_FALLBACK_MESSAGES = {
    "kk": (
        "😔 Кешіріңіз, бұл тақырып бойынша анимацияны әзірге жасай алмадым. "
        "Басқа тақырыпты байқап көріңізші."
    ),
    "ru": (
        "😔 Модель пока не поддерживает эту тему для анимации. "
        "Попробуйте, пожалуйста, другую тему."
    ),
    "en": (
        "😔 Sorry, I couldn't animate this topic yet. Please try another one."
    ),
}


def _error_tail(text: str, limit: int = 400) -> str:
    """Last part of an error - the actual exception lives at the end."""
    s = (text or "").strip()
    return s[-limit:] if len(s) > limit else s


async def render_video(state: ScienceVideoState) -> Dict[str, Any]:
    script = (state.get("manim_script") or "").strip()
    if not script:
        raise ValueError("manim_script is required")

    server_script_path = os.getenv("MANIM_MCP_SERVER_SCRIPT")
    if not server_script_path:
        raise RuntimeError(
            "Missing MANIM_MCP_SERVER_SCRIPT environment variable."
        )

    python_exe = os.getenv("MANIM_MCP_PYTHON", sys.executable)
    env: Dict[str, str] = {}
    if os.getenv("MANIM_EXECUTABLE"):
        env["MANIM_EXECUTABLE"] = os.environ["MANIM_EXECUTABLE"]

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
                    content=(
                        "You are fixing a Manim Community v0.19 script that failed "
                        "to render.\n"
                        "You are given the script and the exact error it produced.\n"
                        "Return ONLY the corrected, complete Python script - no "
                        "markdown, no explanation.\n"
                        "Fix the specific cause of the error (wrong keyword argument, "
                        "non-existent method, bad parameter). If an API is unreliable, "
                        "replace that part with a simpler construction using basic "
                        "shapes, Text, MathTex and Transform.\n"
                        "Keep the same educational content, the same on-screen "
                        "language, and exactly ONE Scene class.\n"
                    ),
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

