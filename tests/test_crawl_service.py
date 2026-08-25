from __future__ import annotations

from dataclasses import replace
from random import Random
from unittest.mock import Mock
import threading

import pytest
import requests

from ncss_harves.client import ListPage
from ncss_harves.crawl_service import CrawlCancelled, CrawlService
from ncss_harves.errors import AuthenticationRequired
from ncss_harves.filters import CrawlRequest, crawl_request_from_params
from ncss_harves.models import Job, QueryResult
from ncss_harves.shutdown import ShutdownCoordinator


class FakeClient:
    def __init__(self, pages: ListPage | Exception | list[ListPage | Exception]) -> None:
        self.pages = list(pages) if isinstance(pages, list) else [pages]
        self.page_calls: list[tuple[int, int, dict[str, object]]] = []
        self.detail_calls: list[str] = []
        self.details: dict[str, Job | Exception] = {}

    def fetch_page_result(self, page, limit, native_params):
        self.page_calls.append((page, limit, dict(native_params)))
        result = self.pages.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_detail(self, job: Job) -> Job:
        self.detail_calls.append(job.job_id)
        result = self.details.get(job.job_id, replace(job, description=f"详情 {job.job_id}"))
        if isinstance(result, Exception):
            raise result
        return result


class FakeRepository:
    def __init__(self, cache: dict[str, Job] | None = None) -> None:
        self.cache = cache or {}
        self.inserted: tuple[Job, ...] | None = None
        self.cache_calls: list[tuple[str, ...]] = []

    def detail_cache(self, job_ids):
        requested = tuple(job_ids)
        self.cache_calls.append(requested)
        return {
            job_id: self.cache[job_id]
            for job_id in requested
            if job_id in self.cache
        }

    def insert_batch(self, jobs, *, commit_guard=None):
        with commit_guard:
            self.inserted = tuple(jobs)
        return len(self.inserted)


class TrackingRandom(Random):
    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self.job_sample_calls = 0

    def sample(self, population, k, *, counts=None):
        if not isinstance(population, range):
            self.job_sample_calls += 1
        return super().sample(population, k, counts=counts)


def request(limit: int = 3) -> CrawlRequest:
    return CrawlRequest(
        dimensions=(((("areaCode", "110000"),),),),
        page=2,
        limit=limit,
    )


def test_crawl_reuses_cache_merges_latest_list_and_fetches_missing_details():
    listed = (
        Job(job_id="cached", job_name="本次最新名称", low_month_pay=9000, list_payload={"v": 2}),
        Job(job_id="cached", job_name="重复条目"),
        Job(job_id="new", job_name="新增岗位"),
        Job(job_id="failed", job_name="失败岗位"),
    )
    cached = Job(
        job_id="cached",
        job_name="旧名称",
        area_name="北京市海淀区",
        description="缓存详情",
        industry_sectors="计算机软件",
        employment_type="internship",
        detail_payload={"cached": True},
        detail_fetched_at="2026-08-25T00:00:00Z",
    )
    client = FakeClient(ListPage(listed, total=321, page=2, limit=3))
    client.details["failed"] = requests.Timeout("failed")
    repository = FakeRepository({"cached": cached})
    service = CrawlService(
        repository=repository,
        client_factory=lambda _cancel: client,
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
    )

    result = service.crawl(request(), threading.Event())

    assert client.detail_calls == ["new", "failed"]
    assert [job.job_id for job in result.jobs] == ["cached", "new"]
    assert result.total == 3
    assert result.jobs[0].job_name == "本次最新名称"
    assert result.jobs[0].low_month_pay == 9000
    assert result.jobs[0].description == "缓存详情"
    assert result.jobs[0].area_name == "北京市海淀区"
    assert result.jobs[0].list_payload == {"v": 2}
    assert result.jobs[0].detail_payload == {"cached": True}
    assert [job.job_id for job in repository.inserted or ()] == ["cached", "new"]


