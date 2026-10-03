"""A teacher's quizzes over HTTP: who may touch them, and what a save keeps."""

from quizkit import choice, short


class TestWhoMayUseIt:
    def test_signed_out_is_refused(self, as_):
        assert as_(None).get("/api/quiz/quizzes").status_code == 401

    def test_a_student_is_refused(self, as_):
        assert as_("student-token").get("/api/quiz/quizzes").status_code == 403

    def test_another_teachers_quiz_is_not_found(self, as_, make_quiz):
        mine = make_quiz()
        other = as_("other-token")
        assert other.get(f"/api/quiz/quizzes/{mine['id']}").status_code == 404
        assert other.put(f"/api/quiz/quizzes/{mine['id']}", json={"title": "x"}).status_code == 404
        assert other.delete(f"/api/quiz/quizzes/{mine['id']}").status_code == 404
        assert other.post(f"/api/quiz/quizzes/{mine['id']}/sessions", json={}).status_code == 404


class TestKeepingOne:
    def test_created_and_listed(self, client, make_quiz):
        created = make_quiz()
        listed = client.get("/api/quiz/quizzes").json()["items"]
        item = next(i for i in listed if i["id"] == created["id"])
        assert item["questionCount"] == 2
        assert item["kinds"] == {"choice": 1, "short": 1}
        assert item["ready"] is True
        assert item["lastRun"] is None

    def test_a_save_changes_only_what_it_names(self, client, make_quiz):
        created = make_quiz()
        saved = client.put(f"/api/quiz/quizzes/{created['id']}",
                           json={"title": "Ньютон заңдары"}).json()
        assert saved["title"] == "Ньютон заңдары"
        assert [q["id"] for q in saved["questions"]] == [q["id"] for q in created["questions"]]

    def test_a_half_written_question_saves_and_is_reported(self, client, make_quiz):
        created = make_quiz()
        questions = created["questions"] + [choice(options=("1", "", "", ""), correct=None)]
        saved = client.put(f"/api/quiz/quizzes/{created['id']}",
                           json={"questions": questions}).json()
        new_id = saved["questions"][-1]["id"]
        assert set(saved["problems"][new_id]) == {"empty_option", "no_correct"}

    def test_settings_outside_their_set_fall_back(self, client, make_quiz):
        created = make_quiz()
        saved = client.put(f"/api/quiz/quizzes/{created['id']}", json={
            "settings": {"timeLimitMin": 7, "leaderboard": "yes", "showResults": False},
        }).json()
        assert saved["settings"]["timeLimitMin"] == 15
        assert saved["settings"]["leaderboard"] is True
        assert saved["settings"]["showResults"] is False

    def test_a_copy_gets_fresh_ids_and_keeps_the_right_answer(self, client, make_quiz):
        created = make_quiz()
        copy = client.post(f"/api/quiz/quizzes/{created['id']}/copy").json()
        assert copy["id"] != created["id"]
        assert not {q["id"] for q in copy["questions"]} & {q["id"] for q in created["questions"]}
        original = created["questions"][0]
        copied = copy["questions"][0]
        right = next(o["text"] for o in original["options"] if o["id"] == original["correct"])
        assert next(o["text"] for o in copied["options"] if o["id"] == copied["correct"]) == right

    def test_deleting_takes_its_runs_with_it(self, client, open_session, join, quiz):
        made, session = open_session()
        join(session["code"])
        assert client.delete(f"/api/quiz/quizzes/{made['id']}").status_code == 200

        import asyncio

        players = asyncio.run(quiz.db.db.quiz_players.count_documents(
            {"session_id": session["id"]}))
        assert players == 0
        assert client.get(f"/api/quiz/sessions/{session['id']}").status_code == 404


class TestOpeningARun:
    def test_an_unfinished_quiz_cannot_be_opened(self, client, make_quiz):
        made = make_quiz([choice(correct=None), short()])
        response = client.post(f"/api/quiz/quizzes/{made['id']}/sessions", json={})
        assert response.status_code == 409
        assert response.json()["code"] == "quiz_not_ready"

    def test_an_empty_quiz_cannot_be_opened(self, client, make_quiz):
        made = make_quiz([])
        assert client.post(f"/api/quiz/quizzes/{made['id']}/sessions",
                           json={}).status_code == 409

    def test_the_chosen_settings_become_the_default(self, client, open_session):
        made, _ = open_session(timeLimitMin=5)
        assert client.get(f"/api/quiz/quizzes/{made['id']}").json()["settings"]["timeLimitMin"] == 5

    def test_a_code_from_the_readable_alphabet(self, open_session):
        from quiz_service.codes import ALPHABET

        _, session = open_session()
        assert len(session["code"]) == 6 and set(session["code"]) <= set(ALPHABET)

    def test_editing_the_quiz_does_not_change_the_run(self, client, open_session, join):
        """A question reworded while phones are answering it would make the
        results describe a test nobody took."""
        made, session = open_session()
        client.put(f"/api/quiz/quizzes/{made['id']}",
                   json={"questions": [choice(text="Өзгерді")]})
        token, state = join(session["code"])
        client.post(f"/api/quiz/sessions/{session['id']}/start")
        from quizkit import player

        assert player(client, token).state().json()["question"]["text"] == "2 + 2 = ?"

    def test_open_runs_are_capped(self, client, make_quiz, monkeypatch):
        from quiz_service.api import sessions

        monkeypatch.setattr(sessions, "MAX_OPEN_SESSIONS", 1)
        made = make_quiz()
        assert client.post(f"/api/quiz/quizzes/{made['id']}/sessions", json={}).status_code == 201
        second = client.post(f"/api/quiz/quizzes/{made['id']}/sessions", json={})
        assert second.status_code == 409 and second.json()["code"] == "too_many_open"
