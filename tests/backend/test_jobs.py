"""Generation tasks: the log the admin panel reads, background documents, health.

Every video and document becomes a task with a status, a render time and, when
it fails, an error type. Lesson plans and quiz drafts can be asked for in the
background - Cloudflare gives up after 100 seconds and a plan can take two
minutes - and are then collected by polling. Staff see the tasks and the
system's health; only the admin sees the metrics, which include money.
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

PLAN_REQUEST = {"subject": "physics", "grade": 8, "topic": "Ньютонның екінші заңы",
                "lang": "kk", "duration": 40, "section": ""}
PLAN = {
    "section": "Динамика", "objectives": [{"code": "8.2.1.4", "text": "Заңды қолдану"}],
    "lesson_goal": "Ұғындыру", "success_criteria": ["Жаза алады"],
    "stages": [
        {"phase": "start", "title": "Кіріспе", "minutes": 5, "teacher": "Сұрайды", "student": "Жауап береді"},
        {"phase": "middle", "title": "Негізгі", "minutes": 30, "teacher": "Түсіндіреді", "student": "Шығарады"},
        {"phase": "end", "title": "Қорытынды", "minutes": 5, "teacher": "Қорытады", "student": "Жазады"},
    ],
}

QUIZ_REQUEST = {
    "subject": "physics", "grade": 8, "topic": "Үйкеліс күші", "lang": "kk",
    "count": 2, "mix": "mixed", "difficulty": "medium", "purpose": "new", "avoid": [],
}
QUESTIONS = [{"type": "single", "text": "Үйкеліс неге тәуелді?", "options": ["a", "b"], "answer": 0}]
BACKGROUND = {"Prefer": "respond-async"}


def run_db(coro):
    return asyncio.run(coro)


@pytest.fixture
def account(backend):
    from fastapi.testclient import TestClient

    opened = []

    def _make(role="teacher", staff=None):
        c = TestClient(backend.app)
        c.__enter__()
        opened.append(c)
        r = c.post("/api/auth/signup", json={"email": f"j{uuid.uuid4().hex[:10]}@school.kz",
                                             "password": "password123", "role": role})
        assert r.status_code == 201, r.text
        c.user = r.json()["user"]
        if staff:
            run_db(backend.db.db.users.update_one({"_id": ObjectId(c.user["id"])},
                                                  {"$set": {"staff_role": staff}}))
        return c

    yield _make
    for c in opened:
        c.__exit__(None, None, None)


@pytest.fixture
def documents(backend):
    """An agent that writes documents. `reply` decides what it answers."""
    from app.ws.manager import agent_manager

    state = {"reply": None, "sent": []}

    class _Socket:
        async def send_json(self, payload):
            state["sent"].append(payload)
            reply = state["reply"] or (
                {"plan": dict(PLAN), "minutes_planned": 40} if payload["type"] == "lesson_plan"
                else {"questions": QUESTIONS, "requested": 2})
            agent_manager.resolve_assessment(payload["request_id"], reply)

        async def close(self, code=1000, reason=""):
            pass

    agent_manager.agent_connection = _Socket()
    agent_manager.agent_features = {"lesson_plan", "quiz", "assessment", "ack"}
    yield state
    agent_manager.agent_connection = None
    agent_manager.agent_features = set()


def poll(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = client.get(f"/api/jobs/{job_id}")
        assert found.status_code == 200, found.text
        body = found.json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("the job never finished")


def job_by_ref(backend, ref):
    return run_db(backend.db.db.generation_jobs.find_one({"ref": ref}))


def ask_video(client, agent_secret, reply, *, narration=True, frames=()):
    """One question through /ws to a test agent. Returns the agent's render request."""
    with client.websocket_connect("/ws/agent") as agent:
        agent.send_json({"type": "auth", "token": agent_secret, "features": ["ack"]})
        assert agent.receive_json()["type"] == "auth_ok"
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "create_chat", "data": {"title": "t"}})
            chat_id = ws.receive_json()["data"]["id"]
            ws.send_json({"type": "user_message", "data": {
                "chat_id": chat_id, "prompt": f"Үйкеліс {uuid.uuid4().hex[:6]}", "narration": narration}})
            assert ws.receive_json()["type"] == "message_received"
            render = agent.receive_json()
            agent.send_json({"type": "ack", "request_id": render["request_id"]})
            for frame in frames:
                agent.send_json({**frame, "request_id": render["request_id"]})
                ws.receive_json()
            agent.send_json({"request_id": render["request_id"], **reply})
            ws.receive_json()
    return render


