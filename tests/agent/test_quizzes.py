"""Quiz questions from the model: what is kept, and what never reaches a class.

The wrong options are the point of a quiz question - each names one
misunderstanding - so most of what is checked here is about options: four,
distinct, exactly one right, none that refers to the others, and the right
one not always sitting in the same place.
"""

import random
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "agent", REPO_ROOT / "tests" / "stubs"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from anyq import quizzes as qz  # noqa: E402

SPEC = {"subject": "physics", "grade": 8, "topic": "Ньютонның екінші заңы",
        "language": "kk", "count": 4, "mix": "mixed", "difficulty": "medium"}


def choice(text="Массасы 2 кг денеге 10 Н күш әсер етеді. Үдеу?",
           options=("5 м/с²", "20 м/с²", "0,2 м/с²", "12 м/с²"), correct=0, notes=None):
    return {
        "type": "choice", "text": text, "options": list(options), "correct": correct,
        "notes": list(notes) if notes is not None else ["", "көбейтті", "кері бөлді", "қосты"],
        "explanation": "a = F/m", "topic": "Екінші заң",
    }


def short(text="1200 кг автомобиль 0,5 м/с² үдеумен қозғалады. Тарту күші?",
          answer="600", unit="Н", accept=("0,6 кН",)):
    return {"type": "short", "text": text, "answer": answer, "unit": unit,
            "accept": list(accept), "explanation": "F = ma", "topic": "Екінші заң"}


def payload(*questions):
    return {"questions": list(questions)}


def four():
    return payload(choice(), choice(text="Инерция дегеніміз не?",
                                    options=("Жылдамдықты сақтау қасиеті", "Күш",
                                             "Тартылыс", "Үйкеліс")),
                   choice(text="Үшінші заң не дейді?",
                          options=("Күштер тең, қарама-қарсы", "Күштер тең, бағыттас",
                                   "Ауыр дене күштірек", "Күштер теңгеріледі")),
                   short())


class TestOptions:
    def test_a_good_question_is_kept_with_its_notes(self):
        result = qz._validate(payload(choice()), {**SPEC, "count": 1})
        question = result["questions"][0]
        right = question["options"][question["correct"]]
        assert right["text"] == "5 м/с²" and right["note"] == ""
        notes = {o["text"]: o["note"] for o in question["options"]}
        assert notes["20 м/с²"] == "көбейтті"

    def test_numbers_come_sorted_and_the_answer_follows(self):
        question = qz._validate(payload(choice()), {**SPEC, "count": 1})["questions"][0]
        assert [o["text"] for o in question["options"]] == ["0,2 м/с²", "5 м/с²", "12 м/с²", "20 м/с²"]
        assert question["options"][question["correct"]]["text"] == "5 м/с²"

    def test_words_are_shuffled_so_the_answer_is_not_always_first(self):
        """Models put the right answer first. Across many questions it must
        land in more than one place."""
        positions = set()
        for seed in range(20):
            raw = choice(text=f"Сұрақ {seed}",
                         options=("Тыныштықта қалады", "Тоқтайды", "Үдейді", "Бұрылады"))
            question = qz._validate(payload(raw), {**SPEC, "count": 1},
                                    random.Random(seed))["questions"][0]
            positions.add(question["correct"])
            assert question["options"][question["correct"]]["text"] == "Тыныштықта қалады"
        assert len(positions) > 1

    @pytest.mark.parametrize("options", [
        ("5", "5", "6", "7"),
        ("5 м/с²", "5  м/с²", "6", "7"),
        ("Иә", "Жоқ", "", "Мүмкін"),
        ("Иә", "Жоқ", "Мүмкін"),
    ])
    def test_four_distinct_options_or_nothing(self, options):
        result = qz._validate(payload(choice(options=options)), {**SPEC, "count": 1})
        assert "error" in result

    @pytest.mark.parametrize("bad", ["Барлығы дұрыс", "Все ответы верны",
                                     "None of the above", "Дұрыс жауап жоқ"])
    def test_options_that_point_at_other_options(self, bad):
        options = ("Масса", "Салмақ", "Күш", bad)
        result = qz._validate(payload(choice(options=options)), {**SPEC, "count": 1})
        assert "error" in result

    @pytest.mark.parametrize("correct", [4, -1, "0", True, None])
    def test_the_right_answer_must_be_one_of_the_options(self, correct):
        result = qz._validate(payload(choice(correct=correct)), {**SPEC, "count": 1})
        assert "error" in result


class TestTypedAnswers:
    def test_the_unit_is_kept_apart(self):
        question = qz._validate(payload(short()), {**SPEC, "count": 1, "mix": "short"})["questions"][0]
        assert question == {**question, "answer": "600", "unit": "Н", "accept": ["0,6 кН"]}

    def test_an_answer_too_long_to_type(self):
        result = qz._validate(payload(short(answer="күш массаға тура пропорционал болады")),
                              {**SPEC, "count": 1, "mix": "short"})
        assert "error" in result


class TestTheSet:
    def test_a_full_set(self):
        result = qz._validate(four(), SPEC)
        assert len(result["questions"]) == 4 and result["dropped"] == 0

    def test_a_few_bad_ones_are_dropped_not_fatal(self):
        body = four()
        body["questions"].append(choice(text="Жаман", correct=9))
        result = qz._validate(body, {**SPEC, "count": 5})
        assert len(result["questions"]) == 4 and result["dropped"] == 1

    def test_mostly_bad_is_refused(self):
        bad = [choice(text=f"q{i}", correct=9) for i in range(6)]
        result = qz._validate(payload(choice(), *bad), {**SPEC, "count": 7})
        assert "error" in result

    def test_no_more_than_asked(self):
        assert len(qz._validate(four(), {**SPEC, "count": 2})["questions"]) == 2

    def test_questions_already_in_the_quiz_are_not_returned(self):
        """`avoid` is what "add more" sends."""
        spec = {**SPEC, "count": 3, "avoid": ["Инерция дегеніміз не?"]}
        texts = [q["text"] for q in qz._validate(four(), spec)["questions"]]
        assert "Инерция дегеніміз не?" not in texts

    def test_a_repeat_within_one_reply_is_dropped(self):
        result = qz._validate(payload(choice(), choice(), short()), {**SPEC, "count": 3})
        assert len(result["questions"]) == 2

    def test_only_choice_when_only_choice_was_asked(self):
        result = qz._validate(four(), {**SPEC, "count": 3, "mix": "choice"})
        assert all(q["type"] == "choice" for q in result["questions"])

    def test_not_an_object(self):
        assert "error" in qz._validate(["x"], SPEC)
        assert "error" in qz._validate({"questions": "x"}, SPEC)


class TestThePrompt:
    def test_it_asks_for_the_split_it_will_check(self):
        prompt = qz._system_prompt({**SPEC, "count": 8, "mix": "mixed"})
        assert "6 multiple-choice and 2 short-answer" in prompt

    def test_it_asks_for_a_note_on_every_wrong_option(self):
        assert "For every wrong option write a note" in qz._system_prompt(SPEC)

    def test_the_topic_is_wrapped_as_untrusted_data(self):
        source = (REPO_ROOT / "agent" / "anyq" / "quizzes.py").read_text(encoding="utf-8")
        assert '_wrap("topic", topic)' in source
        assert "USER_CONTENT_NOTICE" in source
