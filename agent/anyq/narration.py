"""Turning the spoken lines of a script into audio, before anything renders.

This is the half of narration that holds the Azure key. The other half lives
in manim-mcp-server/src/anyq_narration.py and only reads files, because the
render subprocess executes model-written code and is given no credentials -
see the safe_env comment in manim_server.run_manim_script.

So the order is: validate the script, read the lines out of it, synthesise
them here, hand the renderer a directory. The renderer cannot ask for a line
that was not synthesised, which is why extraction reads the AST rather than
trusting the model to also list what it intends to say.

Failure degrades to silence rather than to no video. A student who asked a
question and got a silent animation has been served; one who got an error has
not, and Azure's free tier runs out at half a million characters a month.
"""

from __future__ import annotations

import ast
import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from anyq.config import (
    _LLM_RETRIES,
    _LLM_RETRY_BASE_DELAY,
    AZURE_SPEECH_KEY,
    AZURE_SPEECH_REGION,
    NARRATION_ENABLED,
    NARRATION_RATE,
    NARRATION_VOICE,
)

# The renderer's copy of the hashing rule. Imported rather than re-implemented:
# if the two ever disagree every lookup misses and every video goes silent,
# which is a failure nobody would see in a log.
_SHIM_DIR = Path(__file__).resolve().parents[1] / "manim-mcp-server" / "src"


def _shim():
    import sys

    if str(_SHIM_DIR) not in sys.path:
        sys.path.insert(0, str(_SHIM_DIR))
    import anyq_narration

    return anyq_narration


# Which Azure voice speaks. The product's choice is between the two Kazakh
# voices - those are the ones anyone here can judge - so the setting names
# them, and the other languages follow with a voice of the same gender.
_VOICES: Dict[Tuple[str, str], str] = {
    ("kk", "aigul"): "kk-KZ-AigulNeural",
    ("kk", "daulet"): "kk-KZ-DauletNeural",
    ("ru", "aigul"): "ru-RU-SvetlanaNeural",
    ("ru", "daulet"): "ru-RU-DmitryNeural",
    ("en", "aigul"): "en-US-AriaNeural",
    ("en", "daulet"): "en-US-GuyNeural",
}
_LOCALES = {"kk": "kk-KZ", "ru": "ru-RU", "en": "en-US"}

# Azure charges by character and the free tier is 500k a month. A script that
# somehow asked for a novel would burn it in one request, so cap the whole
# job rather than trusting the prompt's line-length guidance.
MAX_NARRATION_CHARS = 4000


def voice_for(language: str, choice: str = "") -> str:
    """The Azure voice name, or "" when this language has none."""
    return _VOICES.get((language or "", (choice or NARRATION_VOICE).lower()), "")


def extract_lines(script: str) -> List[str]:
    """Every string the script will speak, in order, without repeats.

    Read from the AST rather than from anything the model tells us separately:
    the manifest has to cover exactly what `self.voiceover(text=...)` will ask
    for, and a second list could disagree with the code.
    """
    try:
        tree = ast.parse(script or "")
    except SyntaxError:
        return []

    found: List[str] = []
    seen = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "voiceover"):
            continue
        text = None
        for kw in node.keywords:
            if kw.arg == "text" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                text = kw.value.value
        if text is None and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                text = first.value
        if not text or not text.strip():
            continue
        key = _shim().normalise_line(text)
        if key in seen:
            continue
        seen.add(key)
        found.append(text)
    return found


def _ssml(text: str, voice: str, locale: str) -> str:
    escaped = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (
        f"<speak version='1.0' xml:lang='{locale}'>"
        f"<voice name='{voice}'>"
        # Slower than default: this is a school explanation, not a news read.
        f"<prosody rate='{NARRATION_RATE}'>{escaped}</prosody>"
        f"</voice></speak>"
    )