class TestVideoTasks:
    def test_a_render_is_logged_from_queue_to_done(self, backend, client, new_user, agent_secret):
        new_user()
        render = ask_video(client, agent_secret, {
            "status": "complete", "text": "Жауап", "video_path": "rendered_j1.mp4",
            "duration": 41.5, "has_audio": True, "elapsed_sec": 73.2, "tts_chars": 812,
        }, frames=[{"type": "progress", "stage": "write"}])
        job = job_by_ref(backend, render["request_id"])
        assert job["kind"] == "video" and job["status"] == "done"
        assert job["video"] is True and job["has_audio"] is True and job["narration"] is True
        assert job["render_sec"] == 73.2 and job["tts_chars"] == 812 and job["duration"] == 41.5
        assert job.get("started_at")
        # Done: the question is not kept here - it is in the chat.
        assert "prompt" not in job["spec"] and "chat_id" not in job["spec"]

    def test_a_failure_keeps_its_type_and_what_was_asked(self, backend, client, new_user, agent_secret):
        new_user()
        render = ask_video(client, agent_secret, {
            "status": "error", "text": "Кешіріңіз", "error": "boom", "error_type": "RenderError",
            "elapsed_sec": 12.0, "tts_chars": 300,
        })
        job = job_by_ref(backend, render["request_id"])
        assert job["status"] == "failed" and job["error_type"] == "RenderError"
        assert job["tts_chars"] == 300 and job["spec"]["prompt"].startswith("Үйкеліс")

    def test_a_timeout_in_the_sweep_fails_the_task(self, backend, client, new_user):
        from app.services import jobs
        from app.ws import manager

        ref = f"sweep-{uuid.uuid4().hex}"
        run_db(jobs.start("video", "u", ref))
        manager.agent_manager.pending_requests[ref] = {"user_id": "u", "chat_id": "c", "created_at": -10**9}
        run_db(manager._sweep_once())
        job = job_by_ref(backend, ref)
        assert job["status"] == "failed" and job["error_type"] == "timeout"

    def test_open_tasks_are_closed_after_a_restart(self, backend):
        from app.services import jobs

        ref = f"open-{uuid.uuid4().hex}"
        run_db(jobs.start("lesson_plan", "u", ref))
        run_db(jobs.running(ref))
        assert run_db(jobs.recover_after_restart()) >= 1
        job = job_by_ref(backend, ref)
        assert job["status"] == "failed" and job["error_type"] == "backend_restart"


class TestBackgroundDocuments:
    def test_a_lesson_plan_in_the_background(self, backend, account, documents):
        teacher = account()
        started = teacher.post("/api/lesson-plans", json=PLAN_REQUEST, headers=BACKGROUND)
        assert started.status_code == 202, started.text
        done = poll(teacher, started.json()["job_id"])
        assert done["status"] == "done"
        assert done["lesson_plan"]["topic"] == PLAN_REQUEST["topic"]
        # And it is in the teacher's list, polled or not.
        assert any(p["id"] == done["lesson_plan"]["id"] for p in teacher.get("/api/lesson-plans").json()["items"])

    def test_without_the_header_it_still_answers_in_one_go(self, backend, account, documents):
        teacher = account()
        made = teacher.post("/api/lesson-plans", json=PLAN_REQUEST)
        assert made.status_code == 201 and made.json()["plan"]["stages"]
        job = run_db(backend.db.db.generation_jobs.find_one({"output_id": made.json()["id"]}))
        assert job["kind"] == "lesson_plan" and job["status"] == "done"

    def test_a_failure_reaches_the_poller_as_the_request_would_have(self, backend, account, documents):
        teacher = account()
        documents["reply"] = {"error": "timeout"}
        started = teacher.post("/api/lesson-plans", json=PLAN_REQUEST, headers=BACKGROUND)
        failed = poll(teacher, started.json()["job_id"])
        assert failed["status"] == "failed" and failed["error"]["status"] == 504
        job = run_db(backend.db.db.generation_jobs.find_one({"_id": ObjectId(started.json()["job_id"])}))
        assert job["error_type"] == "timeout"

    def test_refusals_still_answer_at_once(self, backend, account, documents):
        teacher = account()
        bad = teacher.post("/api/lesson-plans", json={**PLAN_REQUEST, "grade": 99}, headers=BACKGROUND)
        assert bad.status_code == 400

    def test_a_quiz_draft_is_handed_over_once(self, backend, account, documents):
        teacher = account()
        started = teacher.post("/api/quiz-drafts", json=QUIZ_REQUEST, headers=BACKGROUND)
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        done = poll(teacher, job_id)
        assert done["result"]["questions"] == QUESTIONS
        again = teacher.get(f"/api/jobs/{job_id}").json()
        assert again["status"] == "done" and again["result"] is None

    def test_somebody_elses_job_is_not_found(self, backend, account, documents):
        teacher, other = account(), account()
        job_id = teacher.post("/api/quiz-drafts", json=QUIZ_REQUEST, headers=BACKGROUND).json()["job_id"]
        assert other.get(f"/api/jobs/{job_id}").status_code == 404
        assert other.get("/api/jobs/not-an-id").status_code == 404

    def test_an_uncollected_draft_is_forgotten(self, backend):
        from app.services import jobs

        ref = f"old-{uuid.uuid4().hex}"
        run_db(jobs.start("quiz_draft", "u", ref))
        run_db(jobs.finish(ref, ok=True, result={"questions": QUESTIONS}))
        run_db(jobs.forget_uncollected(datetime.now(timezone.utc) + timedelta(hours=2)))
        assert "result" not in job_by_ref(backend, ref)


