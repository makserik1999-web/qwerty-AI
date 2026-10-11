"""What people actually made, kept for the admin statistics.

generation_events cannot answer that: it is the quota's counter, given back
when a render fails and expired after two days. Assessments, plans and chats
can be deleted by their owners. So nothing recorded how much the product is
used - this does, one small document per finished action:

    kind        explanation | assessment | lesson_plan | quiz_draft
    ok          False only for an explanation the agent failed
    video       an explanation that came with a video
    cached      an explanation answered from the library, not generated

Never the question text: the statistics need counts, not what was asked.

Writing here must never fail the request it describes, so `log` swallows its
own errors.
"""

from datetime import datetime, timezone

from app.db import db

KINDS = ("explanation", "assessment", "lesson_plan", "quiz_draft")


async def log(user_id: str, kind: str, *, ok: bool = True, video: bool = False,
              cached: bool = False) -> None:
    try:
        await db.db.usage_log.insert_one(
            {
                "user_id": str(user_id),
                "kind": kind,
                "ok": bool(ok),
                "video": bool(video),
                "cached": bool(cached),
                "at": datetime.now(timezone.utc),
            }
        )
    except Exception as e:  # noqa: BLE001 - statistics never break a request
        print(f"usage log write failed: {type(e).__name__}: {e}")
