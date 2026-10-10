"""What a question is, and how an answer is marked."""

import pytest
from quizkit import choice, short


@pytest.fixture
def q(quiz):
    from quiz_service import questions

    return questions


class TestShape:
    def test_the_right_option_named_by_position_becomes_its_id(self, q):
        cleaned = q.clean_question(choice(correct=2))
        assert cleaned["correct"] == cleaned["options"][2]["id"]

    def test_ids_the_editor_sent_survive_a_save(self, q):
        first = q.clean_question(choice())
        again = q.clean_question(first)
        assert again["id"] == first["id"]
        assert [o["id"] for o in again["options"]] == [o["id"] for o in first["options"]]

    def test_a_duplicated_id_is_replaced(self, q):
        """A pasted copy of a card must not answer to the original's id -
        results are keyed by it."""
        one = q.clean_question(choice())
        both = q.clean_questions([one, dict(one)], 50)
        assert both[0]["id"] != both[1]["id"]

    def test_a_forged_id_is_replaced(self, q):
        cleaned = q.clean_question({**choice(), "id": "answers.$where"})
        assert cleaned["id"].startswith("q-")

    def test_a_half_written_question_is_kept(self, q):
        """The editor saves while the teacher types; a save must not eat the
        empty option they are about to fill in."""
        cleaned = q.clean_question(choice(options=("3", "", "5", "6"), correct=None))
        assert len(cleaned["options"]) == 4
        assert cleaned["correct"] == ""

    def test_no_more_than_four_options(self, q):
        cleaned = q.clean_question(choice(options=tuple("abcdefg")))
        assert len(cleaned["options"]) == 4

    def test_accepted_variants_can_arrive_as_one_line(self, q):
        cleaned = q.clean_question({**short(), "accept": "600 · 600 Н | 0,6 кН"})
        assert cleaned["accept"] == ["600", "600 Н", "0,6 кН"]

    def test_unknown_type_is_a_choice(self, q):
        assert q.clean_question({"type": "essay", "text": "x"})["type"] == "choice"

    def test_not_a_question_at_all(self, q):
        assert q.clean_question("2 + 2") is None


class TestWhatStopsAQuestionBeingPlayed:
    def test_a_finished_question_has_no_problems(self, q):
        assert q.problems(q.clean_question(choice())) == []
        assert q.problems(q.clean_question(short())) == []

    @pytest.mark.parametrize("raw,code", [
        ({**choice(), "text": "  "}, "no_text"),
        (choice(options=("3", "", "5", "6")), "empty_option"),
        (choice(options=("3",), correct=0), "few_options"),
        (choice(correct=None), "no_correct"),
        (choice(options=("4", "4 ", "5", "6")), "duplicate_options"),
        ({**short(), "answer": ""}, "no_answer"),
    ])
    def test_each_problem_is_named(self, q, raw, code):
        assert code in q.problems(q.clean_question(raw))


class TestMarkingATypedAnswer:
    @pytest.mark.parametrize("typed", [
        "5", "5,0", "5.0", "5.00", " 5 ", "5 м/с²", "5м/с2", "5 М/С²",
    ])
    def test_the_same_number_written_differently_is_right(self, q, typed):
        assert q.is_correct_short(typed, q.clean_question(short()))

    @pytest.mark.parametrize("typed", ["6", "0.5", "50", "", "м/с²", "5 Н"])
    def test_a_different_answer_is_wrong(self, q, typed):
        assert not q.is_correct_short(typed, q.clean_question(short()))

    def test_a_thousand_with_a_space_in_it(self, q):
        question = q.clean_question(short(answer="1200", unit="Н", accept=()))
        assert q.is_correct_short("1 200", question)
        assert q.is_correct_short("1 200 Н", question)

    def test_the_minus_sign_people_actually_type(self, q):
        question = q.clean_question(short(answer="-3", unit="", accept=()))
        assert q.is_correct_short("−3", question)

    def test_a_word_answer_ignores_case(self, q):
        question = q.clean_question(short(answer="Инерция", unit="", accept=()))
        assert q.is_correct_short("инерция", question)
        assert not q.is_correct_short("масса", question)


class TestWhatAStudentIsSent:
    def test_no_answer_and_no_notes(self, q):
        question = q.clean_question(choice(notes={0: "санамады"}))
        view = q.student_view(question, None, 0, 1)
        flat = repr(view)
        assert "correct" not in view and "санамады" not in flat
        assert "explanation" not in view
        assert [o["text"] for o in view["options"]] == ["3", "4", "5", "22"]

    def test_options_come_in_the_players_own_order(self, q):
        question = q.clean_question(choice())
        order = [o["id"] for o in reversed(question["options"])]
        view = q.student_view(question, order, 0, 1)
        assert [o["text"] for o in view["options"]] == ["22", "5", "4", "3"]

    def test_a_typed_question_carries_its_unit_not_its_answer(self, q):
        view = q.student_view(q.clean_question(short()), None, 0, 1)
        assert view["unit"] == "м/с²"
        assert "answer" not in view and "accept" not in view
