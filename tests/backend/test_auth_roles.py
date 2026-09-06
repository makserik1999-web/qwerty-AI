"""Who someone is, decided by the server rather than by the browser.

The prototype interface worked out the role from the address that was typed
into it - anything containing "teacher" got the six-tab shell, anything else
got three. That is a demo affordance, and it was the only thing standing
between a student and the teacher screens. Roles now live on the account.

Nothing here checks that a teacher teaches; the role is self-declared at
signup and that is the whole of it for now. What these tests hold is narrower
and more useful: the value is stored once, read from the account on every
later request, defaulted downwards when it is missing or unrecognised, and
cannot be changed by any route a signed-in person can reach.

The rest is the shape the new interface actually sends - a name, an email and
no username at all - against a backend whose accounts have always been keyed
on a username.

Every address here is made unique. The in-memory Mongo is session-scoped, so
a fixed one would collide with whichever test ran first and turn a real
assertion into a duplicate-signup error.
"""

import asyncio
import uuid

import pytest


@pytest.fixture
def address():
    """A unique address, optionally built around a chosen local part."""

    def _make(stem: str = "user") -> str:
        return f"{stem}{uuid.uuid4().hex[:8]}@school.kz"

    return _make


@pytest.fixture
def signup(client, address):
    """Sign up the way the new interface does: no username, but a role."""

    def _make(email=None, password="password123", **extra):
        body = {"email": email or address(), "password": password, **extra}
        return client.post("/api/auth/signup", json=body)

    return _make


def run_db(coro):
    """Await one coroutine from a synchronous test.

    The database under test is mongomock's in-memory client, which keeps its
    documents in plain dicts and is not bound to a loop - so a throwaway one
    is enough to read back what the endpoints wrote. The TestClient owns the
    loop the app runs on, which is why this cannot simply be an async test.
    """
    return asyncio.run(coro)


# ------------------------------------------------------- the username gap --


class TestTheUsernameIsDerived:
    """The interface never asks for one, and everything is keyed on it."""

    def test_signing_up_without_a_username_works(self, signup):
        response = signup(name="Айсұлу", role="teacher")
        assert response.status_code == 201, response.text

    def test_the_handle_comes_from_the_address(self, signup, address):
        email = address("aisulu")
        local = email.split("@")[0]

        assert signup(email).json()["user"]["username"] == local

    def test_punctuation_becomes_underscores(self, signup, address):
        """A local part is allowed characters a username is not."""
        stem = uuid.uuid4().hex[:6]
        email = f"ais.ulu-b{stem}@school.kz"

        assert signup(email).json()["user"]["username"] == f"ais_ulu_b{stem}"

    def test_two_people_with_the_same_local_part_both_get_in(self, client, address):
        local = f"aisulu{uuid.uuid4().hex[:6]}"
        first = client.post(
            "/api/auth/signup", json={"email": f"{local}@school.kz", "password": "password123"}
        ).json()["user"]
        second = client.post(
            "/api/auth/signup", json={"email": f"{local}@lyceum.kz", "password": "password123"}
        ).json()["user"]

        assert first["username"] == local
        assert second["username"] == f"{local}2"
        assert first["id"] != second["id"]

    def test_a_local_part_with_nothing_usable_still_signs_up(self, signup):
        """Cyrillic addresses exist, and _USERNAME_RE is ASCII only."""
        from app.config import _USERNAME_RE

        response = signup(f"әйгүл{uuid.uuid4().hex[:4]}@school.kz")

        assert response.status_code == 201, response.text
        assert _USERNAME_RE.fullmatch(response.json()["user"]["username"])

    def test_a_cyrillic_address_does_not_become_bare_digits(self, signup):
        """Found live, and the regex check above had let it through.

        "Айсұлу.Б70390@school.kz" lost every letter to the substitution and
        produced the username "70390" - which matches _USERNAME_RE perfectly
        well and reads as a database id. Asserting only that a value is valid
        is how a test passes while the value is useless.
        """
        digits = uuid.uuid4().int % 10**6
        user = signup(f"Айсұлу.Б{digits}@school.kz").json()["user"]

        assert not user["username"].isdigit(), "a handle nobody can recognise"
        assert user["username"] == f"user{digits}"

    def test_a_username_that_is_sent_is_still_honoured(self, client):
        """The old sign-in screen and every existing test send one."""
        handle = f"kanat_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/auth/signup", json={"username": handle, "password": "password123"}
        )

        assert response.json()["user"]["username"] == handle

    def test_a_malformed_username_is_still_rejected(self, client):
        """Deriving one must not turn a bad username into a silent replacement."""
        response = client.post(
            "/api/auth/signup", json={"username": "ab", "password": "password123"}
        )
        assert response.status_code == 400

    def test_neither_identifier_is_a_400(self, client):
        assert client.post("/api/auth/signup", json={"password": "password123"}).status_code == 400


