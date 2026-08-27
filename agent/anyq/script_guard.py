"""Sanity checks and fixups applied to LLM-produced Manim scripts.

Moved verbatim out of science_manim_graph_agent.py. _ensure_unicode_font uses
_pick_unicode_font from anyq.language rather than a copy of it.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict

from anyq.config import MANIM_ALLOW_LATEX
from anyq.language import _pick_unicode_font


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
    if MANIM_ALLOW_LATEX != "1":
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
