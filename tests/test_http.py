from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
import socket
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ncss_harves.areas import PROVINCE_AREA_CODES
from ncss_harves.errors import AuthenticationRequired
from ncss_harves.http_server import create_server
from ncss_harves.filters import (
    MONTH_PAY_NATIVE_VALUES,
    CrawlRequest,
)
from ncss_harves.logging_utils import SafeLogger
from ncss_harves.models import Job, QueryResult
from ncss_harves.shutdown import ShutdownCoordinator


class FakeRepository:
    def __init__(self, initialized: bool = True) -> None:
        self.initialized = initialized
        self.queries = []

    def is_initialized(self) -> bool:
        return self.initialized

    def query(self, query) -> QueryResult:
        self.queries.append(query)
        jobs = (
            Job(
                job_id="1",
                job_name="产品经理",
                description="完整描述",
                list_payload={"native": "list"},
                detail_payload={"native": "detail"},
            ),
        )
        return QueryResult(jobs=jobs, total=7, page=query.page, limit=query.limit)


class FakeCrawlTask:
    def __init__(self, result: QueryResult | Exception) -> None:
        self.result = result
        self.cancelled = False

    def wait(self, _timeout=None):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def cancel(self):
        self.cancelled = True


class FakeCrawlCoordinator:
    def __init__(self, result: QueryResult | Exception | None = None) -> None:
        self.result = result or QueryResult(
            jobs=(Job(job_id="remote", job_name="远端岗位", description="完整详情",
                      list_payload={"private": 1}, detail_payload={"private": 2}),),
            total=321,
            page=7,
            limit=20,
        )
        self.requests: list[CrawlRequest] = []

    def submit(self, request: CrawlRequest):
        self.requests.append(request)
        return FakeCrawlTask(self.result)


class BlockingCrawlTask:
    def __init__(self) -> None:
        self.cancelled = threading.Event()

    def wait(self, _timeout=None):
        raise TimeoutError("still running")

    def cancel(self):
        self.cancelled.set()


class BlockingCrawlCoordinator:
    def __init__(self) -> None:
        self.task = BlockingCrawlTask()
        self.submitted = threading.Event()

    def submit(self, _request):
        self.submitted.set()
        return self.task


@dataclass
class HttpResult:
    status_code: int
    payload: dict[str, object]


