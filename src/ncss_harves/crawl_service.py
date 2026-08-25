from __future__ import annotations

from dataclasses import replace
from random import Random, SystemRandom
import threading
from typing import Callable, ContextManager, Iterable, Protocol

from .client import NcssClient
from .combination_sampler import sample_combinations
from .errors import AuthenticationRequired, ShutdownRequested
from .filters import CrawlRequest, NativeOption
from .models import Job, QueryResult
from .shutdown import ShutdownCoordinator
from .storage import now_iso


class CrawlCancelled(RuntimeError):
    """The caller disconnected or the service is stopping."""


MAX_COMBINATION_ATTEMPTS = 50


class CrawlRepository(Protocol):
    def detail_cache(self, job_ids: Iterable[str]) -> dict[str, Job]: ...

    def insert_batch(
        self,
        jobs: tuple[Job, ...],
        *,
        commit_guard: ContextManager[None],
    ) -> int: ...


class CrawlService:
    def __init__(
        self,
        *,
        repository: CrawlRepository,
        client_factory: Callable[[threading.Event], NcssClient],
        relogin: Callable[[Callable[[], bool]], object],
        shutdown: ShutdownCoordinator,
        random_factory: Callable[[], Random] = SystemRandom,
    ) -> None:
        self.repository = repository
        self.client_factory = client_factory
        self.relogin = relogin
        self.shutdown = shutdown
        self.random_factory = random_factory

    def _raise_if_cancelled(self, cancel: threading.Event) -> None:
        if cancel.is_set() or self.shutdown.stopping:
            raise CrawlCancelled("crawl cancelled")

    def crawl(self, request: CrawlRequest, cancel: threading.Event) -> QueryResult:
        random_source = self.random_factory()
        combinations = sample_combinations(
            request.dimensions,
            MAX_COMBINATION_ATTEMPTS,
            random_source,
        )
        for auth_attempt in range(2):
            self._raise_if_cancelled(cancel)
            try:
                return self._crawl_once(
                    request,
                    combinations,
                    random_source,
                    cancel,
                )
            except AuthenticationRequired:
                self._raise_if_cancelled(cancel)
                if auth_attempt:
                    raise
                self.relogin(lambda: cancel.is_set() or self.shutdown.stopping)
            except ShutdownRequested as exc:
                raise CrawlCancelled("crawl cancelled") from exc
        raise AssertionError("unreachable")

    def _crawl_once(
        self,
        request: CrawlRequest,
        combinations: tuple[tuple[NativeOption, ...], ...],
        random_source: Random,
        cancel: threading.Event,
    ) -> QueryResult:
        client = self.client_factory(cancel)
        unique_listed: dict[str, Job] = {}
        for combination in combinations:
            self._raise_if_cancelled(cancel)
            page = client.fetch_page_result(
                request.page,
                request.limit,
                request.native_params(
                    combination,
                    limit=request.limit,
                ),
            )
            self._raise_if_cancelled(cancel)
            for job in page.jobs:
                unique_listed.setdefault(job.job_id, job)
            if len(unique_listed) >= request.limit:
                break

        candidate_jobs = tuple(unique_listed.values())
        if len(candidate_jobs) < request.limit:
            return QueryResult((), 0, request.page, request.limit)
        selected_jobs = (
            candidate_jobs
            if len(candidate_jobs) == request.limit
            else tuple(random_source.sample(candidate_jobs, request.limit))
        )
        cached = self.repository.detail_cache(job.job_id for job in selected_jobs)
        completed: list[Job] = []
        for job in selected_jobs:
            self._raise_if_cancelled(cancel)
            cached_job = cached.get(job.job_id)
            if cached_job is not None:
                completed.append(self._merge_detail(job, cached_job))
                continue
            try:
                detailed = client.fetch_detail(job)
            except (AuthenticationRequired, ShutdownRequested):
                raise
            except Exception:
                continue
            completed.append(
                replace(detailed, detail_fetched_at=detailed.detail_fetched_at or now_iso())
            )
        self._raise_if_cancelled(cancel)
        unique_completed: dict[str, Job] = {}
        for job in completed:
            unique_completed.setdefault(job.job_id, job)
        jobs = tuple(unique_completed.values())
        self.repository.insert_batch(
            jobs,
            commit_guard=self.shutdown.commit_guard(),
        )
        return QueryResult(jobs, len(candidate_jobs), request.page, request.limit)

    @staticmethod
    def _merge_detail(list_job: Job, cached: Job) -> Job:
        return replace(
            list_job,
            area_name=cached.area_name or list_job.area_name,
            industry_sectors=cached.industry_sectors or list_job.industry_sectors,
            job_type=cached.job_type or list_job.job_type,
            job_type_name=cached.job_type_name or list_job.job_type_name,
            employment_type=cached.employment_type or list_job.employment_type,
            description=cached.description,
            detail_payload=dict(cached.detail_payload),
            first_seen_at=cached.first_seen_at,
            detail_fetched_at=cached.detail_fetched_at,
        )
