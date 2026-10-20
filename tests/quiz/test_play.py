"""A run from the student's side: join by code, answer, finish.

What matters most here is what a phone is NOT told. The right answer reaches
a student only after they have answered, and only if the teacher chose to
show results; the next question only once the current one is answered.
"""

import asyncio
from datetime import timedelta

import pytest
from quizkit import choice, player, short


def _start(client, session):
    response = client.post(f"/api/quiz/sessions/{session['id']}/start")
    assert response.status_code == 200, response.text
    return response.json()


def _option(state, text):
    return next(o["id"] for o in state["question"]["options"] if o["text"] == text)


class TestJoining:
    def test_the_code_finds_the_quiz(self, client, open_session):
        _, session = open_session()
        found = client.get(f"/api/play/code/{session['code'].lower()}").json()
        assert found["questionCount"] == 2 and found["status"] == "lobby"
        assert found["joinable"] is True

    def test_an_unknown_code(self, client):
        response = client.get("/api/play/code/AAAAAA")
        assert response.status_code == 404 and response.json()["code"] == "no_such_code"

    def test_a_code_outside_the_alphabet_is_not_looked_up(self, client):
        assert client.get("/api/play/code/000000").status_code == 404

    def test_joining_puts_you_in_the_lobby(self, open_session, join):
        _, session = open_session()
        _, state = join(session["code"])
        assert state["status"] == "lobby"
        assert state["question"] is None

    def test_a_taken_name_is_told_apart_not_refused(self, open_session, join):
        _, session = open_session()
        join(session["code"], "Дана")
        _, second = join(session["code"], "дана")
        assert second["player"]["name"] == "дана 2"

    @pytest.mark.parametrize("name", ["", "   ", "​​"])
    def test_a_name_is_needed(self, client, open_session, name):
        _, session = open_session()
        response = client.post(f"/api/play/code/{session['code']}/join", json={"name": name})
        assert response.status_code == 400

    def test_a_long_name_is_cut(self, open_session, join):
        _, session = open_session()
        _, state = join(session["code"], "А" * 80)
        assert len(state["player"]["name"]) == 24

    def test_a_full_session(self, client, open_session, join, monkeypatch):
        from quiz_service.api import play

        monkeypatch.setattr(play, "MAX_PLAYERS", 1)
        _, session = open_session()
        join(session["code"])
        response = client.post(f"/api/play/code/{session['code']}/join", json={"name": "Ерлан"})
        assert response.status_code == 409 and response.json()["code"] == "session_full"

    def test_joins_per_address_are_limited(self, client, open_session, monkeypatch):
        from quiz_service.api import play

        monkeypatch.setattr(play.join_window, "limit", 2)
        _, session = open_session()
        headers = {"X-Real-IP": "10.0.0.7"}
        for name in ("A", "B"):
            assert client.post(f"/api/play/code/{session['code']}/join",
                               json={"name": name}, headers=headers).status_code == 201
        assert client.post(f"/api/play/code/{session['code']}/join",
                           json={"name": "C"}, headers=headers).status_code == 429

    def test_late_join_can_be_closed(self, client, open_session, join):
        _, session = open_session(lateJoin=False)
        join(session["code"])
        _start(client, session)
        response = client.post(f"/api/play/code/{session['code']}/join", json={"name": "Ерлан"})
        assert response.status_code == 409 and response.json()["code"] == "late_join_closed"

    def test_a_late_joiner_gets_a_countdown_of_their_own(self, client, open_session, join,
                                                         monkeypatch):
        from quiz_service.api import play

        _, session = open_session()
        join(session["code"])
        _start(client, session)
        monkeypatch.setattr(play, "COUNTDOWN_SEC", 30)
        _, late = join(session["code"], "Ерлан")
        assert late["status"] == "countdown"


class TestStarting:
    def test_nobody_in_the_lobby(self, client, open_session):
        _, session = open_session()
        response = client.post(f"/api/quiz/sessions/{session['id']}/start")
        assert response.status_code == 409 and response.json()["code"] == "empty_lobby"

    def test_everyone_starts_on_the_same_beat(self, client, open_session, join, monkeypatch):
        from quiz_service.api import sessions

        monkeypatch.setattr(sessions, "COUNTDOWN_SEC", 30)
        _, session = open_session()
        a, _ = join(session["code"], "A")
        b, _ = join(session["code"], "B")
        started = _start(client, session)

        first = player(client, a).state().json()
        second = player(client, b).state().json()
        assert first["status"] == second["status"] == "countdown"
        assert first["startsAt"] == second["startsAt"] == started["startsAt"]
        assert first["question"] is None

    def test_starting_twice(self, client, open_session, join):
        _, session = open_session()
        join(session["code"])
        _start(client, session)
        assert client.post(f"/api/quiz/sessions/{session['id']}/start").status_code == 409


