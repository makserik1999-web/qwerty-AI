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


# The first {...} block in a reply, for models that introduce their JSON with
# a sentence. Non-greedy from the first brace to the last is wrong for nested
# objects, so this matches balanced-enough text and json.loads does the rest.
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _safe_json_loads(text: str) -> Dict[str, Any]:
    """Parse a JSON object out of a model reply.

    Asking for "ONLY valid JSON" is not enough: gemini-3.7-flash returns the
    correct object wrapped in a ```json fence, and other models introduce it
    with a sentence. Both used to parse as nothing, and because every caller
    reads the result with .get(), the failure was silent - classify_intent
    saw no "is_science" key and rejected every question as non-scientific.
    So: try the text as given, then without fences, then the first object in
    it.
    """
    raw = text or ""
    for candidate in (raw, _strip_code_fences(raw)):
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict):
            return data

    match = _JSON_OBJECT_RE.search(_strip_code_fences(raw))
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
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


_SCENE_BASE_RE = re.compile(
    r"^(class\s+\w+\s*\(\s*)Scene(\s*\)\s*:)", re.MULTILINE
)


def _ensure_narration_base(script: str) -> str:
    """Make the script inherit VoiceoverScene whether or not the model did.

    The same shape renders with or without sound - anyq_narration decides
    which - so this is safe to apply unconditionally, and applying it
    unconditionally is the point: when the model forgets the base class its
    voiceover blocks raise AttributeError at render time, which costs a repair
    round trip to fix something we can simply supply.
    """
    if not script.strip():
        return script

    script = _SCENE_BASE_RE.sub(r"\1VoiceoverScene\2", script)

    if "from anyq_narration import" in script:
        return script

    lines = script.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().startswith("from manim import"):
            lines.insert(idx + 1, "from anyq_narration import VoiceoverScene")
            return "\n".join(lines)

    return ("from manim import *\n"
            "from anyq_narration import VoiceoverScene\n\n" + script)


# Every scene base a model has been seen to write, and VoiceoverScene, which
# _ensure_narration_base turns a plain Scene into.
_ANY_SCENE_BASE_RE = re.compile(
    r"^(class\s+\w+\s*\(\s*)"
    r"(?:Scene|VoiceoverScene|MovingCameraScene|ThreeDScene|ZoomedScene)"
    r"(\s*\)\s*:)",
    re.MULTILINE,
)
_NARRATION_IMPORT_RE = re.compile(r"^from anyq_narration import [^\n]*$", re.MULTILINE)


def _ensure_motion_base(script: str) -> str:
    """Make the scene inherit MotionScene - the motion layer (MOTION_LAYER=1).

    Applied after _ensure_narration_base and to every rewrite of the script,
    for the same reason that one is: forgetting the base class is the most
    likely thing for the model to do, and the fix is known. MotionScene is
    the narrated scene with the layer added, so a script written for
    VoiceoverScene runs unchanged on it.

    A MovingCameraScene or ThreeDScene becomes one too. If the script then
    reaches for a camera MotionScene does not have, the render fails and the
    repair loop shows the model the error - a known way back, where leaving
    the base alone would quietly ship a video without the layer.
    """
    if not script.strip():
        return script

    script = _ANY_SCENE_BASE_RE.sub(r"\1MotionScene\2", script)

    if re.search(r"^from anyq_narration import [^\n]*\bMotionScene\b", script, re.MULTILINE):
        return script
    if _NARRATION_IMPORT_RE.search(script):
        return _NARRATION_IMPORT_RE.sub("from anyq_narration import MotionScene", script, count=1)

    lines = script.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().startswith("from manim import"):
            lines.insert(idx + 1, "from anyq_narration import MotionScene")
            return "\n".join(lines)
    return "from manim import *\nfrom anyq_narration import MotionScene\n\n" + script