@contextmanager
def running_server(
    repository: FakeRepository | None = None,
    coordinator: FakeCrawlCoordinator | None = None,
):
    shutdown = ShutdownCoordinator()
    repository = repository or FakeRepository()
    server = create_server(
        "127.0.0.1",
        0,
        repository=repository,  # type: ignore[arg-type]
        shutdown=shutdown,
        logger=SafeLogger(logging.getLogger("ncss_harves.test.http")),
        crawl_coordinator=coordinator or FakeCrawlCoordinator(),  # type: ignore[arg-type]
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server, shutdown, repository
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def request(server, path: str, method: str = "GET") -> HttpResult:
    host, port = server.server_address
    try:
        with urlopen(Request(f"http://{host}:{port}{path}", method=method), timeout=2) as response:
            return HttpResult(response.status, json.loads(response.read()))
    except HTTPError as error:
        return HttpResult(error.code, json.loads(error.read()))


def test_only_query_route_exists() -> None:
    with running_server() as (server, _, _):
        assert request(server, "/query").status_code == 200
        assert request(server, "/jobs").status_code == 404
        assert request(server, "/crawl", "POST").status_code == 404


def test_query_returns_local_jobs_and_one_based_metadata() -> None:
    with running_server() as (server, _, repository):
        result = request(server, "/query?jobName=%E4%BA%A7%E5%93%81&offset=2&limit=3")

    assert result.status_code == 200
    assert result.payload["count"] == 1
    assert result.payload["total"] == 7
    assert result.payload["offset"] == 2
    assert result.payload["limit"] == 3
    assert result.payload["jobs"][0]["job_name"] == "产品经理"  # type: ignore[index]
    assert "list_payload" not in result.payload["jobs"][0]  # type: ignore[operator,index]
    assert "detail_payload" not in result.payload["jobs"][0]  # type: ignore[operator,index]
    assert repository.queries[0].job_name == "产品"


def test_query_returns_empty_when_stopping() -> None:
    with running_server() as (server, shutdown, repository):
        shutdown.request_stop()
        result = request(server, "/query")

    assert result.status_code == 200
    assert result.payload == {"jobs": [], "count": 0, "total": 0, "offset": 1, "limit": 20}
    assert repository.queries == []


def test_query_rejects_invalid_readable_enum() -> None:
    with running_server() as (server, _, _):
        result = request(server, "/query?jobType=%E4%B8%B4%E6%97%B6%E5%B7%A5")

    assert result.status_code == 400
    assert result.payload["error"] == "invalid_filter"
    assert result.payload["dimension"] == "jobType"
    assert "实习" in result.payload["allowed_values"]  # type: ignore[operator]


def test_uninitialized_database_returns_503() -> None:
    with running_server(FakeRepository(initialized=False)) as (server, _, _):
        result = request(server, "/query")

    assert result.status_code == 503
    assert result.payload == {"error": "not_initialized"}


def test_builtin_http_access_log_is_disabled(capsys) -> None:
    with running_server() as (server, _, _):
        request(server, "/query")

    assert capsys.readouterr().err == ""


def test_crawl_returns_remote_jobs_with_query_response_shape() -> None:
    coordinator = FakeCrawlCoordinator()
    with running_server(coordinator=coordinator) as (server, _, _):
        result = request(server, "/crawl?areaName=%E5%8C%97%E4%BA%AC&jobType=%E5%AE%9E%E4%B9%A0&offset=7&limit=20")

    assert result.status_code == 200
    assert result.payload["count"] == 1
    assert result.payload["total"] == 321
    assert result.payload["offset"] == 7
    assert result.payload["limit"] == 20
    job = result.payload["jobs"][0]  # type: ignore[index]
    assert job["job_name"] == "远端岗位"
    assert "list_payload" not in job
    assert "detail_payload" not in job
    submitted = coordinator.requests[0]
    combination = tuple(dimension[0] for dimension in submitted.dimensions)
    assert submitted.native_params(combination)["areaCode"] == "11"


def test_crawl_preserves_repeated_and_comma_separated_values() -> None:
    coordinator = FakeCrawlCoordinator()
    path = (
        "/crawl?areaName=%E5%8C%97%E4%BA%AC%2C%E4%B8%8A%E6%B5%B7"
        "&areaName=%E6%9D%AD%E5%B7%9E%E5%B8%82"
        "&jobType=%E5%85%A8%E8%81%8C%EF%BC%8C%E5%AE%9E%E4%B9%A0"
        "&limit=3"
    )
    with running_server(coordinator=coordinator) as (server, _, _):
        result = request(server, path)

    submitted = coordinator.requests[0]
    assert [len(dimension) for dimension in submitted.dimensions] == [3, 2]
    assert submitted.limit == 3
    assert result.status_code == 200
    assert result.payload["total"] == 321
    assert result.payload["limit"] == 20


def test_crawl_accepts_explicit_month_pay_multiselect() -> None:
    coordinator = FakeCrawlCoordinator()
    path = "/crawl?monthPay=2K%E4%BB%A5%E4%B8%8B%2C%E9%9D%A2%E8%AE%AE&limit=2"
    with running_server(coordinator=coordinator) as (server, _, _):
        result = request(server, path)

    submitted = coordinator.requests[0]
    assert result.status_code == 200
    assert submitted.common_items == ()
    assert submitted.dimensions == (
        (
            (("monthPay", "2"),),
            (("monthPay", "0"),),
        ),
    )


def test_crawl_accepts_random_inside_supported_filter_fields() -> None:
    coordinator = FakeCrawlCoordinator()
    path = "/crawl?areaName=random&jobType=random&monthPay=random&limit=3"
    with running_server(coordinator=coordinator) as (server, _, _):
        result = request(server, path)

    submitted = coordinator.requests[0]
    assert [len(dimension) for dimension in submitted.dimensions] == [
        len(PROVINCE_AREA_CODES),
        3,
        len(MONTH_PAY_NATIVE_VALUES),
    ]
    assert submitted.limit == 3
    assert result.status_code == 200


@pytest.mark.parametrize("name", ["publishDateFrom", "publishDateTo", "random"])
def test_crawl_rejects_query_only_parameters(name: str) -> None:
    with running_server() as (server, _, _):
        result = request(server, f"/crawl?{name}=true")
    assert result.status_code == 400
    assert result.payload["error"] == "invalid_request"


def test_crawl_upstream_failure_returns_502() -> None:
    coordinator = FakeCrawlCoordinator(AuthenticationRequired("expired"))
    with running_server(coordinator=coordinator) as (server, _, _):
        result = request(server, "/crawl")
    assert result.status_code == 502
    assert result.payload == {"error": "upstream_error"}


def test_crawl_returns_complete_empty_shape_when_stopping() -> None:
    coordinator = FakeCrawlCoordinator()
    with running_server(coordinator=coordinator) as (server, shutdown, _):
        shutdown.request_stop()
        result = request(server, "/crawl?offset=7&limit=40")
    assert result.status_code == 200
    assert result.payload == {"jobs": [], "count": 0, "total": 0, "offset": 7, "limit": 40}
    assert coordinator.requests == []


def test_crawl_candidate_shortage_returns_complete_empty_shape() -> None:
    coordinator = FakeCrawlCoordinator(
        QueryResult(jobs=(), total=0, page=4, limit=6)
    )
    with running_server(coordinator=coordinator) as (server, _, _):
        result = request(server, "/crawl?offset=4&limit=6")

    assert result.status_code == 200
    assert result.payload == {
        "jobs": [],
        "count": 0,
        "total": 0,
        "offset": 4,
        "limit": 6,
    }


def test_client_disconnect_cancels_running_crawl() -> None:
    coordinator = BlockingCrawlCoordinator()
    with running_server(coordinator=coordinator) as (server, _, _):  # type: ignore[arg-type]
        host, port = server.server_address
        client = socket.create_connection((host, port), timeout=2)
        client.sendall(b"GET /crawl HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        assert coordinator.submitted.wait(1)
        client.close()
        assert coordinator.task.cancelled.wait(1)


def test_shutdown_during_crawl_cancels_task_and_returns_empty_response() -> None:
    coordinator = BlockingCrawlCoordinator()
    captured = []
    with running_server(coordinator=coordinator) as (server, shutdown, _):  # type: ignore[arg-type]
        worker = threading.Thread(target=lambda: captured.append(request(server, "/crawl?offset=7&limit=40")))
        worker.start()
        assert coordinator.submitted.wait(1)
        shutdown.request_stop()
        worker.join(2)

    assert coordinator.task.cancelled.is_set()
    assert len(captured) == 1
    assert captured[0].payload == {"jobs": [], "count": 0, "total": 0, "offset": 7, "limit": 40}