class TestAnswering:
    def test_the_first_question_never_carries_its_answer(self, client, open_session, join):
        _, session = open_session([choice(notes={0: "қосты"})])
        token, _ = join(session["code"])
        _start(client, session)
        state = player(client, token).state().json()
        assert state["status"] == "playing"
        assert "correct" not in state["question"]
        assert "қосты" not in repr(state)

    def test_a_right_answer_scores_and_reveals(self, client, open_session, join):
        _, session = open_session()
        token, _ = join(session["code"])
        _start(client, session)
        me = player(client, token)
        state = me.state().json()

        reply = me.answer(questionId=state["question"]["id"], optionId=_option(state, "4")).json()
        assert reply["correct"] is True and reply["points"] == 100
        assert reply["reveal"]["explanation"]
        assert reply["state"]["question"]["type"] == "short"

    def test_a_streak_is_worth_a_little_more(self, client, open_session, join):
        _, session = open_session([choice(), choice(text="3 + 3 = ?", options=("6", "5"),
                                                    correct=0), short()])
        token, _ = join(session["code"])
        _start(client, session)
        me = player(client, token)

        state = me.state().json()
        me.answer(questionId=state["question"]["id"], optionId=_option(state, "4"))
        state = me.state().json()
        second = me.answer(questionId=state["question"]["id"], optionId=_option(state, "6")).json()
        assert second["points"] == 110
        assert second["state"]["progress"]["streak"] == 2

    def test_a_typed_answer_is_marked_as_a_number(self, client, open_session, join):
        _, session = open_session([short()])
        token, _ = join(session["code"])
        _start(client, session)
        me = player(client, token)
        state = me.state().json()
        reply = me.answer(questionId=state["question"]["id"], text="5,0 м/с²").json()
        assert reply["correct"] is True
        assert reply["state"]["status"] == "finished"

    def test_only_the_current_question_can_be_answered(self, client, open_session, join):
        made, session = open_session()
        token, _ = join(session["code"])
        _start(client, session)
        later = made["questions"][1]["id"]
        response = player(client, token).answer(questionId=later, text="5")
        assert response.status_code == 409 and response.json()["code"] == "not_current"

    def test_a_second_tap_on_the_same_question_is_not_a_second_answer(self, client,
                                                                         open_session, join):
        _, session = open_session()
        token, _ = join(session["code"])
        _start(client, session)
        me = player(client, token)
        state = me.state().json()
        qid = state["question"]["id"]
        assert me.answer(questionId=qid, optionId=_option(state, "4")).status_code == 200
        assert me.answer(questionId=qid, optionId=_option(state, "3")).status_code == 409
        assert me.state().json()["progress"]["answered"] == 1

    def test_an_option_from_another_question_is_refused(self, client, open_session, join):
        _, session = open_session()
        token, _ = join(session["code"])
        _start(client, session)
        state = player(client, token).state().json()
        response = player(client, token).answer(questionId=state["question"]["id"], optionId="o-ffffffffff")
        assert response.status_code == 400

    def test_skipping_counts_as_wrong_and_breaks_the_streak(self, client, open_session, join):
        _, session = open_session()
        token, _ = join(session["code"])
        _start(client, session)
        me = player(client, token)
        state = me.state().json()
        reply = me.answer(questionId=state["question"]["id"], skip=True).json()
        assert reply["correct"] is False and reply["state"]["progress"]["streak"] == 0

    def test_without_results_nothing_is_revealed(self, client, open_session, join):
        _, session = open_session([choice()], showResults=False)
        token, _ = join(session["code"])
        _start(client, session)
        me = player(client, token)
        state = me.state().json()
        reply = me.answer(questionId=state["question"]["id"], optionId=_option(state, "4")).json()
        assert reply["correct"] is None and reply["reveal"] is None
        result = reply["state"]["result"]
        assert result is not None and "score" not in result and "correct" not in result

    def test_an_unknown_token(self, client):
        response = client.get("/api/play/state", headers={"X-Player-Token": "nope"})
        assert response.status_code == 401

    def test_shuffled_options_differ_between_phones(self, client, make_quiz, join):
        """Neighbours see different letters, so "it's B" stops working. With
        four options a match by chance is 1 in 24 per pair - eight phones all
        agreeing would be a broken shuffle, not luck."""
        made = make_quiz([choice()])
        session = client.post(f"/api/quiz/quizzes/{made['id']}/sessions",
                              json={"settings": {"shuffleOptions": True}}).json()
        tokens = [join(session["code"], f"P{i}")[0] for i in range(8)]
        _start(client, session)
        orders = {
            tuple(o["text"] for o in player(client, t).state().json()["question"]["options"])
            for t in tokens
        }
        assert len(orders) > 1