def _synthesise_sync(text: str, voice: str, locale: str) -> bytes:
    url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
        "User-Agent": "anyq",
    }
    body = _ssml(text, voice, locale).encode("utf-8")
    last: Optional[Exception] = None
    for attempt in range(_LLM_RETRIES + 1):
        try:
            r = httpx.post(url, headers=headers, content=body, timeout=60.0)
            if r.status_code == 200:
                return r.content
            # 429 is the free tier running out; retrying will not conjure quota,
            # but a burst limit clears, so treat both as transient once.
            raise RuntimeError(f"azure tts {r.status_code}: {r.text[:160]}")
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last = exc
            if attempt >= _LLM_RETRIES:
                raise
            time.sleep(_LLM_RETRY_BASE_DELAY * (2 ** attempt))
    raise last if last else RuntimeError("unreachable")


async def prepare(script: str, language: str, voice_choice: str = "") -> str:
    """Synthesise the script's lines. Returns a manifest path, or "".

    An empty return renders the animation silently, and every failure path
    returns it: no key, no voice for the language, an over-long script, a
    refused request. The caller does not branch on why.
    """
    if not NARRATION_ENABLED or not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        # Said once per request rather than assumed to be obvious: a silent
        # video is not distinguishable from a spoken one in any log line, and
        # somebody debugging one has to be told which of these it was.
        print("[narration] disabled or unconfigured; rendering silent", flush=True)
        return ""

    voice = voice_for(language, voice_choice)
    locale = _LOCALES.get(language or "", "")
    if not voice or not locale:
        print(f"[narration] no voice for language {language!r}; rendering silent",
              flush=True)
        return ""

    lines = extract_lines(script)
    if not lines:
        # The loudest of the quiet paths, because it is the one that is a
        # surprise. Narration was asked for and the script says nothing - the
        # model wrote no voiceover blocks, or wrote them in a form the manifest
        # cannot read (an f-string or a variable rather than a literal). The
        # video comes out silent AND its length stops being controllable,
        # since the length follows the speech. That produced a "medium" video
        # of 35 seconds with nothing anywhere to explain it.
        blocks = script.count("self.voiceover")
        print(f"[narration] nothing to speak ({blocks} voiceover blocks in the "
              f"script); rendering silent", flush=True)
        return ""

    total = sum(len(line) for line in lines)
    if total > MAX_NARRATION_CHARS:
        print(f"[narration] {total} characters exceeds the {MAX_NARRATION_CHARS} "
              f"cap; rendering silent", flush=True)
        return ""

    work = Path(tempfile.mkdtemp(prefix="anyq-narration-"))
    index: Dict[str, str] = {}
    started = time.monotonic()
    try:
        # Concurrently: the lines are independent and a dozen sequential round
        # trips to Sweden is most of a minute the student spends waiting.
        audio = await asyncio.gather(*[
            asyncio.to_thread(_synthesise_sync, line, voice, locale) for line in lines
        ])
    except Exception as exc:  # noqa: BLE001 - narration is never fatal
        shutil.rmtree(work, ignore_errors=True)
        print(f"[narration] failed, rendering silent: "
              f"{type(exc).__name__}: {str(exc)[-200:]}", flush=True)
        return ""

    shim = _shim()
    for i, (line, data) in enumerate(zip(lines, audio, strict=True)):
        name = f"line{i:02d}.mp3"
        (work / name).write_bytes(data)
        index[shim.narration_key(line)] = name

    manifest = work / "manifest.json"
    manifest.write_text(
        json.dumps({"voice": voice, "language": language, "lines": index},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[narration] {len(lines)} lines, {total} chars, {voice} "
          f"in {time.monotonic() - started:.1f}s", flush=True)
    return str(manifest)


def cleanup(manifest_path: str) -> None:
    """Remove a directory prepare() made. Safe to call with ""."""
    if not manifest_path:
        return
    try:
        shutil.rmtree(Path(manifest_path).parent, ignore_errors=True)
    except Exception:  # noqa: BLE001 - cleanup must never break a request
        pass
