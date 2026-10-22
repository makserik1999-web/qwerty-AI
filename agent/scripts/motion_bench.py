"""Before/after benchmark of the motion layer on real questions.

Runs each question through the whole agent pipeline - the same
process_request the websocket worker calls: intent, explanation, script,
guards, narration, render - and records what the motion layer is about: how
long the render took (render_seconds) and how much of the video stands still
(static_share, see anyq/motion_metric.py). One mode per process, because
MOTION_LAYER is read at import:

    MOTION_LAYER=0 MOTION_METRIC=1 python scripts/motion_bench.py before questions.txt /bench
    MOTION_LAYER=1                 python scripts/motion_bench.py after  questions.txt /bench

Inside the agent image, with the repo's agent/ mounted at /app and the keys
in the environment (docker run --env-file .env ...). Each question costs the
same model calls and Azure characters as a real request. Writes
/bench/<mode>/NN.mp4 and NN.py (the script that was rendered) and appends one
JSON line per question to /bench/<mode>.jsonl.

questions.txt: one question per line; blank lines and lines starting with #
are skipped.
"""

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The rendered script is not part of the answer, so it is caught on its way
# to the renderer - before the graph is built, which is when the graph takes
# its reference to render_video.
import anyq.render as _render  # noqa: E402

_scripts = []
_render_video = _render.render_video


async def _keep_script(state):
    _scripts.append(state.get("manim_script") or "")
    return await _render_video(state)


_render.render_video = _keep_script

import agent_ws_client  # noqa: E402
from anyq.config import ANYQ_TELEMETRY_PATH, MOTION_LAYER  # noqa: E402

EFFORT = os.getenv("BENCH_EFFORT", "low")        # the production profile
LENGTH = os.getenv("BENCH_LENGTH", "medium")


def _telemetry_for(request_id):
    try:
        lines = Path(ANYQ_TELEMETRY_PATH).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("request_id") == request_id:
            return entry
    return {}


async def main(mode, questions_path, out_dir):
    questions = [q.strip() for q in Path(questions_path).read_text(encoding="utf-8").splitlines()
                 if q.strip() and not q.lstrip().startswith("#")]
    target = Path(out_dir) / mode
    target.mkdir(parents=True, exist_ok=True)
    results = Path(out_dir) / f"{mode}.jsonl"
    print(f"[bench] {mode}: {len(questions)} questions, motion_layer={MOTION_LAYER}, "
          f"effort={EFFORT}, length={LENGTH}", flush=True)

    for i, question in enumerate(questions, 1):
        request_id = f"bench-{mode}-{i:02d}"
        _scripts.clear()
        started = time.monotonic()
        reply = await agent_ws_client.process_request({
            "request_id": request_id, "text": question, "narration": True,
            "effort": EFFORT, "video_length": LENGTH,
        })
        took = time.monotonic() - started
        tel = _telemetry_for(request_id)
        video = reply.get("video_path") or ""
        row = {
            "n": i, "question": question, "mode": mode,
            "ok": bool(video), "status": reply.get("status"), "error": reply.get("error", ""),
            "duration": reply.get("duration"), "has_audio": reply.get("has_audio"),
            "total_seconds": round(took, 1),
            "render_seconds": tel.get("render_seconds"),
            "render_attempt": tel.get("render_attempt"),
            "static_seconds": tel.get("static_seconds"),
            "static_share": tel.get("static_share"),
            "transitions_morphed": tel.get("transitions_morphed"),
            "fade_clears_left": tel.get("fade_clears_left"),
            "read_formula_calls": sum(s.count("self.read_formula(") for s in _scripts[-1:]),
        }
        if video and os.path.exists(video):
            shutil.copyfile(video, target / f"{i:02d}.mp4")
        if _scripts:
            (target / f"{i:02d}.py").write_text(_scripts[-1], encoding="utf-8")
        with results.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[bench] {i:02d} {'ok ' if row['ok'] else 'FAIL'} {took:6.1f}s "
              f"render={row['render_seconds']} still={row['static_share']} "
              f"len={row['duration']} | {question[:50]}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