class TestTheClock:
    def _expire(self, quiz, session_id, minutes):
        async def rewind():
            from quiz_service.db import now

            await quiz.db.db.quiz_players.update_many(
                {"session_id": session_id},
                {"$set": {"started_at": now() - timedelta(minutes=minutes)}},
            )

        asyncio.run(rewind())

    def test_time_up_finishes_the_student(self, client, open_session, join, quiz):
        _, session = open_session(timeLimitMin=5)
        token, _ = join(session["code"])
        _start(client, session)
        self._expire(quiz, session["id"], 6)

        state = player(client, token).state().json()
        assert state["status"] == "finished"
        assert state["question"] is None

    def test_an_answer_after_time_is_refused(self, client, open_session, join, quiz):
        _, session = open_session(timeLimitMin=5)
        token, _ = join(session["code"])
        _start(client, session)
        state = player(client, token).state().json()
        self._expire(quiz, session["id"], 6)
        response = player(client, token).answer(questionId=state["question"]["id"],
                                                optionId=_option(state, "4"))
        assert response.status_code == 409

    def test_the_sweep_finishes_a_phone_that_stopped_asking(self, client, open_session,
                                                             join, quiz):
        from quiz_service import lifecycle

        _, session = open_session(timeLimitMin=5)
        join(session["code"])
        _start(client, session)
        self._expire(quiz, session["id"], 6)
        asyncio.run(lifecycle.sweep_once())

        board = client.get(f"/api/quiz/sessions/{session['id']}").json()
        assert board["players"][0]["status"] == "finished"

    def test_no_limit_means_no_deadline(self, client, open_session, join):
        _, session = open_session(timeLimitMin=0)
        token, _ = join(session["code"])
        _start(client, session)
        assert player(client, token).state().json()["deadline"] is None


class TestTheTeacherEndsIt:
    def test_ending_finishes_everyone(self, client, open_session, join):
        _, session = open_session()
        token, _ = join(session["code"])
        _start(client, session)
        ended = client.post(f"/api/quiz/sessions/{session['id']}/end").json()
        assert ended["status"] == "ended"
        state = player(client, token).state().json()
        assert state["status"] == "finished" and state["result"]["waiting"] is False

    def test_the_code_stops_working(self, client, open_session):
        _, session = open_session()
        client.post(f"/api/quiz/sessions/{session['id']}/end")
        assert client.get(f"/api/play/code/{session['code']}").status_code == 404

    def test_removing_a_player(self, client, open_session, join):
        _, session = open_session()
        token, state = join(session["code"], "Жаман сөз")
        pid = state["player"]["id"]
        assert client.delete(f"/api/quiz/sessions/{session['id']}/players/{pid}").status_code == 200
        assert player(client, token).state().json()["status"] == "kicked"
        board = client.get(f"/api/quiz/sessions/{session['id']}").json()
        assert board["players"] == []


class TestResults:
    def test_a_shared_wrong_answer_is_named_with_its_reason(self, client, open_session, join):
        """Three of four picking the same wrong option is one misunderstanding,
        and the option's note says which."""
        _, session = open_session([choice(notes={3: "Сандарды қатар жазды"})])
        tokens = [join(session["code"], name)[0] for name in ("A", "B", "C", "D")]
        _start(client, session)
        for token, pick in zip(tokens, ("22", "22", "22", "4"), strict=True):
            me = player(client, token)
            state = me.state().json()
            me.answer(questionId=state["question"]["id"], optionId=_option(state, pick))

        results = client.get(f"/api/quiz/sessions/{session['id']}/results").json()
        insight = results["insights"][0]
        assert insight["answer"] == "22" and insight["count"] == 3
        assert insight["note"] == "Сандарды қатар жазды"
        assert results["questions"][0]["rate"] == 0.25
        assert results["summary"]["players"] == 4

    def test_students_come_ranked(self, client, open_session, join):
        _, session = open_session([choice()])
        weak, _ = join(session["code"], "Әлсіз")
        strong, _ = join(session["code"], "Күшті")
        _start(client, session)
        for token, pick in ((weak, "3"), (strong, "4")):
            me = player(client, token)
            state = me.state().json()
            me.answer(questionId=state["question"]["id"], optionId=_option(state, pick))

        people = client.get(f"/api/quiz/sessions/{session['id']}/results").json()["players"]
        assert [p["name"] for p in people] == ["Күшті", "Әлсіз"]
        assert people[0]["answers"][0]["value"] == "4"

    def test_a_finished_student_sees_their_place(self, client, open_session, join):
        _, session = open_session([choice()])
        token, _ = join(session["code"])
        _start(client, session)
        me = player(client, token)
        state = me.state().json()
        reply = me.answer(questionId=state["question"]["id"], optionId=_option(state, "4")).json()
        assert reply["state"]["result"]["rank"] == 1

    def test_another_teacher_cannot_read_them(self, as_, open_session):
        _, session = open_session()
        assert as_("other-token").get(
            f"/api/quiz/sessions/{session['id']}/results").status_code == 404
