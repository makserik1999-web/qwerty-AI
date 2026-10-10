"""What a session's answers add up to, for the teacher.

Three readings of the same answers. Per student: who needs a word after the
lesson. Per question: which question the class could not do. And the one a
teacher cannot get from a mark book - per WRONG ANSWER: when a third of the
class picks the same wrong option, that is not thirty separate mistakes but
one misunderstanding, and the option's note says which.
"""

from collections import Counter
from statistics import mean, median
from typing import Any, Dict, List, Optional

from quiz_service.db import aware, iso
from quiz_service.logic import ranked
from quiz_service.questions import _norm

# A wrong option counts as a shared misconception when at least this share of
# the students who answered chose it, and at least this many did - two out of
# three is a coincidence, not a pattern.
MISCONCEPTION_SHARE = 0.25
MISCONCEPTION_MIN = 3


def _duration(player: Dict[str, Any]) -> Optional[float]:
    start = aware(player.get("started_at"))
    end = aware(player.get("finished_at"))
    if not start or not end:
        return None
    return max(0.0, (end - start).total_seconds())


def _value(answer: Optional[Dict[str, Any]], question: Dict[str, Any]) -> str:
    if not answer:
        return ""
    if question["type"] == "choice":
        for option in question.get("options") or []:
            if option["id"] == answer.get("option"):
                return option.get("text", "")
        return ""
    return answer.get("text") or ""


def build(session: Dict[str, Any], players: List[Dict[str, Any]]) -> Dict[str, Any]:
    questions = session.get("questions") or []
    active = ranked([p for p in players if not p.get("kicked")])

    people = []
    for place, player in enumerate(active, start=1):
        answers = player.get("answers") or {}
        total = len(player.get("order") or []) or len(questions)
        correct = int(player.get("correct") or 0)
        people.append({
            "id": str(player["_id"]),
            "name": player.get("name", ""),
            "rank": place,
            "score": int(player.get("score") or 0),
            "correct": correct,
            "answered": int(player.get("answered") or 0),
            "total": total,
            "percent": round(100 * correct / total) if total else 0,
            "durationSec": _duration(player),
            "finished": bool(player.get("finished_at")),
            "bestStreak": int(player.get("best_streak") or 0),
            # In the quiz's own order, not the player's shuffled one, so the
            # columns of a results table line up.
            "answers": [
                {
                    "questionId": q["id"],
                    "correct": bool(answers[q["id"]].get("correct")) if q["id"] in answers else None,
                    "value": _value(answers.get(q["id"]), q),
                    "skipped": bool((answers.get(q["id"]) or {}).get("skipped")),
                }
                for q in questions
            ],
        })

    items = []
    insights = []
    for index, question in enumerate(questions):
        qid = question["id"]
        given = [p["answers"][qid] for p in active if qid in (p.get("answers") or {})]
        answered = len(given)
        right = sum(1 for a in given if a.get("correct"))
        times = [int(a.get("ms") or 0) for a in given if a.get("ms")]
        item: Dict[str, Any] = {
            "id": qid,
            "index": index,
            "type": question["type"],
            "text": question.get("text", ""),
            "explanation": question.get("explanation", ""),
            "topic": question.get("topic", ""),
            "answered": answered,
            "correct": right,
            "rate": round(right / answered, 3) if answered else None,
            "skipped": sum(1 for a in given if a.get("skipped")),
            "medianMs": int(median(times)) if times else None,
        }

        if question["type"] == "choice":
            options = []
            for option in question.get("options") or []:
                count = sum(1 for a in given if a.get("option") == option["id"])
                is_right = option["id"] == question.get("correct")
                options.append({
                    "id": option["id"],
                    "text": option.get("text", ""),
                    "note": option.get("note", ""),
                    "correct": is_right,
                    "count": count,
                })
                if not is_right and answered and count >= MISCONCEPTION_MIN \
                        and count / answered >= MISCONCEPTION_SHARE:
                    insights.append({
                        "questionId": qid,
                        "questionIndex": index,
                        "questionText": question.get("text", ""),
                        "answer": option.get("text", ""),
                        "note": option.get("note", ""),
                        "count": count,
                        "share": round(count / answered, 3),
                    })
            item["options"] = options
        else:
            wrong = Counter(
                _norm(a.get("text") or "") for a in given
                if not a.get("correct") and not a.get("skipped") and (a.get("text") or "").strip()
            )
            item["answer"] = question.get("answer", "")
            item["unit"] = question.get("unit", "")
            item["accept"] = question.get("accept", [])
            item["wrongAnswers"] = [
                {"text": text, "count": count} for text, count in wrong.most_common(5)
            ]
            for text, count in wrong.most_common(1):
                if answered and count >= MISCONCEPTION_MIN and count / answered >= MISCONCEPTION_SHARE:
                    insights.append({
                        "questionId": qid,
                        "questionIndex": index,
                        "questionText": question.get("text", ""),
                        "answer": text,
                        "note": "",
                        "count": count,
                        "share": round(count / answered, 3),
                    })
        items.append(item)

    rated = [i for i in items if i["rate"] is not None]
    durations = [p["durationSec"] for p in people if p["durationSec"] is not None]
    started = [p for p in people if p["answered"]]
    insights.sort(key=lambda i: (-i["share"], i["questionIndex"]))

    return {
        "session": {
            "id": str(session["_id"]),
            "quizId": session.get("quiz_id", ""),
            "title": session.get("title", ""),
            "code": session.get("code", ""),
            "status": session.get("status"),
            "classLabel": session.get("class_label", ""),
            "subject": session.get("subject", "other"),
            "grade": session.get("grade", 0),
            "lang": session.get("lang", "kk"),
            "settings": session.get("settings") or {},
            "createdAt": iso(session.get("created_at")),
            "startsAt": iso(session.get("starts_at")),
            "endedAt": iso(session.get("ended_at")),
        },
        "summary": {
            "players": len(people),
            "finished": sum(1 for p in people if p["finished"]),
            "questionCount": len(questions),
            "averagePercent": round(mean(p["percent"] for p in started)) if started else None,
            "medianDurationSec": round(median(durations)) if durations else None,
            "hardest": min(rated, key=lambda i: (i["rate"], i["index"]))["id"] if rated else None,
            "easiest": max(rated, key=lambda i: (i["rate"], -i["index"]))["id"] if rated else None,
        },
        "questions": items,
        "players": people,
        "insights": insights[:6],
    }
