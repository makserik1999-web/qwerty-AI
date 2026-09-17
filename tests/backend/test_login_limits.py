"""The sign-in and sign-up limits, held against somebody who knows the headers.

Two holes, both of which left the limits in place and doing nothing:

  THE ADDRESS WAS THE CLIENT'S TO CHOOSE. The per-IP key was the first entry of
  X-Forwarded-For, and nginx appends the real peer to whatever the client sent
  under that name - so the first entry is invented by the client. A made-up
  address per request was a fresh budget per request.

  A SUCCESS CLEARED THE ADDRESS. Signing in reset the per-IP budget, so anyone
  with an account of their own could wipe it between guesses at other people's.

Every request here carries X-Real-IP, which is what nginx sets, and a unique
one per test: the limiters live in process memory for the whole run.
"""

import uuid

import pytest


def _ip() -> str:
    raw = uuid.uuid4().int
    return f"10.{raw % 250}.{(raw >> 8) % 250}.{(raw >> 16) % 250 + 1}"


def _email() -> str:
    return f"login{uuid.uuid4().hex[:10]}@school.kz"


@pytest.fixture
def limits(backend):
    from app.security import ratelimit

    return ratelimit


def _login(client, ip, email, password="wrong-password", spoof=None):
    headers = {"X-Real-IP": ip}
    if spoof:
        headers["X-Forwarded-For"] = f"{spoof}, {ip}"
    return client.post("/api/auth/login", json={"email": email, "password": password},
                       headers=headers)


def _signup(client, ip, email, spoof=None):
    headers = {"X-Real-IP": ip}
    if spoof:
        headers["X-Forwarded-For"] = f"{spoof}, {ip}"
    return client.post("/api/auth/signup",
                       json={"email": email, "password": "password123"},
                       headers=headers)


# ------------------------------------------------------------ which address --


class TestWhichAddressIsTrusted:
    def _request(self, headers, host="172.18.0.9"):
        from starlette.requests import Request

        return Request({
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (host, 50000),
        })

    def test_the_address_nginx_set_wins(self, limits):
        request = self._request({"X-Real-IP": "203.0.113.7",
                                 "X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
        assert limits._client_ip(request) == "203.0.113.7"

    def test_the_first_forwarded_entry_is_never_used(self, limits):
        """That entry is whatever the client wrote. nginx adds the real peer
        at the END."""
        request = self._request({"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
        assert limits._client_ip(request) == "203.0.113.7"

    def test_with_no_proxy_headers_it_is_the_peer(self, limits):
        assert limits._client_ip(self._request({})) == "172.18.0.9"


# ------------------------------------------------------------------ sign-in --


class TestSigningIn:
    def test_an_invented_forwarded_address_does_not_buy_more_attempts(
            self, client, limits, monkeypatch):
        monkeypatch.setattr(limits.login_ip_limiter, "max_attempts", 3)
        ip = _ip()

        # A different account each time, so only the address budget is spent.
        for n in range(3):
            assert _login(client, ip, _email(), spoof=f"6.6.6.{n}").status_code == 401

        assert _login(client, ip, _email(), spoof="6.6.6.99").status_code == 429

    def test_a_success_does_not_clear_the_address(self, client, limits, monkeypatch):
        monkeypatch.setattr(limits.login_ip_limiter, "max_attempts", 3)
        ip = _ip()
        mine = _email()
        assert _signup(client, ip, mine).status_code == 201

        assert _login(client, ip, _email()).status_code == 401
        assert _login(client, ip, _email()).status_code == 401
        assert _login(client, ip, mine, password="password123").status_code == 200
        assert _login(client, ip, _email()).status_code == 401

        assert _login(client, ip, _email()).status_code == 429

    def test_successes_do_not_spend_the_address(self, client, limits, monkeypatch):
        """A classroom is one address. Thirty students signing in correctly
        must not lock out the thirty-first."""
        monkeypatch.setattr(limits.login_ip_limiter, "max_attempts", 3)
        ip = _ip()
        mine = _email()
        assert _signup(client, ip, mine).status_code == 201

        for _ in range(6):
            assert _login(client, ip, mine, password="password123").status_code == 200

    def test_capitals_do_not_make_a_second_account_budget(self, client, limits):
        """Addresses are matched case-insensitively, so their budget is too."""
        target = _email()
        spellings = [target, target.upper(), target.capitalize(),
                     target.swapcase(), target.title()]

        # A fresh address per attempt, so this measures the account alone.
        for spelling in spellings[:limits.login_limiter.max_attempts]:
            assert _login(client, _ip(), spelling).status_code == 401

        assert _login(client, _ip(), target.replace("login", "LOGIN")).status_code == 429


# ------------------------------------------------------------------ sign-up --


class TestSigningUp:
    def test_an_invented_forwarded_address_does_not_buy_more_accounts(
            self, client, limits, monkeypatch):
        monkeypatch.setattr(limits.signup_limiter, "max_attempts", 2)
        ip = _ip()

        assert _signup(client, ip, _email(), spoof="6.6.6.1").status_code == 201
        assert _signup(client, ip, _email(), spoof="6.6.6.2").status_code == 201
        assert _signup(client, ip, _email(), spoof="6.6.6.3").status_code == 429
