from __future__ import annotations

import threading
import time

import pytest

from ncss_harves.errors import ShutdownRequested
from ncss_harves.shutdown import ShutdownCoordinator


def test_shutdown_waits_for_commit_guard() -> None:
    shutdown = ShutdownCoordinator()
    with shutdown.commit_guard():
        shutdown.request_stop()
        assert shutdown.stopping is True
        assert shutdown.ready_to_close is False
    assert shutdown.ready_to_close is True


def test_raise_if_requested() -> None:
    shutdown = ShutdownCoordinator()
    shutdown.request_stop()
    with pytest.raises(ShutdownRequested):
        shutdown.raise_if_requested()


def test_wait_until_safe_blocks_only_during_commit() -> None:
    shutdown = ShutdownCoordinator()
    entered = threading.Event()
    release = threading.Event()

    def commit() -> None:
        with shutdown.commit_guard():
            entered.set()
            release.wait()

    worker = threading.Thread(target=commit)
    worker.start()
    assert entered.wait(1)
    shutdown.request_stop()
    assert shutdown.wait_until_safe(timeout=0.01) is False
    release.set()
    worker.join(1)
    assert shutdown.wait_until_safe(timeout=1) is True


def test_interruptible_wait_returns_immediately_after_stop() -> None:
    shutdown = ShutdownCoordinator()
    shutdown.request_stop()
    started = time.monotonic()
    assert shutdown.wait(60) is True
    assert time.monotonic() - started < 0.1
