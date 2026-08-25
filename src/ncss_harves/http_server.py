from __future__ import annotations

from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import select
import socket
import time
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from .crawl_service import CrawlCancelled
from .filters import CrawlRequest, crawl_request_from_params, query_from_params
from .logging_utils import SafeLogger
from .models import Job, Query, QueryResult
from .shutdown import ShutdownCoordinator
from .errors import AuthenticationRequired, InvalidFilter, ResponseError


class QueryRepository(Protocol):
    def is_initialized(self) -> bool: ...

    def query(self, query: Query) -> QueryResult: ...


class CrawlTaskProtocol(Protocol):
    def wait(self, timeout: float | None = None) -> QueryResult: ...

    def cancel(self) -> None: ...


class CrawlCoordinatorProtocol(Protocol):
    def submit(self, request: CrawlRequest) -> CrawlTaskProtocol: ...


class QueryHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def public_job_dict(job: Job) -> dict[str, object]:
    payload = asdict(job)
    payload.pop("list_payload", None)
    payload.pop("detail_payload", None)
    return payload


def create_server(
    host: str,
    port: int,
    *,
    repository: QueryRepository,
    shutdown: ShutdownCoordinator,
    logger: SafeLogger,
    crawl_coordinator: CrawlCoordinatorProtocol | None = None,
) -> QueryHttpServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ncss-harves"
        sys_version = ""

        def log_message(self, _format: str, *args: object) -> None:
            return

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        @staticmethod
        def _empty_payload(params: dict[str, object]) -> dict[str, object]:
            try:
                page = max(1, int(params.get("offset") or 1))
            except (TypeError, ValueError):
                page = 1
            try:
                limit = max(1, int(params.get("limit") or 20))
            except (TypeError, ValueError):
                limit = 20
            return {"jobs": [], "count": 0, "total": 0, "offset": page, "limit": limit}

        @staticmethod
        def _result_payload(result: QueryResult) -> dict[str, object]:
            return {
                "jobs": [public_job_dict(job) for job in result.jobs],
                "count": len(result.jobs),
                "total": result.total,
                "offset": result.page,
                "limit": result.limit,
            }

        def _client_disconnected(self) -> bool:
            try:
                readable, _, _ = select.select([self.connection], [], [], 0)
                if not readable:
                    return False
                return self.connection.recv(1, socket.MSG_PEEK) == b""
            except (OSError, ValueError):
                return True

        def _not_found(self) -> None:
            self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            self._not_found()

        def do_PUT(self) -> None:
            self._not_found()

        def do_DELETE(self) -> None:
            self._not_found()

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path not in {"/query", "/crawl"}:
                self._not_found()
                return
            raw_params = parse_qs(parsed.query, keep_blank_values=True)
            params: dict[str, object] = {
                key: values[0] if len(values) == 1 else values for key, values in raw_params.items()
            }
            if shutdown.stopping:
                self._send_json(200, self._empty_payload(params))
                return
            if not repository.is_initialized():
                self._send_json(503, {"error": "not_initialized"})
                return
            if parsed.path == "/crawl":
                self._handle_crawl(params)
                return
            self._handle_query(params)

        def _handle_query(self, params: dict[str, object]) -> None:
            started = time.monotonic()
            try:
                query = query_from_params(params)
                result = repository.query(query)
                if shutdown.stopping:
                    self._send_json(200, self._empty_payload(params))
                    return
                logger.info(
                    "query",
                    params=params,
                    returned=len(result.jobs),
                    total=result.total,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                )
                self._send_json(200, self._result_payload(result))
            except InvalidFilter as exc:
                self._send_json(
                    400,
                    {
                        "error": "invalid_filter",
                        "dimension": exc.dimension,
                        "value": exc.value,
                        "allowed_values": list(exc.allowed_values),
                    },
                )
            except ValueError as exc:
                self._send_json(400, {"error": "invalid_request", "message": str(exc)})
            except Exception as exc:
                logger.exception("query_failed", error=f"{type(exc).__name__}: {exc}")
                self._send_json(500, {"error": "internal_error"})

        def _handle_crawl(self, params: dict[str, object]) -> None:
            if crawl_coordinator is None:
                self._send_json(503, {"error": "crawl_unavailable"})
                return
            task: CrawlTaskProtocol | None = None
            try:
                request = crawl_request_from_params(params)
                task = crawl_coordinator.submit(request)
                while True:
                    if shutdown.stopping:
                        task.cancel()
                        self._send_json(200, self._empty_payload(params))
                        return
                    if self._client_disconnected():
                        task.cancel()
                        return
                    try:
                        result = task.wait(0.05)
                        break
                    except TimeoutError:
                        continue
                if shutdown.stopping:
                    self._send_json(200, self._empty_payload(params))
                    return
                self._send_json(200, self._result_payload(result))
            except InvalidFilter as exc:
                self._send_json(
                    400,
                    {
                        "error": "invalid_filter",
                        "dimension": exc.dimension,
                        "value": exc.value,
                        "allowed_values": list(exc.allowed_values),
                    },
                )
            except ValueError as exc:
                self._send_json(400, {"error": "invalid_request", "message": str(exc)})
            except CrawlCancelled:
                if not self._client_disconnected():
                    self._send_json(200, self._empty_payload(params))
            except (AuthenticationRequired, ResponseError) as exc:
                logger.error("crawl_upstream_failed", error=f"{type(exc).__name__}: {exc}")
                self._send_json(502, {"error": "upstream_error"})
            except Exception as exc:
                logger.exception("crawl_failed", error=f"{type(exc).__name__}: {exc}")
                self._send_json(502, {"error": "upstream_error"})

    return QueryHttpServer((host, port), Handler)