# -------------------------------------------------------------- the role --


class TestTheRoleIsNotTakenOnTrust:
    def test_a_teacher_is_recorded_as_one(self, signup):
        assert signup(role="teacher").json()["user"]["role"] == "teacher"

    def test_no_role_means_student(self, signup):
        assert signup().json()["user"]["role"] == "student"

    @pytest.mark.parametrize(
        "sent", ["", "admin", "student; drop", "ұстаз", "x" * 200, None, "teacherr", "tea cher"]
    )
    def test_anything_unrecognised_falls_back_to_student(self, signup, sent):
        """The fallback points at the lesser privilege, never the greater.

        Falling back to teacher would mean a typo, an old client or a truncated
        field silently hands out the paid screens.
        """
        assert signup(role=sent).json()["user"]["role"] == "student"

    @pytest.mark.parametrize("sent", ["Teacher", "TEACHER ", " teacher"])
    def test_the_word_is_recognised_however_it_is_cased(self, signup, sent):
        """Only unrecognised words fall back; a capital is not a different role."""
        assert signup(role=sent).json()["user"]["role"] == "teacher"

    def test_an_account_from_before_roles_reads_as_a_student(self, backend):
        """No field at all is the same as an unrecognised one, and just as safe.

        Checked against the payload builder directly rather than through a
        doctored database row: this is the only place a role is read on the
        way out, so it is the only place the fallback has to hold.
        """
        from app.security.sessions import _user_payload
        from bson import ObjectId

        payload = _user_payload({"_id": ObjectId(), "username": "old_account"})

        assert payload["role"] == "student"
        assert payload["name"] == "old_account"

    def test_the_name_falls_back_to_the_handle(self, signup, address):
        """Every screen greets someone by name, so it can never be empty."""
        email = address("kanat")
        user = signup(email).json()["user"]

        assert user["name"] == email.split("@")[0]

    def test_the_name_is_kept_as_given(self, signup):
        assert signup(name="  Айсұлу   Бекова ").json()["user"]["name"] == "Айсұлу Бекова"


# ------------------------------------------------------------ signing in --


class TestSigningInWithAnEmail:
    def test_the_address_works(self, signup, client, address):
        email = address()
        signup(email)
        client.post("/api/auth/logout")

        response = client.post(
            "/api/auth/login", json={"email": email, "password": "password123"}
        )

        assert response.status_code == 200, response.text
        assert client.get("/api/auth/me").status_code == 200

    def test_capitals_are_the_same_account(self, signup, client, address):
        """Typed with a capital on a phone keyboard is not a different person."""
        email = address("Aisulu")
        signup(email)
        client.post("/api/auth/logout")

        response = client.post(
            "/api/auth/login", json={"email": email.lower(), "password": "password123"}
        )

        assert response.status_code == 200, response.text

    def test_the_username_still_works(self, client, new_user):
        """Existing accounts have no email at all."""
        made = new_user()
        client.post("/api/auth/logout")

        response = client.post(
            "/api/auth/login",
            json={"username": made["username"], "password": made["password"]},
        )

        assert response.status_code == 200

    def test_a_wrong_password_is_still_refused(self, signup, client, address):
        email = address()
        signup(email)
        client.post("/api/auth/logout")

        response = client.post(
            "/api/auth/login", json={"email": email, "password": "wrongpassword"}
        )

        assert response.status_code == 401

    def test_an_unknown_address_is_refused(self, client, address):
        response = client.post(
            "/api/auth/login", json={"email": address(), "password": "password123"}
        )
        assert response.status_code == 401

    def test_the_role_survives_a_new_session(self, signup, client, address):
        """The point of storing it: the browser is not asked what it is."""
        email = address()
        signup(email, role="teacher")
        client.post("/api/auth/logout")
        client.post("/api/auth/login", json={"email": email, "password": "password123"})

        assert client.get("/api/auth/me").json()["user"]["role"] == "teacher"


