from __future__ import annotations

from dataclasses import dataclass, field
from queue import Queue
import threading
from typing import Callable

from .crawl_service import CrawlCancelled
from .filters import CrawlRequest
from .models import QueryResult


@dataclass(eq=False, slots=True)
class CrawlTask:
    request: CrawlRequest
    cancel_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)
    result: QueryResult | None = None
    error: BaseException | None = None

    def cancel(self) -> None:
        self.cancel_event.set()

    def wait(self, timeout: float | None = None) -> QueryResult:
        if not self.done_event.wait(timeout):
            raise TimeoutError("crawl task did not finish in time")
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise CrawlCancelled("crawl task was cancelled")
        return self.result


class CrawlCoordinator:
    def __init__(
        self,
        crawl: Callable[[CrawlRequest, threading.Event], QueryResult],
    ) -> None:
        self._crawl = crawl
        self._queue: Queue[CrawlTask | None] = Queue()
        self._lock = threading.Lock()
        self._tasks: set[CrawlTask] = set()
        self._worker: threading.Thread | None = None
        self._closed = False

    @property
    def worker_alive(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def submit(self, request: CrawlRequest) -> CrawlTask:
        with self._lock:
            if self._closed:
                raise RuntimeError("crawl coordinator is closed")
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run,
                    name="ncss-crawl",
                    daemon=False,
                )
                self._worker.start()
            task = CrawlTask(request)
            self._tasks.add(task)
            self._queue.put(task)
            return task

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return
            try:
                if task.cancel_event.is_set():
                    raise CrawlCancelled("crawl task was cancelled")
                task.result = self._crawl(task.request, task.cancel_event)
            except BaseException as exc:
                task.error = exc
            finally:
                task.done_event.set()
                with self._lock:
                    self._tasks.discard(task)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            tasks = tuple(self._tasks)
            worker = self._worker
            for task in tasks:
                task.cancel()
            if worker is not None:
                self._queue.put(None)
        if worker is not None and worker is not threading.current_thread():
            worker.join()
