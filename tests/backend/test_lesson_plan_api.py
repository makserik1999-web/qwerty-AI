"""The lesson-plan endpoints: who may use them, and what they refuse.

The second part of the product only teachers can reach. The agent owns the
document and the checks that matter to its content; what is asserted here is
the boundary around it - the role, the closed sets, and the ownership rule
that makes a guessed id worth nothing.
"""

from typing import Any, Dict

import pytest

VALID: Dict[str, Any] = {
    "subject": "physics",
    "grade": 8,
    "topic": "Ньютонның екінші заңы",
    "lang": "kk",
    "duration": 40,
    "section": "",
}

PLAN: Dict[str, Any] = {
    "section": "Динамика",
    "objectives": [{"code": "8.2.1.4", "text": "Заңды қолдану"}],
    "lesson_goal": "Ұғындыру",
    "success_criteria": ["Жаза алады"],
    "values": "Ынтымақ",
    "cross_curricular": "Математика",
    "prior_knowledge": "Инерция",
    "stages": [
        {"phase": "start", "title": "Кіріспе", "minutes": 5,
         "teacher": "Сұрайды", "student": "Жауап береді",
         "assessment": "Ауызша", "resources": "Тақта"},
        {"phase": "middle", "title": "Негізгі", "minutes": 30,
         "teacher": "Түсіндіреді", "student": "Есеп шығарады",
         "assessment": "Жазбаша", "resources": "Оқулық"},
        {"phase": "end", "title": "Қорытынды", "minutes": 5,
         "teacher": "Қорытады", "student": "Рефлексия жазады",
         "assessment": "Стикер", "resources": "Стикер"},
    ],
    "differentiation": "Қолдау",
    "assessment_plan": "Ауызша",
    "health_safety": "Партаның арасы",
}


@pytest.fixture
def agent(backend):
    """An agent that answers with a plan, without a model behind it."""
    from app.ws.manager import agent_manager

    sent = []

    class _Socket:
        async def send_json(self, payload):
            sent.append(payload)
            agent_manager.resolve_assessment(payload["request_id"], {
                "plan": dict(PLAN),
                "minutes_planned": 40,
                "dropped_codes": 0,
            })

        async def close(self, code=1000, reason=""):
            pass

    agent_manager.agent_connection = _Socket()
    agent_manager.agent_features = {"assessment", "lesson_plan", "ack"}
    yield sent
    agent_manager.agent_connection = None
    agent_manager.agent_features = set()


@pytest.fixture
def address_book():
    import uuid

    return lambda: f"p{uuid.uuid4().hex[:10]}@school.kz"


@pytest.fixture
def teacher(client, address_book):
    """A signed-in teacher: the role is chosen at signup and lives on the
    account, which is why this is the only way to get one."""
    response = client.post("/api/auth/signup", json={
        "email": address_book(), "password": "password123",
        "name": "Айсұлу", "role": "teacher",
    })
    assert response.status_code == 201, response.text
    return response.json()["user"]


# ------------------------------------------------------------- who may ask --


class TestOnlyTeachers:
    def test_a_signed_out_visitor_is_refused(self, anon_client):
        assert anon_client.post("/api/lesson-plans", json=VALID).status_code == 401

    def test_a_student_is_refused(self, client, address_book):
        """The role lives on the account, so this is refused by the server and
        not by hiding a link."""
        client.post("/api/auth/signup", json={
            "email": address_book(), "password": "password123",
            "name": "Дінмұхаммед", "role": "student",
        })
        assert client.post("/api/lesson-plans", json=VALID).status_code == 403

    def test_listing_needs_a_teacher_too(self, anon_client):
        assert anon_client.get("/api/lesson-plans").status_code == 401


# ------------------------------------------------------- what reaches a prompt --