# ------------------------------------------------------------ the profile --


class TestTheProfile:
    def test_the_name_can_be_changed(self, signup, client):
        signup(name="Айсұлу")

        response = client.patch("/api/auth/profile", json={"name": "Айсұлу Бекова"})

        assert response.status_code == 200, response.text
        assert response.json()["user"]["name"] == "Айсұлу Бекова"
        assert client.get("/api/auth/me").json()["user"]["name"] == "Айсұлу Бекова"

    def test_the_email_can_be_changed(self, signup, client, address):
        signup()
        fresh = address()

        response = client.patch("/api/auth/profile", json={"email": fresh})

        assert response.status_code == 200, response.text
        assert response.json()["user"]["email"] == fresh

    def test_the_new_address_is_usable_to_sign_in(self, signup, client, address):
        signup()
        fresh = address()
        client.patch("/api/auth/profile", json={"email": fresh})
        client.post("/api/auth/logout")

        response = client.post(
            "/api/auth/login", json={"email": fresh, "password": "password123"}
        )

        assert response.status_code == 200, response.text

    def test_someone_elses_address_is_refused(self, signup, client, address):
        taken = address()
        signup(taken)
        client.post("/api/auth/logout")
        signup()

        assert client.patch("/api/auth/profile", json={"email": taken}).status_code == 409

    def test_the_role_cannot_be_changed_here(self, signup, client):
        """The one thing this endpoint must not accept.

        The settings screen shows the role as a badge, not a control - but the
        interface declining to offer something is not a defence, because the
        request can be made without it.
        """
        signup(role="student")

        client.patch("/api/auth/profile", json={"name": "S", "role": "teacher"})

        assert client.get("/api/auth/me").json()["user"]["role"] == "student"

    def test_the_username_cannot_be_changed_here(self, signup, client):
        """Chats, sessions and the admin allowlist are keyed on it."""
        before = signup().json()["user"]["username"]

        client.patch("/api/auth/profile", json={"username": "admin"})

        assert client.get("/api/auth/me").json()["user"]["username"] == before

    def test_an_empty_name_is_refused(self, signup, client):
        signup()
        assert client.patch("/api/auth/profile", json={"name": "   "}).status_code == 400

    def test_a_malformed_address_is_refused(self, signup, client):
        signup()
        assert client.patch("/api/auth/profile", json={"email": "not-an-email"}).status_code == 400

    def test_it_needs_a_session(self, anon_client):
        assert anon_client.patch("/api/auth/profile", json={"name": "X"}).status_code == 401


# ------------------------------------------------------ deleting it all --


class TestDeletingTheAccount:
    def test_the_session_stops_working(self, signup, client):
        signup()

        assert client.delete("/api/auth/account").status_code == 200
        assert client.get("/api/auth/me").status_code == 401

    def test_signing_in_again_is_impossible(self, signup, client, address):
        email = address()
        signup(email)
        client.delete("/api/auth/account")

        response = client.post(
            "/api/auth/login", json={"email": email, "password": "password123"}
        )

        assert response.status_code == 401

    def test_the_address_is_free_again(self, signup, client, address):
        email = address()
        signup(email)
        client.delete("/api/auth/account")

        assert signup(email).status_code == 201

    def test_the_chats_and_their_messages_go_too(self, signup, client, backend):
        """Chats are made over the socket, so this one reaches for the database.

        Worth the reach: an account whose rows outlive it leaves someone's
        questions readable by whoever the deletion was supposed to protect
        them from, and no HTTP route can show that once the session is gone.
        """
        from app.repositories.chats import create_chat
        from app.repositories.messages import save_message

        user_id = signup().json()["user"]["id"]

        chat = run_db(create_chat(user_id, "физика"))
        chat_id = chat["id"]
        run_db(save_message(chat_id, "user", "что такое инерция"))

        assert client.get("/api/chats").json(), "the chat was not visible to begin with"

        assert client.delete("/api/auth/account").status_code == 200

        assert run_db(backend.db.db.chats.count_documents({"user_id": user_id})) == 0
        assert run_db(backend.db.db.messages.count_documents({"chat_id": chat_id})) == 0
        assert run_db(backend.db.db.sessions.count_documents({"user_id": user_id})) == 0

    def test_it_needs_a_session(self, anon_client):
        assert anon_client.delete("/api/auth/account").status_code == 401
