from __future__ import annotations

from unittest.mock import Mock

import pytest

from ncss_harves.auth import AuthManager, CredentialsRequired
from ncss_harves.credentials import Credentials
from ncss_harves.errors import AuthenticationRequired


class FakeSession:
    def __init__(self, number: int) -> None:
        self.number = number
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.login_credentials: Credentials | None = None
        self.export_count = 0
        self.closed = False

    def __enter__(self) -> "FakeBrowser":
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True

    def establish_login(self, credentials: Credentials) -> None:
        self.login_credentials = credentials

    def cookies(self) -> tuple[object, ...]:
        self.export_count += 1
        return ()

    def user_agent(self) -> str:
        return f"ua-{self.export_count}"


class FakeVerifier:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.sessions: list[FakeSession] = []

    def __call__(self, session: FakeSession) -> "FakeVerifier":
        self.sessions.append(session)
        return self

    def verify_authenticated(self) -> bool:
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return bool(result)


class FakeCredentialStore:
    def __init__(self, saved: Credentials | None = None) -> None:
        self.saved = saved
        self.save_calls: list[Credentials] = []

    def load(self) -> Credentials | None:
        return self.saved

    def save(self, credentials: Credentials) -> None:
        self.saved = credentials
        self.save_calls.append(credentials)


def make_auth(results: list[object], saved: Credentials | None = None):
    browser = FakeBrowser()
    verifier = FakeVerifier(results)
    store = FakeCredentialStore(saved)
    sleeper = Mock()
    sessions: list[FakeSession] = []

    def session_factory(_cookies: object, _user_agent: str) -> FakeSession:
        session = FakeSession(len(sessions) + 1)
        sessions.append(session)
        return session

    auth = AuthManager(
        browser_factory=lambda _stop_requested: browser,
        credential_store=store,  # type: ignore[arg-type]
        client_factory=verifier,
        session_factory=session_factory,
        sleeper=sleeper,
        output=Mock(),
    )
    return auth, browser, verifier, store, sleeper, sessions


def test_cookie_validation_recollects_once_after_five_seconds() -> None:
    auth, browser, _, store, sleeper, sessions = make_auth([AuthenticationRequired("expired"), True])
    credentials = Credentials("u", "p")

    session = auth.establish(credentials)

    assert session is auth.current_session
    assert browser.export_count == 2
    assert browser.closed is True
    assert sessions[0].closed is True
    assert sessions[1].closed is False
    sleeper.assert_called_once_with(5.0)
    assert store.save_calls == [credentials]


def test_second_failure_requests_new_credentials_and_keeps_old_file() -> None:
    old = Credentials("old", "valid")
    auth, browser, _, store, sleeper, sessions = make_auth([False, False], saved=old)

    with pytest.raises(CredentialsRequired, match="第 6 页"):
        auth.establish(Credentials("new", "wrong"))

    assert browser.closed is True
    assert sleeper.call_count == 1
    assert all(session.closed for session in sessions)
    assert store.saved == old
    assert store.save_calls == []
    assert auth.current_session is None


def test_saved_credentials_are_required_for_automatic_login() -> None:
    auth, *_ = make_auth([True], saved=None)

    with pytest.raises(CredentialsRequired, match="加密账密"):
        auth.establish_saved()


def test_saved_credentials_are_used() -> None:
    saved = Credentials("saved-user", "saved-password")
    auth, browser, _, store, _, _ = make_auth([True], saved=saved)

    auth.establish_saved()

    assert browser.login_credentials == saved
    assert store.save_calls == [saved]


def test_verified_session_atomically_replaces_and_closes_old_session() -> None:
    auth, _, verifier, _, _, sessions = make_auth([True, True])
    first = auth.establish(Credentials("u1", "p1"))
    second = auth.establish(Credentials("u2", "p2"))

    assert auth.current_session is second
    assert first.closed is True
    assert second.closed is False
    assert verifier.sessions == sessions


def test_close_current_session_is_idempotent() -> None:
    auth, *_ = make_auth([True])
    session = auth.establish(Credentials("u", "p"))

    auth.close()
    auth.close()

    assert session.closed is True
    assert auth.current_session is None


def test_saved_login_passes_task_stop_callback_to_browser_factory() -> None:
    callbacks = []
    browser = FakeBrowser()
    verifier = FakeVerifier([True])
    store = FakeCredentialStore(Credentials("u", "p"))
    auth = AuthManager(
        browser_factory=lambda callback: callbacks.append(callback) or browser,
        credential_store=store,  # type: ignore[arg-type]
        client_factory=verifier,
        session_factory=lambda _cookies, _ua: FakeSession(1),
        output=Mock(),
    )
    stop_requested = lambda: True

    auth.establish_saved(stop_requested=stop_requested)

    assert callbacks == [stop_requested]
