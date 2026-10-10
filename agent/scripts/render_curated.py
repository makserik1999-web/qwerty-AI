"""Render one curated script inside the agent container.

Reads {"script": "...", "quality": "h"} on stdin, prints one JSON object on
stdout. Deliberately dumb: it does not know what a topic or a language is, it
renders the text it is handed. Composing that text is the host driver's job
(scripts/seed_library.py), which is where the content tree lives.

It goes through the same safety validator and the same font handling as a
generated script, so a curated video is produced by exactly the path a live
one is - no second renderer to keep in sync.

Usage (from the repo root):
    echo '{"script": "...", "quality": "h"}' \
      | docker compose exec -T agent python /app/scripts/render_curated.py
"""

import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/manim-mcp-server/src")

from anyq.script_guard import _ensure_unicode_font  # noqa: E402
from manim_server import run_manim_script  # noqa: E402


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        json.dump({"success": False, "error": f"bad request json: {exc}"}, sys.stdout)
        return 2

    script = (request.get("script") or "").strip()
    if not script:
        json.dump({"success": False, "error": "empty script"}, sys.stdout)
        return 2

    quality = request.get("quality") or "h"
    if quality not in ("l", "m", "h"):
        json.dump({"success": False, "error": f"bad quality {quality!r}"}, sys.stdout)
        return 2

    # Kazakh needs a font with the extra Cyrillic letters; the live pipeline
    # forces one the same way rather than trusting the script to ask for it.
    script = _ensure_unicode_font(script)

    result = run_manim_script(script, quality=quality)

    video_path = result.get("video_path") or ""
    json.dump(
        {
            "success": bool(result.get("success")),
            "video_path": video_path,
            # The backend serves the media volume at /media/<filename>.
            "video_url": f"/media/{video_path.rsplit('/', 1)[-1]}" if video_path else "",
            "error": result.get("error") or "",
        },
        sys.stdout,
        ensure_ascii=False,
    )
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
