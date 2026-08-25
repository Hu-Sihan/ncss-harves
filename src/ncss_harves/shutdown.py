from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Iterator

from .errors import ShutdownRequested


class ShutdownCoordinator:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._condition = threading.Condition()
        self._commit_count = 0

    @property
    def stopping(self) -> bool:
        return self._stop_event.is_set()

    @property
    def ready_to_close(self) -> bool:
        with self._condition:
            return self.stopping and self._commit_count == 0

    def request_stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()

    def raise_if_requested(self) -> None:
        if self.stopping:
            raise ShutdownRequested("shutdown requested")

    def wait(self, timeout: float) -> bool:
        """Return True when stop was requested, False when the timeout elapsed."""
        return self._stop_event.wait(timeout)

    @contextmanager
    def commit_guard(self) -> Iterator[None]:
        with self._condition:
            self._commit_count += 1
        try:
            yield
        finally:
            with self._condition:
                self._commit_count -= 1
                self._condition.notify_all()

    def wait_until_safe(self, timeout: float | None = None) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: self._commit_count == 0, timeout=timeout)
