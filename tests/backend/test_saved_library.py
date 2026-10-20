"""A person's own library, which is not the answer cache.

Two things share the word "library" in this product and nothing else. This
file is about keeping them apart, and about a saved explanation still being
there tomorrow - which it was not, because the Library screen was reading a
list built in the browser and thrown away on reload.

THE NAME. `library_entries` is the global answer cache: one row serves
everyone who asked the same question. `saved_explanations` is private, one row
per person. If those ever met, "remove from my library" would take an answer
away from strangers and a search would show them other people's questions. The
tests at the bottom hold the wall between them.

THE SNAPSHOT. A saved row copies the explanation rather than pointing at the
message. A pointer is smaller and stays in step with edits, but it also means
tidying up a chat silently empties somebody's library - which is not a trade a
person would make knowingly. The video is referenced rather than copied,
because videos are shared: a saved answer whose file has been collected still
reads, it just no longer plays.
"""

import pytest


@pytest.fixture
def answered(client, new_user, agent_secret):
    """A user with one answered question, and the id of the answer.

    Goes through the real path - socket, agent, saved message - because the
    thing being tested is saving an answer by its id, and a hand-written
    message document would not prove that works.
    """

    def _make(question="что такое инерция", answer="инерция это...", video="rendered.mp4"):
        new_user()
        with client.websocket_connect("/ws/agent") as agent:
            agent.send_json({"type": "auth", "token": agent_secret})
            assert agent.receive_json().get("type") == "auth_ok"

            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "create_chat", "data": {"title": question}})
                chat_id = ws.receive_json()["data"]["id"]
                ws.send_json({
                    "type": "user_message",
                    "data": {"chat_id": chat_id, "prompt": question},
                })
                assert ws.receive_json().get("type") == "message_received"

                request_id = agent.receive_json()["request_id"]
                agent.send_json({
                    "request_id": request_id, "status": "complete",
                    "text": answer, "video_path": video,
                })
                reply = ws.receive_json()

        return {
            "message_id": reply["data"]["message_id"],
            "chat_id": chat_id,
            "question": question,
            "answer": answer,
        }

    return _make


def _save(client, made, **extra):
    return client.post("/api/library", json={
        "message_id": made["message_id"], "question": made["question"],
        "subject": "physics", "lang": "kk", **extra,
    })


# ------------------------------------------------------- it stays saved --


class TestItSurvivesAReload:
    """The bug the whole phase exists for.

    Saving put a card in a list that lived in the browser. It looked saved,
    and it was gone on the next visit - the worst shape of a bug, because
    nothing reports it and the person only finds out when they go looking for
    something they thought they had.
    """

    def test_a_saved_answer_is_listed(self, client, answered):
        made = answered()

        assert _save(client, made).status_code == 201
        items = client.get("/api/library").json()["items"]

        assert [i["question"] for i in items] == ["что такое инерция"]

    async def test_it_lives_on_the_server(self, client, answered, backend):
        """Where it was not before: the list was built in the browser.

        Checked in the database rather than by reading the list back, because
        a list that came from the same process that wrote it proves nothing
        about surviving a reload.
        """
        made = answered()
        _save(client, made)

        rows = await backend.db.db.saved_explanations.count_documents(
            {"message_id": made["message_id"]}
        )
        assert rows == 1

    def test_the_title_falls_back_to_the_question(self, client, answered):
        """A card titled with the first line of the answer is unrecognisable."""
        made = answered(question="неге аспан көк?", answer="жарық шашырайды...")

        saved = client.post("/api/library", json={"message_id": made["message_id"]}).json()

        assert saved["question"] == "неге аспан көк?"

    def test_the_explanation_comes_back_whole(self, client, answered):
        made = answered(answer="инерция - бұл дененің...", video="v1.mp4")
        _save(client, made)

        item = client.get("/api/library").json()["items"][0]

        assert item["markdown"] == "инерция - бұл дененің..."
        assert item["videoUrl"] == "/media/v1.mp4"

    def test_saving_twice_is_one_card(self, client, answered):
        """Two tabs, or a double click. Not an error, and not two cards."""
        made = answered()
        first = _save(client, made).json()
        again = _save(client, made)

        assert again.status_code in (200, 201)
        assert again.json()["id"] == first["id"]
        assert len(client.get("/api/library").json()["items"]) == 1


class TestItIsASnapshot:
    def test_deleting_the_chat_leaves_the_card(self, client, answered):
        """Tidying up a chat must not empty a library.

        This is why the row copies the explanation instead of pointing at it.
        """
        made = answered()
        _save(client, made)

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "delete_chat", "data": {"chat_id": made["chat_id"]}})
            assert ws.receive_json()["data"]["success"] is True

        items = client.get("/api/library").json()["items"]

        assert len(items) == 1
        assert items[0]["markdown"] == made["answer"]


# ---------------------------------------------------------- whose it is --


class TestOnePersonsLibrary:
    def test_i_cannot_save_someone_elses_answer(self, client, answered):
        """A guessed message id must not put a stranger's answer in my library."""
        made = answered()
        client.post("/api/auth/logout")
        answered()  # a different person

        assert _save(client, made).status_code == 404

    def test_i_do_not_see_anyone_elses(self, client, answered):
        made = answered()
        _save(client, made)
        client.post("/api/auth/logout")
        answered()

        assert client.get("/api/library").json()["items"] == []

    def test_i_cannot_rename_theirs(self, client, answered):
        made = answered()
        saved_id = _save(client, made).json()["id"]
        client.post("/api/auth/logout")
        answered()

        assert client.patch(
            f"/api/library/{saved_id}", json={"question": "моё"}
        ).status_code == 404

    def test_i_cannot_delete_theirs(self, client, answered):
        made = answered()
        saved_id = _save(client, made).json()["id"]
        client.post("/api/auth/logout")
        answered()

        assert client.delete(f"/api/library/{saved_id}").status_code == 404

    def test_it_needs_a_session(self, anon_client):
        assert anon_client.get("/api/library").status_code == 401


