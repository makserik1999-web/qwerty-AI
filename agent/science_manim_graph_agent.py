"""
Science Manim Graph Agent - Generates educational videos using Manim.

This agent:
1. Analyzes user questions (optionally with images)
2. Classifies if the question is science/educational
3. Decides if a video is needed
4. Generates educator explanation + Manim script
5. Renders the video using MCP

The implementation lives in the anyq package. This module stays as the entry
point and re-exports the names other modules import from it - in particular
_detect_language and DEFAULT_OUTPUT_LANGUAGE, which agent_ws_client resolves
through here.
"""

from anyq.config import DEFAULT_OUTPUT_LANGUAGE  # noqa: F401 - re-exported
from anyq.graph import app, run_once  # noqa: F401 - re-exported
from anyq.language import _detect_language  # noqa: F401 - re-exported
from anyq.nodes import ScienceVideoState  # noqa: F401 - re-exported
from anyq.script_guard import _latex_toolchain_healthy  # noqa: F401 - re-exported


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