def _inherits_motion_scene(script: str) -> bool:
    """Whether the scene the renderer will run is a MotionScene.

    The check the motion layer stands on: every scene class in the script
    subclasses MotionScene, there is at least one, and MotionScene is
    imported where the renderer provides it.
    """
    try:
        tree = ast.parse(script or "")
    except SyntaxError:
        return False

    imported = any(
        isinstance(node, ast.ImportFrom) and node.module == "anyq_narration"
        and any(alias.name == "MotionScene" and not alias.asname for alias in node.names)
        for node in tree.body
    )
    scenes = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
        if any(b.endswith("Scene") for b in bases):
            scenes.append(bases)
    return imported and bool(scenes) and all(bases == ["MotionScene"] for bases in scenes)


# Animations that take something off the screen, and animations that put
# something on it. Names only - the guard never needs to know what they do,
# only which direction they go.
_EXIT_ANIMS = frozenset({
    "FadeOut", "Unwrite", "Uncreate", "ShrinkToCenter", "RemoveTextLetterByLetter",
})
_ENTER_ANIMS = frozenset({
    "FadeIn", "Write", "Create", "DrawBorderThenFill", "GrowFromCenter",
    "GrowFromEdge", "GrowFromPoint", "GrowArrow", "SpinInFromNothing",
    "AddTextLetterByLetter", "ShowIncreasingSubsets",
})


def _anim_kind(node: ast.AST) -> str:
    """"exit", "enter" or "" for one argument of self.play(...)."""
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    name = func.id if isinstance(func, ast.Name) else (
        func.attr if isinstance(func, ast.Attribute) else ""
    )
    if name in _EXIT_ANIMS:
        return "exit"
    if name in _ENTER_ANIMS:
        return "enter"
    return ""


def _mentions_tracker_duration(node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Attribute) and n.attr == "duration"
        for n in ast.walk(node)
    )


