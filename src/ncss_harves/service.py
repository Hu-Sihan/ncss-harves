from __future__ import annotations

import threading
from typing import Callable, Protocol

from .auth import AuthManager, CredentialsRequired
from .collector import Collector, TqdmProgress
from .credentials import Credentials
from .errors import AuthenticationRequired, ShutdownRequested
from .logging_utils import SafeLogger
from .shutdown import ShutdownCoordinator
from .storage import Repository


class HttpServer(Protocol):
    def serve_forever(self) -> None: ...

    def shutdown(self) -> None: ...

    def server_close(self) -> None: ...


class CrawlCoordinator(Protocol):
    def close(self) -> None: ...


class ApplicationService:
    def __init__(
        self,
        *,
        repository: Repository,
        auth: AuthManager,
        shutdown: ShutdownCoordinator,
        http_factory: Callable[[], HttpServer],
        collector_factory: Callable[[object], Collector],
        prompt_credentials: Callable[[], Credentials],
        logger: SafeLogger,
        output: Callable[[str], None] = print,
        crawl_coordinator: CrawlCoordinator,
    ) -> None:
        self.repository = repository
        self.auth = auth
        self.shutdown = shutdown
        self.http_factory = http_factory
        self.collector_factory = collector_factory
        self.prompt_credentials = prompt_credentials
        self.logger = logger
        self.output = output
        self.crawl_coordinator = crawl_coordinator
        self.http_server: HttpServer | None = None
        self.http_thread: threading.Thread | None = None
        self._close_lock = threading.Lock()
        self._closed = False

    def run(self) -> None:
        try:
            self.startup()
            while not self.shutdown.wait(0.2):
                pass
        finally:
            self.close()

    def startup(self) -> None:
        self.repository.initialize_schema()
        first_start = not self.repository.is_initialized()
        self._authenticate(first_start=first_start)
        if first_start:
            self._initialize_database()
        self._start_http()

    def _authenticate(self, *, first_start: bool) -> None:
        if first_start:
            self._interactive_login()
            return
        try:
            self.auth.establish_saved()
        except CredentialsRequired:
            self._interactive_login()

    def _interactive_login(self) -> None:
        while not self.shutdown.stopping:
            credentials = self.prompt_credentials()
            try:
                self.auth.establish(credentials)
                return
            except CredentialsRequired as exc:
                self.output(f"登录失败：{exc}")
        raise ShutdownRequested("shutdown requested during login")

    def _collector(self) -> Collector:
        return self.collector_factory(self.auth.session())

    def _initialize_database(self) -> None:
        while True:
            self.shutdown.raise_if_requested()
            try:
                batch = self._collector().collect_initial(TqdmProgress())
                self.shutdown.raise_if_requested()
                inserted = self.repository.insert_batch(
                    batch.jobs,
                    mark_initialized=True,
                    commit_guard=self.shutdown.commit_guard(),
                )
                self.output(f"初始化拉取成功：入库 {inserted} 条岗位。")
                return
            except AuthenticationRequired:
                self._recover_without_http()

    def _recover_without_http(self) -> None:
        try:
            self.auth.establish_saved()
        except CredentialsRequired:
            self._interactive_login()

    def _start_http(self) -> None:
        if self.shutdown.stopping:
            return
        server = self.http_factory()
        thread = threading.Thread(
            target=server.serve_forever,
            name="ncss-http",
            daemon=False,
        )
        self.http_server = server
        self.http_thread = thread
        thread.start()

    def _stop_http(self) -> None:
        server, thread = self.http_server, self.http_thread
        self.http_server = None
        self.http_thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self.shutdown.request_stop()
        self._stop_http()
        self.crawl_coordinator.close()
        self.shutdown.wait_until_safe()
        self.auth.close()