class TestTheRequestIsCheckedBeforeItTravels:
    @pytest.mark.parametrize("field,bad", [
        ("subject", "astrology"),
        ("lang", "fr"),
        ("grade", 2),
        ("duration", 90),
    ])
    def test_a_value_outside_its_closed_set_is_refused(self, client, teacher,
                                                       agent, field, bad):
        response = client.post("/api/lesson-plans", json={**VALID, field: bad})
        assert response.status_code == 400
        assert not agent, "a rejected request still reached the agent"

    def test_an_empty_topic_is_refused(self, client, teacher, agent):
        assert client.post("/api/lesson-plans",
                           json={**VALID, "topic": "   "}).status_code == 400
        assert not agent

    def test_an_overlong_topic_is_refused(self, client, teacher, agent):
        assert client.post("/api/lesson-plans",
                           json={**VALID, "topic": "x" * 500}).status_code == 400
        assert not agent

    def test_the_spec_the_agent_gets_is_the_validated_one(self, client, teacher, agent):
        client.post("/api/lesson-plans", json=VALID)
        assert len(agent) == 1
        frame = agent[0]
        assert frame["type"] == "lesson_plan"
        assert frame["spec"] == {
            "subject": "physics", "grade": 8, "topic": VALID["topic"],
            "language": "kk", "duration": 40, "section": "",
        }


# ------------------------------------------------------------ the round trip --


class TestWritingAndKeepingOne:
    def test_a_plan_comes_back_and_is_listed(self, client, teacher, agent):
        created = client.post("/api/lesson-plans", json=VALID)
        assert created.status_code == 201, created.text

        body = created.json()
        assert body["minutesPlanned"] == 40
        assert len(body["plan"]["stages"]) == 3

        listed = client.get("/api/lesson-plans").json()["items"]
        assert [p["id"] for p in listed] == [body["id"]]

    def test_every_stage_gets_an_id(self, client, teacher, agent):
        """Position is not an identity: deleting the second stage must not
        rename the third, and an edit opened on one has to land on it."""
        plan = client.post("/api/lesson-plans", json=VALID).json()["plan"]
        ids = [stage["id"] for stage in plan["stages"]]
        assert all(ids) and len(set(ids)) == len(ids)

    def test_an_edit_is_kept(self, client, teacher, agent):
        created = client.post("/api/lesson-plans", json=VALID).json()
        edited = {**created["plan"]}
        edited["stages"] = [{**s} for s in edited["stages"]]
        edited["stages"][0]["teacher"] = "Отредактировано учителем"

        saved = client.put(f"/api/lesson-plans/{created['id']}", json={"plan": edited})
        assert saved.status_code == 200
        assert saved.json()["plan"]["stages"][0]["teacher"] == "Отредактировано учителем"

        reread = client.get(f"/api/lesson-plans/{created['id']}").json()
        assert reread["plan"]["stages"][0]["teacher"] == "Отредактировано учителем"

    def test_a_plan_with_no_stages_is_not_a_plan(self, client, teacher, agent):
        created = client.post("/api/lesson-plans", json=VALID).json()
        response = client.put(f"/api/lesson-plans/{created['id']}",
                              json={"plan": {"stages": []}})
        assert response.status_code == 400

    def _save(self, client, plan_id, plan):
        return client.put(f"/api/lesson-plans/{plan_id}", json={"plan": plan})

    def test_a_save_keeps_only_the_documents_fields(self, client, teacher, agent):
        """The save used to store whatever JSON arrived. The fields the
        generator may not write must not come in through the edit instead."""
        created = client.post("/api/lesson-plans", json=VALID).json()
        edited = {**created["plan"], "teacher_name": "Иванов И.И.",
                  "date": "2026-09-15", "junk": "x" * 10_000}

        saved = self._save(client, created["id"], edited).json()["plan"]
        for smuggled in ("teacher_name", "date", "junk"):
            assert smuggled not in saved, smuggled
        assert saved["lesson_goal"] == PLAN["lesson_goal"]

    def test_a_stage_the_page_cannot_draw_is_mended_or_dropped(self, client, teacher, agent):
        created = client.post("/api/lesson-plans", json=VALID).json()
        edited = {**created["plan"], "stages": [
            42,
            {"phase": "warmup", "minutes": "a lot", "teacher": ["not", "text"],
             "student": "Жазады", "id": "made-up"},
        ]}

        stages = self._save(client, created["id"], edited).json()["plan"]["stages"]
        assert len(stages) == 1
        stage = stages[0]
        assert stage["phase"] == "middle"
        assert stage["minutes"] == 0
        assert stage["teacher"] == ""
        assert stage["id"] != "made-up" and stage["id"].startswith("s-")

    def test_stage_ids_survive_a_save(self, client, teacher, agent):
        """The page finds the stage being edited by its id."""
        created = client.post("/api/lesson-plans", json=VALID).json()
        before = [s["id"] for s in created["plan"]["stages"]]

        saved = self._save(client, created["id"], created["plan"]).json()["plan"]
        assert [s["id"] for s in saved["stages"]] == before

    def test_a_half_rewritten_stage_is_not_eaten(self, client, teacher, agent):
        """A teacher can clear a column on the way to rewriting it. Saving then
        must not delete the stage they are typing into."""
        created = client.post("/api/lesson-plans", json=VALID).json()
        edited = {**created["plan"]}
        edited["stages"] = [{**s} for s in edited["stages"]]
        edited["stages"][1]["student"] = ""

        saved = self._save(client, created["id"], edited).json()["plan"]
        assert len(saved["stages"]) == 3
        assert saved["stages"][1]["student"] == ""

    def test_one_plan_cannot_grow_into_megabytes(self, client, teacher, agent):
        created = client.post("/api/lesson-plans", json=VALID).json()
        stage = {**created["plan"]["stages"][0], "teacher": "ә" * 50_000}
        edited = {**created["plan"], "stages": [stage] * 200}

        saved = self._save(client, created["id"], edited).json()["plan"]
        assert len(saved["stages"]) <= 30
        assert all(len(s["teacher"]) <= 4000 for s in saved["stages"])

    def test_stages_that_are_all_unusable_are_no_plan(self, client, teacher, agent):
        created = client.post("/api/lesson-plans", json=VALID).json()
        edited = {**created["plan"], "stages": [1, "two", None]}
        assert self._save(client, created["id"], edited).status_code == 400

    def test_deleting_one(self, client, teacher, agent):
        created = client.post("/api/lesson-plans", json=VALID).json()
        assert client.delete(f"/api/lesson-plans/{created['id']}").status_code == 200
        assert client.get(f"/api/lesson-plans/{created['id']}").status_code == 404