def _play_calls(tree: ast.Module):
    """Every `self.play(...)` used as a statement, innermost last."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func = call.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "play"
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
        ):
            yield node, call


def _pace_animations(script: str, cap: float, exit_run_time: float) -> Tuple[str, bool]:
    """Make things happen one at a time, and at a normal speed.

    Two rewrites, both of them the same complaint from watching the videos:

    1. A `self.play(...)` that removes something AND adds something in the
       same call plays both at once. The old caption is still half on screen
       while the new one is already half drawn on top of it, and for the
       length of the animation the frame is two texts occupying one line. Such
       a call is split in two - what leaves goes first, then what arrives.

    2. `run_time=tracker.duration` stretches one animation across the whole
       spoken sentence. It is not needed: the voiceover block waits for its
       own audio when it exits, so the block lasts the right length whatever
       the animation did. Every such run_time is capped, which leaves the
       motion at a readable speed and the remainder as a still frame.

    Rewrites the source text of the affected statements only, rather than
    unparsing the module: the rest of the script - comments, spacing, the
    exact spelling of every spoken line - is left byte for byte as it was.
    """
    if not script.strip():
        return script, False
    try:
        tree = ast.parse(script)
    except SyntaxError:
        # Not our problem to report: the validator rejects it a step later
        # with a message about the actual syntax error.
        return script, False

    edits = []  # (start_offset, end_offset, replacement)
    lines = script.splitlines(keepends=True)
    starts = []
    running = 0
    for line in lines:
        starts.append(running)
        running += len(line)

    def offset(lineno: int, col: int) -> int:
        return starts[lineno - 1] + col

    for stmt, call in _play_calls(tree):
        if stmt.lineno is None or stmt.end_lineno is None:
            continue
        indent = " " * stmt.col_offset

        def src(node) -> str:
            return ast.get_source_segment(script, node) or ""

        kinds = [_anim_kind(a) for a in call.args]
        exits = [src(a) for a, k in zip(call.args, kinds, strict=True) if k == "exit"]
        rest = [src(a) for a, k in zip(call.args, kinds, strict=True) if k != "exit"]
        has_enter = "enter" in kinds

        # Keywords, with tracker-length run_times capped.
        keywords, capped_any = [], False
        for kw in call.keywords:
            value = src(kw.value)
            if kw.arg == "run_time" and _mentions_tracker_duration(kw.value):
                value = f"min({cap}, {value})"
                capped_any = True
            keywords.append(f"{kw.arg}={value}" if kw.arg else f"**{value}")

        split = bool(exits) and has_enter
        if not split and not capped_any:
            continue
        if any(not s for s in exits + rest):
            # get_source_segment could not place an argument; leave the
            # statement alone rather than rewriting it from a guess.
            continue

        # The replacement starts AT col_offset, so the statement's own
        # indentation is already in the text before it; only a second line
        # needs indenting.
        if split:
            first = f"self.play({', '.join(exits)}, run_time={exit_run_time})"
            second = f"{indent}self.play({', '.join(rest + keywords)})"
            replacement = f"{first}\n{second}"
        else:
            replacement = f"self.play({', '.join(rest + keywords)})"

        edits.append((
            offset(stmt.lineno, stmt.col_offset),
            offset(stmt.end_lineno, stmt.end_col_offset),
            replacement,
        ))

    if not edits:
        return script, False

    # Last first, so earlier offsets stay valid.
    out = script
    for start, end, replacement in sorted(edits, reverse=True):
        out = out[:start] + replacement + out[end:]

    try:
        ast.parse(out)
    except SyntaxError as e:
        # Never hand on a script this made worse - but never do it quietly
        # either, or the pacing simply stops happening and nothing says so.
        print(f"[pacing] rewrite produced invalid syntax, keeping the "
              f"original: {e}", flush=True)
        return script, False
    return out, True


# What a name was made as, for _morph_transitions: the class at the root of
# the expression it was last assigned from - MathTex(...).next_to(x) is a
# formula. Only these two kinds are ever morphed; Text is a caption and L2
# forbids morphing one sentence into another.
_FORMULA_CLASSES = frozenset({"MathTex", "Tex"})
_SHAPE_CLASSES = frozenset({
    "Circle", "Square", "Rectangle", "RoundedRectangle", "Triangle", "Polygon",
    "RegularPolygon", "Ellipse", "Dot", "Star", "Annulus", "Sector",
    "AnnularSector", "Arc", "Line", "Arrow", "DashedLine", "DoubleArrow",
    "Vector",
})


def _root_class(node: ast.AST) -> str:
    """`MathTex` for MathTex("a").scale(2).next_to(b): the call a chain starts from."""
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        node = node.func.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _kind_of(class_name: str) -> str:
    if class_name in _FORMULA_CLASSES:
        return "formula"
    if class_name in _SHAPE_CLASSES:
        return "shape"
    return ""


def _is_self_call(stmt: ast.stmt, *methods: str) -> bool:
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return False
    func = stmt.value.func
    return (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.value.id == "self" and (not methods or func.attr in methods))


def _anim_on_name(node: ast.AST) -> Tuple[str, str]:
    """("exit"|"enter", name) for FadeOut(x) / Write(x), else ("", "")."""
    kind = _anim_kind(node)
    if kind and isinstance(node, ast.Call) and len(node.args) == 1 \
            and isinstance(node.args[0], ast.Name):
        return kind, node.args[0].id
    return "", ""


def _statement_lists(tree: ast.AST):
    """Every block of statements: function bodies, with/for/if bodies."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
                yield stmts


def _is_exit_arg(node: ast.AST) -> bool:
    """FadeOut(x), or *[FadeOut(m) for m in self.mobjects]."""
    if isinstance(node, ast.Starred) and isinstance(node.value, (ast.ListComp, ast.GeneratorExp)):
        return _anim_kind(node.value.elt) == "exit"
    return _anim_kind(node) == "exit"


def _is_exit_play(stmt: ast.stmt) -> bool:
    return (_is_self_call(stmt, "play") and bool(stmt.value.args)
            and all(_is_exit_arg(a) for a in stmt.value.args))


