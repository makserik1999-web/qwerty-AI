"""Sanity checks and fixups applied to LLM-produced Manim scripts.

Includes an AST-based safety validator: the only real sandbox boundary
(container isolation is the other one). Everything here must stay importable
without spoon-ai-sdk (check.sh exercises these helpers against a stub).

_ensure_unicode_font uses _pick_unicode_font from anyq.language rather than a
copy of it.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Tuple

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


_latex_health_cache: Dict[str, Any] = {"checked": False, "healthy": False}


def _latex_toolchain_healthy() -> bool:
    """True when the LaTeX toolchain works. Probed once and cached thereafter.

    This is a blocking subprocess probe; call it from a worker thread
    (asyncio.to_thread) when used inside the async graph.
    """
    if _latex_health_cache["checked"]:
        return _latex_health_cache["healthy"]

    result = False
    if MANIM_ALLOW_LATEX == "1":
        env = os.environ.copy()
        texbin = "/Library/TeX/texbin"
        if os.path.isdir(texbin):
            env["PATH"] = f"{texbin}:{env.get('PATH', '')}"

        if shutil.which("latex", path=env.get("PATH")) is not None and shutil.which(
            "dvisvgm", path=env.get("PATH")
        ) is not None:
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
                    result = cp.returncode == 0
            except Exception:
                result = False

    _latex_health_cache["checked"] = True
    _latex_health_cache["healthy"] = result
    return result


# ================= AST safety validator =================
# The Manim script is LLM-generated (and may embed attacker-controlled text).
# It runs inside the agent container, so besides container isolation we refuse
# anything that is not a plain Manim scene: whitelisted imports only, no
# module-level code beyond imports/classes/simple assignments, and no
# dangerous builtins anywhere.
_ALLOWED_IMPORT_MODULES = {"manim", "numpy", "math", "random", "typing"}
_ALLOWED_DUNDER_ATTRS = {"__init__", "__name__"}
_FORBIDDEN_NAMES = {
    "eval", "exec", "open", "input", "breakpoint", "compile", "__import__",
    "globals", "locals", "vars", "memoryview", "exit", "quit", "help",
    "getattr", "setattr", "delattr", "socket", "requests", "os", "sys",
    "subprocess", "importlib", "ctypes",
}


def _import_module_ok(node: ast.AST) -> str:
    """Returns "" when the import is allowed, else a reason."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            root = (alias.name or "").split(".")[0]
            if root not in _ALLOWED_IMPORT_MODULES:
                return f"import of {alias.name!r} is not allowed"
        return ""
    if isinstance(node, ast.ImportFrom):
        if not node.module:
            return "relative imports are not allowed"
        root = node.module.split(".")[0]
        if root not in _ALLOWED_IMPORT_MODULES:
            return f"import from {node.module!r} is not allowed"
        return ""
    return "internal error: not an import"


def _validate_module_level(tree: ast.Module) -> str:
    """Only imports, class definitions, simple assignments and a docstring /
    Text.set_default(...) call may live at module level."""
    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            reason = _import_module_ok(stmt)
            if reason:
                return reason
            continue
        if isinstance(stmt, ast.ClassDef):
            if stmt.decorator_list:
                return "class decorators are not allowed"
            continue
        if isinstance(stmt, ast.Assign):
            if not all(isinstance(t, ast.Name) for t in stmt.targets):
                return "module-level assignment must use plain variable names"
            continue
        if isinstance(stmt, ast.AnnAssign):
            if not isinstance(stmt.target, ast.Name):
                return "module-level annotation must use a plain variable name"
            continue
        if isinstance(stmt, ast.Expr):
            # docstring or the font directive Text.set_default(font="...")
            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                continue
            if (
                isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and getattr(stmt.value.func, "attr", "") == "set_default"
                and isinstance(stmt.value.func.value, ast.Name)
                and stmt.value.func.value.id == "Text"
            ):
                continue
            return "module-level code is not allowed (only imports and class definitions)"
        if isinstance(stmt, ast.Pass):
            continue
        return f"module-level statement of type {type(stmt).__name__} is not allowed"
    return ""


def _validate_all_nodes(tree: ast.Module) -> str:
    """Walk everything: banned imports, banned builtins, dunder escapes."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            reason = _import_module_ok(node)
            if reason:
                return reason
        elif isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_NAMES:
                return f"forbidden name {node.id!r}"
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr in _FORBIDDEN_NAMES:
                return f"forbidden attribute {attr!r}"
            if attr.startswith("__") and attr not in _ALLOWED_DUNDER_ATTRS:
                return f"forbidden dunder attribute {attr!r}"
        elif isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in _FORBIDDEN_NAMES:
                return f"forbidden call {name!r}"
        elif isinstance(node, ast.Dict):
            # string keys starting with "__" can smuggle dunder attribute names
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and str(k.value).startswith("__"):
                    return f"forbidden string key {k.value!r}"
        elif isinstance(node, ast.keyword):
            if node.arg and node.arg.startswith("__"):
                return f"forbidden keyword argument {node.arg!r}"
    return ""


def validate_manim_script(script: str) -> Tuple[bool, str]:
    """AST-based safety validation. Returns (ok, reason).

    When ok is False the script MUST NOT be executed or rendered - callers
    surface a clear error instead of running it.
    """
    text = script or ""
    if not text.strip():
        return False, "script is empty"
    try:
        tree = ast.parse(text, mode="exec")
    except SyntaxError as e:
        return False, f"syntax error: {e.msg} (line {e.lineno})"

    reason = _validate_module_level(tree)
    if reason:
        return False, reason
    reason = _validate_all_nodes(tree)
    if reason:
        return False, reason
    return True, ""