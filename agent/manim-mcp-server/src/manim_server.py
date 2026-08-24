#!/usr/bin/env python3
"""
Minimal Manim MCP Server for executing Manim animations.
Uses the Model Context Protocol (MCP) to expose a tool for rendering Manim scripts.
"""

import asyncio
import os
import sys
import tempfile
import subprocess
import json
import uuid
import shutil
from pathlib import Path
from typing import Any

from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import Server
import mcp.server.stdio

# Output directory for rendered videos
OUTPUT_DIR = Path(os.getenv("MANIM_OUTPUT_DIR", "/app/manim-mcp-server/src/media/outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

server = Server("manim-mcp-server")


def run_manim_script(code: str, quality: str = "l") -> dict:
    """
    Execute a Manim script and return the path to the rendered video.
    
    Args:
        code: The Python Manim script to execute
        quality: Video quality - l (low 480p), m (medium 720p), h (high 1080p)
    
    Returns:
        dict with 'success', 'video_path', and 'error' keys
    """
    # Create a unique temporary file for the script
    script_id = str(uuid.uuid4())[:8]
    script_path = Path(tempfile.gettempdir()) / f"manim_script_{script_id}.py"
    
    try:
        # Write the script to a temporary file
        with open(script_path, "w") as f:
            f.write(code)
        
        # Find the Scene class name
        import re
        scene_match = re.search(r'class\s+(\w+)\s*\(\s*(?:Scene|ThreeDScene|MovingCameraScene|ZoomedScene)\s*\)', code)
        if not scene_match:
            return {
                "success": False,
                "video_path": None,
                "error": "No Scene class found in the script"
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
            scene_name
        ]
        
        # Run manim
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            env={**os.environ, "PATH": f"/usr/local/bin:/usr/bin:/bin:{os.environ.get('PATH', '')}"}
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "video_path": None,
                "error": f"Manim execution failed: {result.stderr}"
            }
        
        # Find the output video
        # Manim outputs to media_dir/videos/script_name/quality/scene_name.mp4
        script_stem = script_path.stem
        quality_dirs = {"l": "480p15", "m": "720p30", "h": "1080p60"}
        quality_dir = quality_dirs.get(quality, "480p15")
        
        expected_video = Path(media_dir) / "videos" / script_stem / quality_dir / f"{scene_name}.mp4"
        
        if expected_video.exists():
            # Move to outputs directory with unique name (use shutil.move for cross-device support)
            final_path = OUTPUT_DIR / f"{scene_name}_{script_id}.mp4"
            shutil.move(str(expected_video), str(final_path))
            
            return {
                "status": "ok",
                "success": True,
                "video_path": str(final_path),
                "error": None
            }
        
        # Try to find any MP4 in the media directory
        for mp4 in Path(media_dir).rglob("*.mp4"):
            if scene_name in mp4.name:
                final_path = OUTPUT_DIR / f"{scene_name}_{script_id}.mp4"
                shutil.move(str(mp4), str(final_path))
                return {
                    "status": "ok",
                    "success": True,
                    "video_path": str(final_path),
                    "error": None
                }
        
        return {
            "success": False,
            "video_path": None,
            "error": f"Video file not found. Manim output: {result.stdout}"
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "video_path": None,
            "error": "Manim execution timed out (5 minute limit)"
        }
    except Exception as e:
        return {
            "success": False,
            "video_path": None,
            "error": f"Execution error: {str(e)}"
        }
    finally:
        # Clean up temporary script
        if script_path.exists():
            script_path.unlink()


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
    
    # Run in a thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_manim_script, code, quality)
    
    return [types.TextContent(type="text", text=json.dumps(result))]


async def main():
    """Run the MCP server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        init_options = InitializationOptions(
            server_name="manim-mcp-server",
            server_version="1.0.0",
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