def _exit_then_enter(stmts):
    """([exit plays], enter play): a departure, then an arrival.

    The departure is one play that only removes things, or several in a row
    - models clear the diagram, then the caption, in two calls, which is the
    same empty frame. Then, past nothing but plain statements such as the
    assignment that builds the next object, a play that brings something in.
    """
    i = 0
    while i < len(stmts):
        if not _is_exit_play(stmts[i]):
            i += 1
            continue
        exits, enter, j = [stmts[i]], None, i + 1
        while j < len(stmts):
            later = stmts[j]
            if _is_self_call(later, "play"):
                if _is_exit_play(later):
                    exits.append(later)
                    j += 1
                    continue
                if any(_anim_kind(a) == "enter" for a in later.value.args):
                    enter = later
                break
            if _is_self_call(later) or not isinstance(
                    later, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.Pass)):
                break
            j += 1
        if enter is not None:
            yield exits, enter
        i = j


def _morph_transitions(script: str) -> Tuple[str, int, int]:
    """Turn "fade the old one out, write the new one in" into a morph.

    Under the motion layer, L8 asks for formulas to change with
    TransformMatchingTex and shapes with ReplacementTransform rather than a
    fade to an empty frame and a fade back in. The model still writes the
    old pattern often - _pace_animations even produces it, by splitting a
    play that faded and wrote at once - so the plain cases are rewritten
    here:

        self.play(FadeOut(eq1), run_time=0.35)      self.play(TransformMatchingTex(eq1, eq2),
        eq2 = MathTex("a", "=", "F", "/", "m")  ->            run_time=0.8)
        self.play(Write(eq2), run_time=0.8)

    Only when it is certain to be the same thing as before plus motion: the
    old and the new object are plain names in the same block, both were last
    assigned from a formula (MathTex/Tex) or both from a shape, and the old
    one is not used again later - after a morph it is gone, and fading it in
    again would bring back a broken copy. Captions (Text) are never touched.

    Returns (script, morphs made, fade-to-empty changes left): the second
    count is how often the script still clears and redraws - several things
    faded out, then something new brought in - which this cannot fix without
    knowing what corresponds to what.
    """
    if not script.strip():
        return script, 0, 0
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return script, 0, 0

    lines = script.splitlines(keepends=True)
    starts, running = [], 0
    for line in lines:
        starts.append(running)
        running += len(line)

    def offset(lineno: int, col: int) -> int:
        return starts[lineno - 1] + col

    def src(node: ast.AST) -> str:
        return ast.get_source_segment(script, node) or ""

    # Assignments in source order, for "what was this name last made as".
    assignments = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            assignments.append((node.lineno, node.targets[0].id, _kind_of(_root_class(node.value))))
    assignments.sort()

    def kind_at(name: str, lineno: int) -> str:
        kind = ""
        for line_no, target, k in assignments:
            if line_no >= lineno:
                break
            if target == name:
                kind = k
        return kind

    # Every use of every name, to know whether the old object comes back.
    uses = sorted(
        (node.lineno, node.col_offset, node.id, isinstance(node.ctx, ast.Store))
        for node in ast.walk(tree) if isinstance(node, ast.Name)
    )

    def used_again(name: str, after: Tuple[int, int]) -> bool:
        for line_no, col, n, is_store in uses:
            if (line_no, col) <= after or n != name:
                continue
            return not is_store  # the next mention: a read brings it back
        return False

    edits = []  # (start, end, replacement)
    morphs = 0
    for stmts in _statement_lists(tree):
        for exit_stmts, enter_stmt in _exit_then_enter(stmts):
            enter_call = enter_stmt.value
            enters = []
            for arg in enter_call.args:
                kind, name = _anim_on_name(arg)
                if kind == "enter":
                    enters.append((arg, name, kind_at(name, enter_stmt.lineno)))
            end_of_enter = (enter_stmt.end_lineno, enter_stmt.end_col_offset)

            paired = {}
            for exit_stmt in exit_stmts:
                kept_exits = []
                for arg in exit_stmt.value.args:
                    kind, old = _anim_on_name(arg)
                    old_kind = kind_at(old, exit_stmt.lineno) if old else ""
                    match = None
                    if old_kind and not used_again(old, end_of_enter):
                        for enter_arg, new, new_kind in enters:
                            if id(enter_arg) not in paired and new_kind == old_kind \
                                    and new != old:
                                match = (enter_arg, new)
                                break
                    if match is None:
                        kept_exits.append(src(arg))
                        continue
                    enter_arg, new = match
                    verb = "TransformMatchingTex" if old_kind == "formula" else "ReplacementTransform"
                    paired[id(enter_arg)] = (enter_arg, f"{verb}({old}, {new})")

                if len(kept_exits) == len(exit_stmt.value.args):
                    continue  # nothing of this play became a morph
                start = offset(exit_stmt.lineno, exit_stmt.col_offset)
                end = offset(exit_stmt.end_lineno, exit_stmt.end_col_offset)
                if kept_exits:
                    keywords = [f"{kw.arg}={src(kw.value)}" if kw.arg else f"**{src(kw.value)}"
                                for kw in exit_stmt.value.keywords]
                    edits.append((start, end, f"self.play({', '.join(kept_exits + keywords)})"))
                else:
                    # The whole play became the morph: nothing is left of it.
                    # `pass` keeps the line a statement whatever surrounds it.
                    edits.append((start, end, "pass"))

            morphs += len(paired)
            for enter_arg, replacement in paired.values():
                edits.append((offset(enter_arg.lineno, enter_arg.col_offset),
                              offset(enter_arg.end_lineno, enter_arg.end_col_offset),
                              replacement))

    out = script
    for start, end, replacement in sorted(edits, reverse=True):
        out = out[:start] + replacement + out[end:]
    try:
        ast.parse(out)
    except SyntaxError as e:
        print(f"[morph] rewrite produced invalid syntax, keeping the original: {e}",
              flush=True)
        out, morphs = script, 0

    return out, morphs, _count_fade_clears(out)