def test_cancellation_discards_entire_batch_before_commit():
    cancel = threading.Event()
    client = FakeClient(ListPage((Job(job_id="new"),), total=1, page=1, limit=1))
    client.details["new"] = Job(job_id="new", description="完整")
    original_fetch_detail = client.fetch_detail

    def fetch_then_cancel(job):
        result = original_fetch_detail(job)
        cancel.set()
        return result

    client.fetch_detail = fetch_then_cancel  # type: ignore[method-assign]
    repository = FakeRepository()
    service = CrawlService(
        repository=repository,
        client_factory=lambda _cancel: client,
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
    )

    with pytest.raises(CrawlCancelled):
        service.crawl(request(limit=1), cancel)

    assert repository.inserted is None


def test_authentication_relogin_restarts_whole_page_once():
    first = FakeClient(AuthenticationRequired("expired"))
    second = FakeClient(ListPage((Job(job_id="new"),), total=1, page=2, limit=1))
    clients = iter((first, second))
    relogin = Mock()
    repository = FakeRepository()
    service = CrawlService(
        repository=repository,
        client_factory=lambda _cancel: next(clients),
        relogin=relogin,
        shutdown=ShutdownCoordinator(),
    )

    result = service.crawl(request(limit=1), threading.Event())

    relogin.assert_called_once()
    assert [job.job_id for job in result.jobs] == ["new"]


def test_second_authentication_failure_is_propagated_without_commit():
    clients = iter((
        FakeClient(AuthenticationRequired("expired-1")),
        FakeClient(AuthenticationRequired("expired-2")),
    ))
    repository = FakeRepository()
    service = CrawlService(
        repository=repository,
        client_factory=lambda _cancel: next(clients),
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
    )

    with pytest.raises(AuthenticationRequired, match="expired-2"):
        service.crawl(request(limit=1), threading.Event())

    assert repository.inserted is None


def test_crawl_tries_new_combinations_until_unique_candidates_fill_limit():
    mixed_request = crawl_request_from_params(
        {
            "areaName": "北京,上海",
            "jobType": "全职,实习",
            "limit": 3,
            "offset": 2,
        }
    )
    pages = [
        ListPage((Job(job_id="a"),), 1, 2, 3),
        ListPage((Job(job_id="a"), Job(job_id="b")), 2, 2, 3),
        ListPage((Job(job_id="c"), Job(job_id="d")), 2, 2, 3),
    ]
    client = FakeClient(pages)
    repository = FakeRepository()
    service = CrawlService(
        repository=repository,
        client_factory=lambda _cancel: client,
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
        random_factory=lambda: Random(7),
    )

    result = service.crawl(mixed_request, threading.Event())

    assert len(client.page_calls) == 3
    assert all(call[0:2] == (2, 3) for call in client.page_calls)
    assert result.total == 4
    assert len(result.jobs) == 3
    assert set(client.detail_calls) == {job.job_id for job in result.jobs}


def test_detail_failure_does_not_backfill_from_unselected_candidates():
    limited_request = CrawlRequest(page=1, limit=2)
    client = FakeClient(
        ListPage(
            (Job(job_id="a"), Job(job_id="b"), Job(job_id="c")),
            total=3,
            page=1,
            limit=2,
        )
    )
    client.details["b"] = requests.Timeout("failed")
    repository = FakeRepository()
    service = CrawlService(
        repository=repository,
        client_factory=lambda _cancel: client,
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
        random_factory=lambda: Random(7),
    )

    result = service.crawl(limited_request, threading.Event())

    assert client.detail_calls == ["a", "b"]
    assert [job.job_id for job in result.jobs] == ["a"]
    assert result.total == 3


def test_limit_one_requests_one_list_item_per_selected_combination():
    limited_request = crawl_request_from_params(
        {"areaName": "北京,上海", "limit": 1}
    )
    client = FakeClient(ListPage((Job(job_id="a"),), total=1, page=1, limit=1))
    service = CrawlService(
        repository=FakeRepository(),
        client_factory=lambda _cancel: client,
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
        random_factory=lambda: Random(7),
    )

    service.crawl(limited_request, threading.Event())

    assert client.page_calls[0][0:2] == (1, 1)


