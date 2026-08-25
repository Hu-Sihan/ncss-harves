from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Protocol, Sequence, TypeVar

from tqdm import tqdm

from .client import NcssClient
from .config import INITIAL_PAGE_COUNT, NCSS_PAGE_SIZE
from .errors import AuthenticationRequired, ShutdownRequested
from .models import Job


T = TypeVar("T")


class ListFetchFailed(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Batch:
    jobs: tuple[Job, ...]
    list_count: int


class Progress(Protocol):
    def pages(self, values: Iterable[int], *, total: int) -> Iterable[int]: ...

    def details(self, values: Iterable[Job], *, total: int) -> Iterable[Job]: ...


class NullProgress:
    def pages(self, values: Iterable[int], *, total: int) -> Iterable[int]:
        return values

    def details(self, values: Iterable[Job], *, total: int) -> Iterable[Job]:
        return values


class TqdmProgress:
    def pages(self, values: Iterable[int], *, total: int) -> Iterable[int]:
        return tqdm(values, total=total, desc="岗位列表", unit="页", dynamic_ncols=True)

    def details(self, values: Iterable[Job], *, total: int) -> Iterable[Job]:
        return tqdm(values, total=total, desc="岗位详情", unit="条", dynamic_ncols=True)


class Collector:
    def __init__(
        self,
        client: NcssClient,
        *,
        page_count: int = INITIAL_PAGE_COUNT,
        page_size: int = NCSS_PAGE_SIZE,
    ) -> None:
        self.client = client
        self.page_count = page_count
        self.page_size = page_size

    def collect_initial(self, progress: Progress | None = None) -> Batch:
        progress = progress or NullProgress()
        listed = self._list_pages(progress)
        detailed = self._details_serially(listed.values(), progress)
        return Batch(jobs=tuple(detailed), list_count=len(listed))

    def _list_pages(self, progress: Progress) -> dict[str, Job]:
        listed: dict[str, Job] = {}
        pages = progress.pages(range(1, self.page_count + 1), total=self.page_count)
        for page in pages:
            try:
                jobs = self.client.fetch_page(page, self.page_size)
            except (AuthenticationRequired, ShutdownRequested):
                raise
            except Exception as exc:
                raise ListFetchFailed(f"failed to fetch NCSS list page {page}") from exc
            for job in jobs:
                listed.setdefault(job.job_id, job)
        return listed

    def _details_serially(
        self,
        jobs: Iterable[Job],
        progress: Progress,
        *,
        total: int | None = None,
    ) -> Iterator[Job]:
        if total is None:
            if not isinstance(jobs, Sequence):
                jobs = tuple(jobs)
            total = len(jobs)
        for job in progress.details(jobs, total=total):
            try:
                yield self.client.fetch_detail(job)
            except (AuthenticationRequired, ShutdownRequested):
                raise
            except Exception:
                continue