_MORPH_ANIMS = frozenset({
    "Transform", "ReplacementTransform", "TransformMatchingTex",
    "TransformMatchingShapes", "TransformFromCopy", "FadeTransform",
    "FadeTransformPieces",
})


def _count_fade_clears(script: str) -> int:
    """How often the script fades several things out and then brings new
    ones in with nothing carried over - "everything out, everything in", the
    cut to an empty frame L8 forbids. A change of scene in which something
    morphs into its successor is not one, even if the rest fades."""
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return 0
    count = 0
    for stmts in _statement_lists(tree):
        for exit_stmts, enter_stmt in _exit_then_enter(stmts):
            args = [a for stmt in exit_stmts for a in stmt.value.args]
            if not (len(args) >= 2 or any(isinstance(a, ast.Starred) for a in args)):
                continue
            carried = any(
                isinstance(a, ast.Call) and isinstance(a.func, ast.Name)
                and a.func.id in _MORPH_ANIMS for a in enter_stmt.value.args)
            if not carried:
                count += 1
    return count


def _contains_latex_objects(script: str) -> bool:
    s = script or ""
    return ("Tex(" in s) or ("MathTex(" in s)


def _contains_forbidden_manim(script: str) -> bool:
    s = script or ""
    forbidden = ["Checkmark", "Exmark", "Cross", "wait_for_input", "input(", "breakpoint("]
    return any(tok in s for tok in forbidden)


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
# anyq_narration is ours, not the model's: it supplies the VoiceoverScene
# base class and is injected the same way the font directive is. It has no
# network code and reads only audio the agent already synthesised, so
# allowing the import does not widen what a generated script can reach.
_ALLOWED_IMPORT_MODULES = {"manim", "numpy", "math", "random", "typing",
                          "anyq_narration"}
_ALLOWED_DUNDER_ATTRS = {"__init__", "__name__"}
_FORBIDDEN_NAMES = {
    "eval", "exec", "open", "input", "breakpoint", "compile", "__import__",
    "globals", "locals", "vars", "memoryview", "exit", "quit", "help",
    "getattr", "setattr", "delattr", "socket", "requests", "os", "sys",
    "subprocess", "importlib", "ctypes",
    # Narration: the service decides which voice speaks and where the
    # audio comes from. A model-chosen voice would silently disagree with
    # the voice the cache key was computed from, and a model-chosen
    # service is model-written configuration of an outside call. Both are
    # set by anyq_narration instead.
    "set_speech_service",
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