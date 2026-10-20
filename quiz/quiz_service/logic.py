"""The rules of a session: whose clock is running, what is asked next, what
an answer is worth, and what each side is allowed to see.

Pure functions over the stored documents, so every rule here is testable
without a database and the API modules only fetch, call and write.

TIME is the server's. A phone's clock can be minutes out, so every state
carries `serverNow` and the phone works out its own offset; a deadline the
phone computed from its own clock would let anybody buy time by changing it.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from quiz_service.config import ANSWER_GRACE_SEC
from quiz_service.db import aware, iso
from quiz_service.questions import student_view

# A right answer is worth 100, and a run of them is worth a little more each
# time - capped, so one long streak cannot outscore a better-answered quiz.
BASE_POINTS = 100
STREAK_STEP = 10
STREAK_CAP = 50


def score(correct: bool, streak_before: int) -> Tuple[int, int]:
    """(points for this answer, streak after it)."""
    if not correct:
        return 0, 0
    streak = streak_before + 1
    return BASE_POINTS + min(STREAK_CAP, (streak - 1) * STREAK_STEP), streak


def questions_by_id(session: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {q["id"]: q for q in session.get("questions") or []}


def deadline(session: Dict[str, Any], player: Dict[str, Any]) -> Optional[datetime]:
    minutes = (session.get("settings") or {}).get("timeLimitMin") or 0
    started = aware(player.get("started_at"))
    if not minutes or not started:
        return None
    return started + timedelta(minutes=minutes)


def current_question(session: Dict[str, Any], player: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The next question in this player's order that they have not answered.

    One at a time and in order: the phone is only ever told about this one,
    so nothing ahead of it can be looked at or skipped to.
    """
    answered = player.get("answers") or {}
    by_id = questions_by_id(session)
    for qid in player.get("order") or []:
        if qid not in answered and qid in by_id:
            return by_id[qid]
    return None


def status(session: Dict[str, Any], player: Dict[str, Any], at: datetime) -> str:
    if player.get("kicked"):
        return "kicked"
    if player.get("finished_at"):
        return "finished"
    if session.get("status") == "ended":
        return "finished"
    started = aware(player.get("started_at"))
    if session.get("status") == "lobby" or not started:
        return "lobby"
    if at < started:
        return "countdown"
    limit = deadline(session, player)
    if limit and at > limit + timedelta(seconds=ANSWER_GRACE_SEC):
        return "finished"
    if current_question(session, player) is None:
        return "finished"
    return "playing"


def ranked(players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Best first: score, then the quicker finish, then whoever joined first."""

    def duration(player: Dict[str, Any]) -> float:
        start = aware(player.get("started_at"))
        end = aware(player.get("finished_at")) or aware(player.get("last_answer_at"))
        if not start or not end:
            return float("inf")
        return (end - start).total_seconds()

    return sorted(
        (p for p in players if not p.get("kicked")),
        key=lambda p: (-int(p.get("score") or 0), duration(p), aware(p.get("joined_at"))),
    )


def rank_of(players: List[Dict[str, Any]], player_id: Any) -> Tuple[int, int]:
    order = ranked(players)
    for index, item in enumerate(order):
        if item["_id"] == player_id:
            return index + 1, len(order)
    return 0, len(order)


def player_state(session: Dict[str, Any], player: Dict[str, Any], at: datetime,
                 players: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Everything a student's phone is allowed to know, and nothing more."""
    settings = session.get("settings") or {}
    total = len(player.get("order") or [])
    state = status(session, player, at)
    limit = deadline(session, player)

    out: Dict[str, Any] = {
        "status": state,
        "sessionStatus": session.get("status"),
        "title": session.get("title", ""),
        "questionCount": total,
        "showResults": bool(settings.get("showResults", True)),
        "leaderboard": bool(settings.get("leaderboard", True)),
        "serverNow": iso(at),
        "startsAt": iso(player.get("started_at")),
        "deadline": iso(limit),
        "player": {"id": str(player["_id"]), "name": player.get("name", "")},
        "progress": {
            "answered": int(player.get("answered") or 0),
            "total": total,
            "score": int(player.get("score") or 0),
            "correct": int(player.get("correct") or 0),
            "streak": int(player.get("streak") or 0),
        },
        "question": None,
        "result": None,
    }

    if state == "playing":
        question = current_question(session, player)
        if question is not None:
            answered = int(player.get("answered") or 0)
            order = (player.get("option_orders") or {}).get(question["id"])
            out["question"] = student_view(question, order, answered, total)

    if state == "finished":
        result: Dict[str, Any] = {
            "answered": int(player.get("answered") or 0),
            "total": total,
            "waiting": session.get("status") != "ended",
        }
        if settings.get("showResults", True):
            answers = player.get("answers") or {}
            result.update({
                "score": int(player.get("score") or 0),
                "correct": int(player.get("correct") or 0),
                "bestStreak": int(player.get("best_streak") or 0),
                "answers": [
                    {"questionId": qid,
                     "correct": bool((answers.get(qid) or {}).get("correct"))
                     if qid in answers else None}
                    for qid in player.get("order") or []
                ],
            })
            if settings.get("leaderboard", True) and players is not None:
                place, of = rank_of(players, player["_id"])
                result.update({"rank": place, "of": of})
        out["result"] = result

    return out


def host_player(player: Dict[str, Any], session: Dict[str, Any], at: datetime) -> Dict[str, Any]:
    return {
        "id": str(player["_id"]),
        "name": player.get("name", ""),
        "status": status(session, player, at),
        "joinedAt": iso(player.get("joined_at")),
        "answered": int(player.get("answered") or 0),
        "correct": int(player.get("correct") or 0),
        "score": int(player.get("score") or 0),
        "streak": int(player.get("streak") or 0),
        "total": len(player.get("order") or []),
    }


def question_tallies(session: Dict[str, Any], players: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per question: how many answered, how many were right, and how each
    option was chosen. The live board draws this as the class answers."""
    tallies = []
    for index, question in enumerate(session.get("questions") or []):
        qid = question["id"]
        answers = [
            p["answers"][qid] for p in players
            if not p.get("kicked") and qid in (p.get("answers") or {})
        ]
        item: Dict[str, Any] = {
            "id": qid,
            "index": index,
            "type": question["type"],
            "text": question.get("text", ""),
            "answered": len(answers),
            "correct": sum(1 for a in answers if a.get("correct")),
        }
        if question["type"] == "choice":
            item["options"] = [
                {
                    "id": option["id"],
                    "text": option.get("text", ""),
                    "count": sum(1 for a in answers if a.get("option") == option["id"]),
                    "correct": option["id"] == question.get("correct"),
                }
                for option in question.get("options") or []
            ]
        tallies.append(item)
    return tallies


def host_state(session: Dict[str, Any], players: List[Dict[str, Any]], at: datetime) -> Dict[str, Any]:
    active = [p for p in players if not p.get("kicked")]
    return {
        "id": str(session["_id"]),
        "quizId": session.get("quiz_id", ""),
        "title": session.get("title", ""),
        "code": session.get("code", ""),
        "status": session.get("status"),
        "classLabel": session.get("class_label", ""),
        "settings": session.get("settings") or {},
        "questionCount": len(session.get("questions") or []),
        "createdAt": iso(session.get("created_at")),
        "startsAt": iso(session.get("starts_at")),
        "endedAt": iso(session.get("ended_at")),
        "serverNow": iso(at),
        "players": [host_player(p, session, at) for p in active],
        "leaders": [str(p["_id"]) for p in ranked(active)[:5]],
        "questions": question_tallies(session, active),
    }
