from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest

from ncss_harves.auth import CredentialsRequired
from ncss_harves.collector import Batch
from ncss_harves.credentials import Credentials
from ncss_harves.models import Job
from ncss_harves.service import ApplicationService
from ncss_harves.shutdown import ShutdownCoordinator


class FakeRepository:
    def __init__(self, events: list[str], *, initialized: bool) -> None:
        self.events = events
        self.initialized = initialized
        self.inserted: list[tuple[tuple[Job, ...], bool]] = []

    def initialize_schema(self) -> None:
        self.events.append("schema")

    def is_initialized(self) -> bool:
        return self.initialized

    def insert_batch(self, jobs, *, mark_initialized=False, commit_guard=None) -> int:
        self.events.append("commit")
        with commit_guard:
            self.inserted.append((tuple(jobs), mark_initialized))
            self.initialized = self.initialized or mark_initialized
        return len(jobs)

class FakeAuth:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.saved_results: list[object] = [object()]
        self.establish_results: list[object] = [object()]
        self.closed = False

    def establish_saved(self):
        self.events.append("login_saved")
        result = self.saved_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def establish(self, credentials: Credentials):
        self.events.append("login_interactive")
        result = self.establish_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def session(self):
        return object()

    def close(self) -> None:
        self.closed = True


class FakeCollector:
    def __init__(self, events: list[str]) -> None:
        self.events = events
    def collect_initial(self, _progress) -> Batch:
        self.events.append("initial_collect")
        return Batch((Job(job_id="initial"),), 1)


class FakeCoordinator:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def close(self) -> None:
        self.events.append("crawl_close")


class FakeHttpServer:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.stop = threading.Event()

    def serve_forever(self) -> None:
        self.events.append("http_start")
        self.stop.wait()

    def shutdown(self) -> None:
        self.events.append("http_stop")
        self.stop.set()

    def server_close(self) -> None:
        self.events.append("http_close")


def build_service(*, initialized: bool):
    events: list[str] = []
    repository = FakeRepository(events, initialized=initialized)
    auth = FakeAuth(events)
    collector = FakeCollector(events)
    coordinator = FakeCoordinator(events)
    server = FakeHttpServer(events)
    prompt_answers = [Credentials("user", "password")]
    shutdown = ShutdownCoordinator()
    service = ApplicationService(
        repository=repository,  # type: ignore[arg-type]
        auth=auth,  # type: ignore[arg-type]
        shutdown=shutdown,
        http_factory=lambda: server,  # type: ignore[arg-type]
        collector_factory=lambda _session: collector,  # type: ignore[arg-type]
        prompt_credentials=lambda: prompt_answers.pop(0),
        logger=Mock(),
        output=Mock(),
        crawl_coordinator=coordinator,  # type: ignore[arg-type]
    )
    return service, events, repository, auth, collector, coordinator, server, prompt_answers


def test_first_serve_initializes_before_http_starts() -> None:
    service, events, repository, _, _, _, _, _ = build_service(initialized=False)

    service.startup()
    service.close()

    assert events[:6] == [
        "schema", "login_interactive", "initial_collect", "commit", "http_start", "http_stop"
    ]
    assert repository.inserted[0][1] is True


def test_later_serve_starts_http_without_background_update() -> None:
    service, events, _, _, _, _, _, _ = build_service(initialized=True)

    service.startup()
    service.close()

    assert events[:3] == ["schema", "login_saved", "http_start"]
    assert "update_collect" not in events
    assert not hasattr(service, "update_thread")


def test_first_start_never_uses_saved_credentials() -> None:
    service, events, *_ = build_service(initialized=False)
    service.startup()
    service.close()
    assert "login_saved" not in events


def test_later_start_falls_back_to_interactive_credentials() -> None:
    service, events, _, auth, _, _, _, prompt_answers = build_service(initialized=True)
    auth.saved_results = [CredentialsRequired("missing")]
    auth.establish_results = [CredentialsRequired("wrong"), object()]
    prompt_answers.append(Credentials("second", "valid"))

    service.startup()
    service.close()

    assert events.count("login_interactive") == 2
    assert events.index("login_interactive") < events.index("http_start")


def test_close_stops_http_then_crawl_coordinator_then_auth() -> None:
    service, events, _, auth, _, _, _, _ = build_service(initialized=True)
    service.startup()
    service.close()
    assert service.shutdown.stopping is True
    assert auth.closed is True
    assert events.index("http_stop") < events.index("crawl_close")
    assert events.index("crawl_close") < len(events)