class TestAdminTasks:
    def _failed_video(self, client, new_user, agent_secret):
        new_user()
        return ask_video(client, agent_secret, {"status": "error", "text": "x", "error": "e",
                                                "error_type": "RenderError"})

    def test_support_lists_failures_and_restarts_one(self, backend, account, client, new_user, agent_secret):
        render = self._failed_video(client, new_user, agent_secret)
        job = job_by_ref(backend, render["request_id"])
        support = account(staff="support")

        listed = support.get("/api/admin/jobs", params={"status": "failed", "kind": "video"}).json()
        mine = next(item for item in listed["items"] if item["id"] == str(job["_id"]))
        assert mine["error_type"] == "RenderError" and mine["restartable"] is True

        # An agent without "ack": the restart's request is not held up waiting
        # for a confirmation this test could only send after the call returns.
        with client.websocket_connect("/ws/agent") as agent:
            agent.send_json({"type": "auth", "token": agent_secret, "features": []})
            assert agent.receive_json()["type"] == "auth_ok"
            restarted = support.post(f"/api/admin/jobs/{job['_id']}/restart", json={"reason": "test"})
            assert restarted.status_code == 200, restarted.text
            again = agent.receive_json()
            assert again["text"] == render["text"]

        new = run_db(backend.db.db.generation_jobs.find_one({"_id": ObjectId(restarted.json()["job_id"])}))
        assert new["restart_of"] == str(job["_id"])
        assert job_by_ref(backend, render["request_id"])["restarted_as"] == restarted.json()["job_id"]
        # Once.
        assert support.post(f"/api/admin/jobs/{job['_id']}/restart", json={}).status_code == 409
        entry = run_db(backend.db.db.admin_audit.find_one({"action": "job.restart",
                                                            "target.job_id": str(job["_id"])}))
        assert entry and entry["reason"] == "test"

    def test_the_silent_filter(self, backend, account, client, new_user, agent_secret):
        new_user()
        render = ask_video(client, agent_secret, {
            "status": "complete", "text": "Жауап", "video_path": "rendered_j2.mp4", "has_audio": False})
        support = account(staff="support")
        silent = support.get("/api/admin/jobs", params={"silent": "true"}).json()["items"]
        assert str(job_by_ref(backend, render["request_id"])["_id"]) in {i["id"] for i in silent}
        assert all(i["has_audio"] is False for i in silent)

    def test_teachers_do_not_see_tasks(self, account):
        assert account().get("/api/admin/jobs").status_code == 404


class TestHealthAndMetrics:
    def test_the_system_page_shows_the_heartbeat(self, backend, account, client, agent_secret):
        support = account(staff="support")
        with client.websocket_connect("/ws/agent") as agent:
            agent.send_json({"type": "auth", "token": agent_secret, "features": ["ack", "heartbeat"]})
            assert agent.receive_json()["type"] == "auth_ok"
            agent.send_json({"type": "heartbeat", "busy": True, "queue": 3, "held": 0, "uptime_sec": 50})
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                state = support.get("/api/admin/system").json()
                if state["agent"]["heartbeat"]:
                    break
                time.sleep(0.05)
        assert state["agent"]["connected"] is True
        assert state["agent"]["heartbeat"]["queue"] == 3 and state["agent"]["heartbeat"]["busy"] is True
        assert state["disk"]["total"] and "videos" in state["queue"]

    def test_metrics_are_the_admins(self, backend, account):
        assert account(staff="support").get("/api/admin/metrics").status_code == 403

    def test_azure_characters_and_the_funnel(self, backend, account):
        from app.services import jobs

        ref = f"az-{uuid.uuid4().hex}"
        run_db(jobs.start("video", "u", ref))
        run_db(jobs.finish(ref, ok=True, video=True, tts_chars=1234))
        teacher = account()
        admin = account(staff="admin")
        before = admin.get("/api/admin/metrics").json()
        assert before["azure"]["chars"] >= 1234 and before["azure"]["limit"] == 500000
        assert before["funnel"]["registered"] >= 2  # the teacher and the admin's own account
        run_db(backend.db.db.users.update_one({"_id": ObjectId(teacher.user["id"])}, {"$set": {
            "trial": {"activated_at": datetime.now(timezone.utc), "used": {"videos": 2}, "bonus": {}}}}))
        after = admin.get("/api/admin/metrics").json()["funnel"]
        assert after["trial_spent"] == before["funnel"]["trial_spent"] + 1
        assert after["trial_used"] == before["funnel"]["trial_used"] + 1


class TestDeletion:
    def test_deleting_the_account_strips_its_tasks(self, backend, account, documents):
        teacher = account()
        teacher.post("/api/lesson-plans", json=PLAN_REQUEST)
        user_id = teacher.user["id"]
        assert teacher.delete("/api/auth/account").status_code in (200, 204)
        assert run_db(backend.db.db.generation_jobs.count_documents({"user_id": user_id})) == 0
