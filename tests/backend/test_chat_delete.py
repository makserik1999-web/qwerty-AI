"""Removing a question from the history, and shipping the code that does it.

Two things asked for on the same screen, and they belong together: the delete
itself, and the reason the previous fix to that screen was live on the server
and absent in the browser.

The history is read over REST (GET /api/chats), so deleting an entry from it is
addressed the same way. The operation is not new - the `delete_chat` socket
frame has always had it - but a socket that may not be open is the wrong thing
to reach for when the list came from a plain request.

Chats are made over the socket, so these tests reach for the repository to
create one, the way test_auth_roles does.
"""

import asyncio
import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf.template"


def run_db(coro):
    """Await one coroutine from a synchronous test (see test_auth_roles)."""
    return asyncio.run(coro)


@pytest.fixture
def a_chat(client, new_user, backend):
    """One signed-in user with one chat and one message in it."""
    from app.repositories.chats import create_chat
    from app.repositories.messages import save_message

    user = new_user()
    client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": user["password"]},
    )
    chat = run_db(create_chat(user["id"], "почему лед не тает в воде"))
    run_db(save_message(chat["id"], "user", "почему лед не тает в воде"))
    return chat["id"]


# ------------------------------------------------------------ the endpoint --


class TestDeletingAChat:
    def test_it_is_gone_from_the_list(self, client, a_chat):
        listed = client.get("/api/chats").json()["items"]
        assert any(c["id"] == a_chat for c in listed), "not there to begin with"

        assert client.delete(f"/api/chats/{a_chat}").status_code == 200

        listed = client.get("/api/chats").json()["items"]
        assert not any(c["id"] == a_chat for c in listed)

    def test_reading_it_afterwards_is_a_404(self, client, a_chat):
        client.delete(f"/api/chats/{a_chat}")
        assert client.get(f"/api/chats/{a_chat}").status_code == 404

    def test_its_messages_go_with_it(self, client, backend, a_chat):
        """A chat whose messages outlive it leaves the question readable by
        exactly the deletion that was meant to remove it."""
        assert run_db(backend.db.db.messages.count_documents({"chat_id": a_chat})) == 1

        client.delete(f"/api/chats/{a_chat}")

        assert run_db(backend.db.db.messages.count_documents({"chat_id": a_chat})) == 0

    def test_deleting_it_twice_is_a_404_not_a_second_success(self, client, a_chat):
        """Saying "deleted" about something that was not there hides a bug."""
        assert client.delete(f"/api/chats/{a_chat}").status_code == 200
        assert client.delete(f"/api/chats/{a_chat}").status_code == 404

    def test_a_malformed_id_is_rejected_before_the_database(self, client, a_chat):
        assert client.delete("/api/chats/not-an-id").status_code == 400

    def test_somebody_elses_chat_is_not_deletable(self, client, new_user, a_chat):
        """Ownership is checked inside the delete: the id is matched together
        with the user, so another account's chat is not found rather than
        removed. Without that, a chat id is enough to destroy it."""
        other = new_user()
        client.post(
            "/api/auth/login",
            json={"username": other["username"], "password": other["password"]},
        )

        assert client.delete(f"/api/chats/{a_chat}").status_code == 404

    def test_it_needs_a_session(self, anon_client, a_chat):
        assert anon_client.delete(f"/api/chats/{a_chat}").status_code == 401


# ------------------------------------------------- shipping the code at all --


class TestIndexHtmlIsNotCached:
    """Why the previous fix to this screen did not reach the browser.

    index.html carries the hashed names of the bundles. The assets are
    immutable for a year precisely because their names change - and this file
    is the only thing that says which names to ask for. A stale copy pins the
    browser to the old build, so a deploy lands on the server and nothing
    changes on the screen.

    It carried no Cache-Control at all, which is not "do not cache": with no
    directive the browser is free to guess, and it guesses from Last-Modified.
    """

    @pytest.fixture(scope="class")
    def index_block(self) -> str:
        conf = TEMPLATE.read_text(encoding="utf-8")
        found = re.search(r"location\s*=\s*/index\.html\s*\{(.*?)\}", conf, re.DOTALL)
        assert found, "index.html is served with no cache directive of its own"
        return found.group(1)

    def test_it_is_told_not_to_cache(self, index_block):
        assert "expires -1" in index_block, index_block

    def test_it_does_not_use_add_header(self, index_block):
        """The trap that would make this fix worse than the bug.

        nginx inherits add_header from the enclosing level ONLY when the level
        defines none of its own. An `add_header Cache-Control` here would drop
        the CSP, the frame-ancestors and the nosniff from the one response that
        is an actual document - silently, and on the page that most needs them.
        """
        assert "add_header" not in index_block, (
            "add_header here replaces every inherited security header; use expires"
        )

    @pytest.fixture(scope="class")
    def assets_block(self) -> str:
        conf = TEMPLATE.read_text(encoding="utf-8")
        found = re.search(
            r"location\s*~\*\s*\\\.\(js\|css[^{]*\{(.*?)\}", conf, re.DOTALL
        )
        assert found, "the hashed-asset location is gone"
        return found.group(1)

    def test_the_hashed_assets_are_still_immutable(self, assets_block):
        """The other half of the pair. Caching them for a year is correct
        BECAUSE index.html is not cached; break that and this becomes the bug."""
        assert "immutable" in assets_block
        assert "max-age=31536000" in assets_block

    def test_the_assets_did_not_lose_their_nosniff(self, assets_block):
        """The same inheritance trap, on the other side of it.

        This block DOES set add_header - it has to, for `immutable` - and that
        dropped every server header from these responses. Measured on the
        running stack: scripts came back with no X-Content-Type-Options at all,
        which is the one header that stops a browser MIME-sniffing a script.
        So it is repeated here, and this test is why it stays repeated.
        """
        assert "X-Content-Type-Options" in assets_block, (
            "add_header in this block drops the inherited nosniff; repeat it here"
        )

    def test_the_assets_set_cache_control_once(self, assets_block):
        """`expires` and `add_header Cache-Control` together put two of them on
        one response. They did, until this."""
        assert "expires" not in assets_block, assets_block