class TestOneTeacherCannotReachAnothersPlan:
    def test_reading(self, client, teacher, agent, address_book):
        mine = client.post("/api/lesson-plans", json=VALID).json()

        # A second teacher, signed in over the first.
        client.post("/api/auth/signup", json={
            "email": address_book(), "password": "password123",
            "name": "Басқа", "role": "teacher",
        })

        assert client.get(f"/api/lesson-plans/{mine['id']}").status_code == 404
        assert client.put(f"/api/lesson-plans/{mine['id']}",
                          json={"plan": PLAN}).status_code == 404
        assert client.delete(f"/api/lesson-plans/{mine['id']}").status_code == 404


class TestWhenTheAgentCannotHelp:
    def test_no_agent_is_a_503_and_not_a_crash(self, client, teacher, backend):
        from app.ws.manager import agent_manager

        agent_manager.agent_connection = None
        assert client.post("/api/lesson-plans", json=VALID).status_code == 503

    def test_an_agent_without_the_feature_is_the_same(self, client, teacher, backend):
        """A rolling deploy has one of these for a minute. It must not read the
        frame as something else."""
        from app.ws.manager import agent_manager

        class _Old:
            async def send_json(self, payload):
                raise AssertionError("an older agent was sent a lesson_plan frame")

            async def close(self, code=1000, reason=""):
                pass

        agent_manager.agent_connection = _Old()
        agent_manager.agent_features = {"assessment"}
        try:
            assert client.post("/api/lesson-plans", json=VALID).status_code == 503
        finally:
            agent_manager.agent_connection = None
            agent_manager.agent_features = set()
