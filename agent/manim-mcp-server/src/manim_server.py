#!/usr/bin/env python3
"""
Minimal Manim MCP Server for executing Manim animations.
Uses the Model Context Protocol (MCP) to expose a tool for rendering Manim scripts.

Security model (defense in depth):
- the script is AST-validated (import whitelist, no module-level side effects,
  no dangerous builtins) BEFORE it is executed - a rejected script is never run;
- the subprocess runs with a minimal environment (no API keys / secrets),
  as a new process group so a timeout kills manim AND its children (ffmpeg);
- container isolation (non-root user, no capabilities, read-only rootfs,
  resource limits) is configured in the Dockerfile / docker-compose.
"""

import ast
import asyncio
import json
import os
import re
import signal
import subprocess
import tempfile
import uuid
from pathlib import Path

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from mcp.server.models import InitializationOptions

# Output directory for rendered videos (set explicitly by compose).
OUTPUT_DIR = Path(os.getenv("MANIM_OUTPUT_DIR", "/app/manim-mcp-server/src/media/outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Hard per-render cap (seconds). The agent's own deadline is larger; this is the
# inner safety net for a single manim run.
MANIM_RENDER_TIMEOUT_SEC = float(os.getenv("MANIM_RENDER_TIMEOUT_SEC", "300"))

server = Server("manim-mcp-server")


# ================= AST safety validator (self-contained copy) =================
# The agent runs the same validator upstream; this copy makes the MCP server
# safe on its own, even if it is ever called directly with attacker input.
_ALLOWED_IMPORT_MODULES = {"manim", "numpy", "math", "random", "typing"}
_ALLOWED_DUNDER_ATTRS = {"__init__", "__name__"}
_FORBIDDEN_NAMES = {
    "eval", "exec", "open", "input", "breakpoint", "compile", "__import__",
    "globals", "locals", "vars", "memoryview", "exit", "quit", "help",
    "getattr", "setattr", "delattr", "socket", "requests", "os", "sys",
    "subprocess", "importlib", "ctypes",
}


def _import_module_ok(node: ast.AST) -> str:
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
            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                continue  # docstring
            if (
                isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and getattr(stmt.value.func, "attr", "") == "set_default"
                and isinstance(stmt.value.func.value, ast.Name)
                and stmt.value.func.value.id == "Text"
            ):
                continue  # Text.set_default(font="...")
            return "module-level code is not allowed (only imports and class definitions)"
        if isinstance(stmt, ast.Pass):
            continue
        return f"module-level statement of type {type(stmt).__name__} is not allowed"
    return ""


def _validate_all_nodes(tree: ast.Module) -> str:
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
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and str(k.value).startswith("__"):
                    return f"forbidden string key {k.value!r}"
        elif isinstance(node, ast.keyword):
            if node.arg and node.arg.startswith("__"):
                return f"forbidden keyword argument {node.arg!r}"
    return ""


def validate_manim_script(script: str) -> tuple:
    """Returns (ok: bool, reason: str). A rejected script MUST NOT be run."""
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


def run_manim_script(code: str, quality: str = "l") -> dict:
    """
    Execute a Manim script and return the path to the rendered video.

    Args:
        code: The Python Manim script to execute
        quality: Video quality - l (low 480p), m (medium 720p), h (high 1080p)

    Returns:
        dict with 'success', 'video_path', and 'error' keys
    """
    # Security gate: never execute a rejected script.
    ok, reason = validate_manim_script(code or "")
    if not ok:
        return {
            "success": False,
            "status": "error",
            "video_path": None,
            "error": f"Script rejected by the safety validator: {reason}",
        }

    # Create a unique temporary file for the script
    script_id = str(uuid.uuid4())[:8]
    script_path = Path(tempfile.gettempdir()) / f"manim_script_{script_id}.py"

    try:
        # Write the script to a temporary file
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        # Find the Scene class name
        scene_match = re.search(
            r'class\s+(\w+)\s*\(\s*(?:Scene|ThreeDScene|MovingCameraScene|ZoomedScene)\s*\)',
            code,
        )
        if not scene_match:
            return {
                "success": False,
                "status": "error",
                "video_path": None,
                "error": "No Scene class found in the script",
            }

        scene_name = scene_match.group(1)

        # Determine manim executable
        manim_exe = os.getenv("MANIM_EXECUTABLE", "manim")

        # Build the command
        quality_flag = f"-q{quality}"
        media_dir = str(OUTPUT_DIR.parent)

        cmd = [
            manim_exe,
            quality_flag,
            "--media_dir", media_dir,
            str(script_path),
            scene_name,
        ]

        # Minimal environment: NO secrets, NO API keys, nothing the script could
        # exfiltrate. Only what manim itself needs to run.
        safe_env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": "/tmp",
            "TMPDIR": tempfile.gettempdir(),
            "MANIM_OUTPUT_DIR": str(OUTPUT_DIR),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        }

        # Run manim as a new process group so a timeout can kill the whole tree
        # (manim + ffmpeg + anything the script spawned) - no orphans.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=safe_env,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=MANIM_RENDER_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass
            try:
                out, err = proc.communicate(timeout=10)
            except Exception:
                out, err = "", ""
            return {
                "success": False,
                "status": "error",
                "video_path": None,
                "error": "Manim execution timed out",
            }

        if proc.returncode != 0:
            tail = (err or "")[-1500:]
            return {
                "success": False,
                "status": "error",
                "video_path": None,
                "error": f"Manim execution failed: {tail}",
            }

        # Find the output video (only the output the current run produced).
        script_stem = script_path.stem
        quality_dirs = {"l": "480p15", "m": "720p30", "h": "1080p60"}
        quality_dir = quality_dirs.get(quality, "480p15")

        expected_video = Path(media_dir) / "videos" / script_stem / quality_dir / f"{scene_name}.mp4"

        if expected_video.exists():
            # Move to outputs directory with unique name (use shutil.move for cross-device support)
            import shutil

            final_path = OUTPUT_DIR / f"{scene_name}_{script_id}.mp4"
            shutil.move(str(expected_video), str(final_path))

            return {
                "status": "ok",
                "success": True,
                "video_path": str(final_path),
                "error": None,
            }

        return {
            "success": False,
            "status": "error",
            "video_path": None,
            "error": f"Video file not found. Manim output: {out[-800:] if out else ''}",
        }

    except Exception as e:
        return {
            "success": False,
            "status": "error",
            "video_path": None,
            "error": f"Execution error: {type(e).__name__}: {str(e)[-500:]}",
        }
    finally:
        # Clean up temporary script
        if script_path.exists():
            try:
                script_path.unlink()
            except Exception:
                pass


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="execute_manim_code",
            description="Execute a Manim Python script to render an animation video",
            inputSchema={
                "type": "object",
                "properties": {
                    "manim_code": {
                        "type": "string",
                        "description": "The complete Manim Python script to execute. Must include a Scene class."
                    },
                    "quality": {
                        "type": "string",
                        "enum": ["l", "m", "h"],
                        "default": "l",
                        "description": "Video quality: l=480p, m=720p, h=1080p"
                    }
                },
                "required": ["manim_code"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls."""
    if name != "execute_manim_code":
        raise ValueError(f"Unknown tool: {name}")

    if not arguments or "manim_code" not in arguments:
        raise ValueError("manim_code is required")

    code = arguments["manim_code"]
    quality = arguments.get("quality", "l")

    if quality not in ("l", "m", "h"):
        raise ValueError("quality must be one of l, m, h")

    # Run in a thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_manim_script, code, quality)

    return [types.TextContent(type="text", text=json.dumps(result))]


async def main():
    """Run the MCP server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        init_options = InitializationOptions(
            server_name="manim-mcp-server",
            server_version="1.1.0",
            capabilities=types.ServerCapabilities(
                tools=types.ToolsCapability(listChanged=False)
            )
        )
        await server.run(
            read_stream,
            write_stream,
            init_options
        )


if __name__ == "__main__":
    asyncio.run(main())