def test_authentication_recovery_reuses_sampled_combination_sequence():
    mixed_request = crawl_request_from_params(
        {"areaName": "北京,上海", "jobType": "全职,实习", "limit": 3}
    )
    first = FakeClient(
        [
            ListPage((Job(job_id="first"),), total=1, page=1, limit=3),
            AuthenticationRequired("expired"),
        ]
    )
    second = FakeClient(
        [
            ListPage((Job(job_id="a"),), total=1, page=1, limit=3),
            ListPage((Job(job_id="b"),), total=1, page=1, limit=3),
            ListPage((Job(job_id="c"),), total=1, page=1, limit=3),
        ]
    )
    clients = iter((first, second))
    service = CrawlService(
        repository=FakeRepository(),
        client_factory=lambda _cancel: next(clients),
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
        random_factory=lambda: Random(7),
    )

    service.crawl(mixed_request, threading.Event())

    assert [call[2] for call in first.page_calls] == [
        call[2] for call in second.page_calls[:2]
    ]


def test_cancellation_between_list_requests_discards_entire_batch():
    cancel = threading.Event()
    mixed_request = crawl_request_from_params(
        {"areaName": "北京,上海", "limit": 2}
    )
    client = FakeClient(
        [
            ListPage((Job(job_id="a"),), total=1, page=1, limit=2),
            ListPage((Job(job_id="b"),), total=1, page=1, limit=2),
        ]
    )
    original_fetch_page = client.fetch_page_result

    def fetch_then_cancel(page, limit, native_params):
        result = original_fetch_page(page, limit, native_params)
        cancel.set()
        return result

    client.fetch_page_result = fetch_then_cancel  # type: ignore[method-assign]
    repository = FakeRepository()
    service = CrawlService(
        repository=repository,
        client_factory=lambda _cancel: client,
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
        random_factory=lambda: Random(7),
    )

    with pytest.raises(CrawlCancelled):
        service.crawl(mixed_request, cancel)

    assert repository.inserted is None
    assert len(client.page_calls) == 1


def test_first_combination_exactly_fills_limit_without_job_sampling():
    random_source = TrackingRandom(7)
    client = FakeClient(
        ListPage(
            (Job(job_id="a"), Job(job_id="b"), Job(job_id="c")),
            total=3,
            page=2,
            limit=3,
        )
    )
    service = CrawlService(
        repository=FakeRepository(),
        client_factory=lambda _cancel: client,
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
        random_factory=lambda: random_source,
    )

    result = service.crawl(request(limit=3), threading.Event())

    assert len(client.page_calls) == 1
    assert client.page_calls[0][0:2] == (2, 3)
    assert [job.job_id for job in result.jobs] == ["a", "b", "c"]
    assert result.total == 3
    assert random_source.job_sample_calls == 0


def test_exhausted_combinations_below_limit_return_empty_without_details_or_insert():
    limited_request = crawl_request_from_params(
        {"areaName": "北京,上海", "limit": 3}
    )
    client = FakeClient(
        [
            ListPage((Job(job_id="a"),), 1, 1, 3),
            ListPage((Job(job_id="a"), Job(job_id="b")), 2, 1, 3),
        ]
    )
    repository = FakeRepository()
    service = CrawlService(
        repository=repository,
        client_factory=lambda _cancel: client,
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
        random_factory=lambda: Random(7),
    )

    result = service.crawl(limited_request, threading.Event())

    assert result == QueryResult((), 0, 1, 3)
    assert repository.cache_calls == []
    assert client.detail_calls == []
    assert repository.inserted is None


def test_crawl_stops_after_fifty_unique_combinations_when_candidates_are_short():
    dimension = tuple(
        (("areaCode", str(index)),)
        for index in range(60)
    )
    capped_request = CrawlRequest(dimensions=(dimension,), page=1, limit=2)
    client = FakeClient(
        [ListPage((Job(job_id="same"),), 1, 1, 2) for _ in range(50)]
    )
    repository = FakeRepository()
    service = CrawlService(
        repository=repository,
        client_factory=lambda _cancel: client,
        relogin=Mock(),
        shutdown=ShutdownCoordinator(),
        random_factory=lambda: Random(7),
    )

    result = service.crawl(capped_request, threading.Event())

    assert len(client.page_calls) == 50
    assert result == QueryResult((), 0, 1, 2)
    assert repository.cache_calls == []
    assert repository.inserted is None
