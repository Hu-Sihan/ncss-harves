from __future__ import annotations

from dataclasses import replace

import pytest
import requests

from ncss_harves.collector import Batch, Collector, ListFetchFailed, NullProgress
from ncss_harves.errors import AuthenticationRequired, ShutdownRequested
from ncss_harves.models import Job


class FakeClient:
    def __init__(self, page_size: int = 20) -> None:
        self.page_size = page_size
        self.page_calls: list[int] = []
        self.detail_calls: list[str] = []
        self.page_errors: dict[int, Exception] = {}
        self.detail_errors: dict[str, Exception] = {}
        self.active_calls = 0
        self.max_concurrent_calls = 0

    def _enter(self) -> None:
        self.active_calls += 1
        self.max_concurrent_calls = max(self.max_concurrent_calls, self.active_calls)

    def _exit(self) -> None:
        self.active_calls -= 1

    def fetch_page(self, page: int, limit: int) -> list[Job]:
        self._enter()
        try:
            self.page_calls.append(page)
            if page in self.page_errors:
                raise self.page_errors[page]
            return [
                Job(job_id=f"job-{page}-{index}", job_name=f"岗位 {page}-{index}")
                for index in range(self.page_size)
            ]
        finally:
            self._exit()

    def fetch_detail(self, job: Job) -> Job:
        self._enter()
        try:
            self.detail_calls.append(job.job_id)
            if job.job_id in self.detail_errors:
                raise self.detail_errors[job.job_id]
            return replace(job, description=f"详情 {job.job_id}")
        finally:
            self._exit()


class RecordingProgress:
    def __init__(self) -> None:
        self.page_total = 0
        self.detail_total = 0
        self.pages_seen: list[int] = []
        self.details_seen: list[str] = []

    def pages(self, values, *, total: int):
        self.page_total = total
        for value in values:
            self.pages_seen.append(value)
            yield value

    def details(self, values, *, total: int):
        self.detail_total = total
        for value in values:
            self.details_seen.append(value.job_id)
            yield value


def test_initial_batch_fetches_fifty_pages_then_details_in_order() -> None:
    client = FakeClient(page_size=20)
    progress = RecordingProgress()
    collector = Collector(client)  # type: ignore[arg-type]

    result = collector.collect_initial(progress)

    assert client.page_calls == list(range(1, 51))
    assert client.max_concurrent_calls == 1
    assert result.list_count == 1000
    assert len(result.jobs) == 1000
    assert progress.page_total == 50
    assert progress.detail_total == 1000
    assert client.detail_calls[0] == "job-1-0"
    assert client.detail_calls[-1] == "job-50-19"


def test_duplicate_list_job_is_fetched_once() -> None:
    client = FakeClient(page_size=1)

    def duplicate_page(page: int, limit: int) -> list[Job]:
        client.page_calls.append(page)
        return [Job(job_id="same", job_name=str(page))]

    client.fetch_page = duplicate_page  # type: ignore[method-assign]
    result = Collector(client, page_count=3).collect_initial(NullProgress())  # type: ignore[arg-type]

    assert result.list_count == 1
    assert [job.job_id for job in result.jobs] == ["same"]
    assert client.detail_calls == ["same"]


def test_detail_failure_omits_job() -> None:
    client = FakeClient(page_size=2)
    client.detail_errors["job-1-1"] = requests.Timeout()

    result = Collector(client, page_count=1).collect_initial()  # type: ignore[arg-type]

    assert result.list_count == 2
    assert [job.job_id for job in result.jobs] == ["job-1-0"]


def test_list_failure_aborts_batch() -> None:
    client = FakeClient(page_size=1)
    client.page_errors[2] = requests.Timeout("list failed")

    with pytest.raises(ListFetchFailed, match="page 2"):
        Collector(client, page_count=3).collect_initial()  # type: ignore[arg-type]

    assert client.detail_calls == []


@pytest.mark.parametrize("stage", ["list", "detail"])
def test_authentication_error_is_propagated(stage: str) -> None:
    client = FakeClient(page_size=1)
    if stage == "list":
        client.page_errors[1] = AuthenticationRequired("expired")
    else:
        client.detail_errors["job-1-0"] = AuthenticationRequired("expired")

    with pytest.raises(AuthenticationRequired):
        Collector(client, page_count=1).collect_initial()  # type: ignore[arg-type]


def test_shutdown_is_never_downgraded_to_detail_failure() -> None:
    client = FakeClient(page_size=1)
    client.detail_errors["job-1-0"] = ShutdownRequested("stop")

    with pytest.raises(ShutdownRequested):
        Collector(client, page_count=1).collect_initial()  # type: ignore[arg-type]


def test_batch_is_an_immutable_snapshot() -> None:
    batch = Batch(jobs=(Job(job_id="1"),), list_count=1)
    assert batch.list_count == 1
    with pytest.raises(AttributeError):
        batch.list_count = 2  # type: ignore[misc]
