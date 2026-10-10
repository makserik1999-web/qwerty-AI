"""The explanation a person reads, before anything is drawn.

Moved verbatim out of nodes.py.
"""

from typing import Any, Dict

from spoon_ai.schema import Message

from anyq.config import DOC_SNIPPET_MODE
from anyq.language import _language_name, _resolve_output_language
from anyq.llm_client import _llm_chat
from anyq.nodes.state import USER_CONTENT_NOTICE, ScienceVideoState, _wrap


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
                    USER_CONTENT_NOTICE
                    + "\n\n"
                    + _wrap("subject", subject)
                    + "\n\n"
                    + _wrap("user_input", q)
                    + (f"\n\n{_wrap('image_context', img_ctx)}" if img_ctx else "")
                ),
            ),
        ]
    )
    return {"educator_text": resp.content.strip(), "output_language": language}