class TestOnlyAnswersAreSavable:
    def test_my_own_question_is_not_an_answer(self, client, answered, backend):
        """The Save button sits under an explanation, but the id is a parameter."""
        made = answered()
        history = client.get(f"/api/chats/{made['chat_id']}").json()
        question_id = next(m["id"] for m in history["messages"] if m["role"] == "user")

        response = client.post("/api/library", json={"message_id": question_id})

        assert response.status_code == 404

    @pytest.mark.parametrize("bad", ["", "not-an-id", "000000000000000000000000"])
    def test_a_nonsense_id_is_a_404(self, client, answered, bad):
        answered()
        assert client.post("/api/library", json={"message_id": bad}).status_code == 404


# ------------------------------------------------------------- editing --


class TestRenaming:
    def test_the_title_changes(self, client, answered):
        made = answered()
        saved_id = _save(client, made).json()["id"]

        renamed = client.patch(
            f"/api/library/{saved_id}", json={"question": "Инерция, 7 сынып"}
        ).json()

        assert renamed["question"] == "Инерция, 7 сынып"
        assert client.get("/api/library").json()["items"][0]["question"] == "Инерция, 7 сынып"

    def test_the_explanation_is_not_editable(self, client, answered):
        """A saved answer is a record of what was said, not a document."""
        made = answered(answer="как было сказано")
        saved_id = _save(client, made).json()["id"]

        client.patch(
            f"/api/library/{saved_id}",
            json={"question": "новое имя", "markdown": "как я хочу"},
        )

        assert client.get("/api/library").json()["items"][0]["markdown"] == "как было сказано"

    def test_an_empty_title_is_refused(self, client, answered):
        made = answered()
        saved_id = _save(client, made).json()["id"]

        assert client.patch(
            f"/api/library/{saved_id}", json={"question": "   "}
        ).status_code == 400


class TestRemoving:
    def test_the_card_goes(self, client, answered):
        made = answered()
        saved_id = _save(client, made).json()["id"]

        assert client.delete(f"/api/library/{saved_id}").status_code == 200
        assert client.get("/api/library").json()["items"] == []

    def test_the_answer_itself_stays_in_the_chat(self, client, answered):
        """Removing a bookmark is not deleting what it pointed at."""
        made = answered()
        saved_id = _save(client, made).json()["id"]
        client.delete(f"/api/library/{saved_id}")

        history = client.get(f"/api/chats/{made['chat_id']}").json()

        assert any(m["role"] == "assistant" for m in history["messages"])

    def test_removing_twice_is_a_404(self, client, answered):
        made = answered()
        saved_id = _save(client, made).json()["id"]
        client.delete(f"/api/library/{saved_id}")

        assert client.delete(f"/api/library/{saved_id}").status_code == 404


# --------------------------------------------- the wall against the cache --


class TestItIsNotTheAnswerCache:
    """The trap this phase was warned about, held in place.

    `library_entries` and `saved_explanations` are different collections with
    opposite access rules. These tests fail loudly if anybody wires one to the
    other - which is the kind of change that looks correct in review, because
    both are "the library".
    """

    async def test_removing_a_card_leaves_the_cached_answer(
        self, client, answered, backend
    ):
        """The file answers everyone who asked the same thing.

        If removing a personal card reached into the cache, one person tidying
        up would make the next asker wait two minutes for a render we already
        had.
        """
        from app.repositories.library import store_entry

        await store_entry(
            cache_key="shared-key", normalized="что такое инерция",
            educator_text="общий ответ", video_url="/media/shared.mp4",
            language="ru", pipeline_version="v2", variant="silent",
        )

        made = answered()
        saved_id = _save(client, made).json()["id"]
        client.delete(f"/api/library/{saved_id}")

        still_there = await backend.db.db.library_entries.find_one(
            {"cache_key": "shared-key"}
        )
        assert still_there, "removing a personal card reached into the shared cache"

    async def test_the_library_list_shows_nobody_elses_questions(
        self, client, answered, backend
    ):
        """The cache holds questions other people asked. A personal list
        showing them would be a leak, not a feature."""
        from app.repositories.library import store_entry

        await store_entry(
            cache_key="someone-else", normalized="чужой вопрос",
            educator_text="чужой ответ", video_url="/media/x.mp4",
            language="ru", pipeline_version="v2", variant="silent",
        )
        answered()

        items = client.get("/api/library").json()["items"]

        assert all(i["question"] != "чужой вопрос" for i in items)

    async def test_saving_does_not_write_to_the_cache(self, client, answered, backend):
        """A personal save is not a vote about what everybody should be served."""
        before = await backend.db.db.library_entries.count_documents({})
        made = answered()
        _save(client, made)
        after = await backend.db.db.library_entries.count_documents({})

        assert after == before

    def test_the_two_collections_are_named_apart(self, backend):
        """A reader of either file has to be told which one they are in."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "backend" / "app" / "repositories"
        cache = (root / "library.py").read_text(encoding="utf-8")
        personal = (root / "saved.py").read_text(encoding="utf-8")

        assert "saved.py" in cache, "the cache module does not point at the personal one"
        assert "library_entries" in personal, "the personal module does not warn about the cache"
