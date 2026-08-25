from __future__ import annotations

import threading
import time

import pytest

from ncss_harves.crawl_coordinator import CrawlCoordinator
from ncss_harves.crawl_service import CrawlCancelled
from ncss_harves.filters import CrawlRequest
from ncss_harves.models import QueryResult


def request(page: int) -> CrawlRequest:
    return CrawlRequest(page=page, limit=20)


def result(page: int) -> QueryResult:
    return QueryResult((), total=page, page=page, limit=20)


def test_tasks_run_fifo_and_never_overlap():
    events: list[str] = []
    first_entered = threading.Event()
    release_first = threading.Event()

    def crawl(item, _cancel):
        events.append(f"start-{item.page}")
        if item.page == 1:
            first_entered.set()
            release_first.wait(1)
        events.append(f"finish-{item.page}")
        return result(item.page)

    coordinator = CrawlCoordinator(crawl)
    assert coordinator.worker_alive is False
    first = coordinator.submit(request(1))
    assert first_entered.wait(1)
    second = coordinator.submit(request(2))
    release_first.set()

    assert first.wait(1).page == 1
    assert second.wait(1).page == 2
    assert events == ["start-1", "finish-1", "start-2", "finish-2"]
    coordinator.close()


def test_cancelled_queued_task_never_runs():
    first_entered = threading.Event()
    release_first = threading.Event()
    calls: list[int] = []

    def crawl(item, _cancel):
        calls.append(item.page)
        if item.page == 1:
            first_entered.set()
            release_first.wait(1)
        return result(item.page)

    coordinator = CrawlCoordinator(crawl)
    first = coordinator.submit(request(1))
    assert first_entered.wait(1)
    second = coordinator.submit(request(2))
    second.cancel()
    release_first.set()

    assert first.wait(1).page == 1
    with pytest.raises(CrawlCancelled):
        second.wait(1)
    assert calls == [1]
    coordinator.close()


def test_running_task_observes_cancel_event():
    entered = threading.Event()

    def crawl(_item, cancel):
        entered.set()
        while not cancel.wait(0.01):
            pass
        raise CrawlCancelled("cancelled")

    coordinator = CrawlCoordinator(crawl)
    task = coordinator.submit(request(1))
    assert entered.wait(1)
    task.cancel()

    with pytest.raises(CrawlCancelled):
        task.wait(1)
    coordinator.close()


def test_close_cancels_running_and_queued_tasks_and_is_idempotent():
    entered = threading.Event()

    def crawl(_item, cancel):
        entered.set()
        while not cancel.wait(0.01):
            pass
        raise CrawlCancelled("closed")

    coordinator = CrawlCoordinator(crawl)
    running = coordinator.submit(request(1))
    queued = coordinator.submit(request(2))
    assert entered.wait(1)

    coordinator.close()
    coordinator.close()

    with pytest.raises(CrawlCancelled):
        running.wait(1)
    with pytest.raises(CrawlCancelled):
        queued.wait(1)
    assert coordinator.worker_alive is False


def test_submit_after_close_is_rejected():
    coordinator = CrawlCoordinator(lambda item, cancel: result(item.page))
    coordinator.close()
    with pytest.raises(RuntimeError, match="closed"):
        coordinator.submit(request(1))
