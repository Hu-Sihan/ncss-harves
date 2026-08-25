from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Sequence

import requests

from .config import (
    DETAIL_URL,
    INTERNSHIP_URL,
    LIST_URL,
    REQUEST_RETRY_WAIT_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    WORK_URL,
)
from .errors import AuthenticationRequired, ResponseError, ShutdownRequested
from .models import Job
from .parsers import parse_detail_html, parse_list_payload


@dataclass(frozen=True, slots=True)
class BrowserCookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = False


@dataclass(frozen=True, slots=True)
class ListPage:
    jobs: tuple[Job, ...]
    total: int
    page: int
    limit: int


def session_from_browser(cookies: Sequence[BrowserCookie], user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Referer": WORK_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    for cookie in cookies:
        session.cookies.set(
            cookie.name,
            cookie.value,
            domain=cookie.domain,
            path=cookie.path or "/",
            secure=cookie.secure,
        )
    return session


class NcssClient:
    def __init__(
        self,
        session: requests.Session,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        self.session = session
        self.sleeper = sleeper
        self.stop_requested = stop_requested

    def _check_running(self) -> None:
        if self.stop_requested():
            raise ShutdownRequested("shutdown requested")

    def _get(self, url: str, **kwargs: object) -> requests.Response:
        self._check_running()
        response = self.session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def _json(response: requests.Response) -> object:
        try:
            return response.json()
        except (requests.JSONDecodeError, ValueError) as exc:
            raise ResponseError("invalid JSON response") from exc

    def _fetch_page_result_once(
        self,
        page: int,
        limit: int,
        native_params: dict[str, object] | None = None,
    ) -> ListPage:
        params: dict[str, object] = {"jobName": "", "offset": page, "limit": limit}
        params.update(native_params or {})
        params["offset"] = page
        params["limit"] = limit
        response = self._get(
            LIST_URL,
            params=params,
            headers={
                "Referer": INTERNSHIP_URL if "03" in str(params.get("jobType") or "") else WORK_URL
            },
        )
        jobs, data = parse_list_payload(self._json(response))
        pagination = data.get("pagenation") or data.get("pagination") or {}
        candidates = []
        if isinstance(pagination, dict):
            candidates.extend(
                pagination.get(key)
                for key in ("count", "total", "totalCount", "recordsTotal")
            )
        candidates.extend(data.get(key) for key in ("total", "totalCount", "recordsTotal"))
        total = next(
            (
                int(value)
                for value in candidates
                if value not in (None, "") and str(value).strip().isdigit()
            ),
            None,
        )
        if total is None:
            raise ResponseError("NCSS list response is missing remote total")
        return ListPage(tuple(jobs), total, page, limit)

    def _fetch_page_once(self, page: int, limit: int) -> list[Job]:
        return list(self._fetch_page_result_once(page, limit).jobs)

    def verify_authenticated(self) -> bool:
        self._fetch_page_once(6, 1)
        return True

    def fetch_page(self, page: int, limit: int = 20) -> list[Job]:
        return list(self.fetch_page_result(page, limit).jobs)

    def fetch_page_result(
        self,
        page: int,
        limit: int = 20,
        native_params: dict[str, object] | None = None,
    ) -> ListPage:
        if page < 1:
            raise ValueError("page must be at least 1")
        if limit < 1:
            raise ValueError("limit must be at least 1")
        try:
            return self._fetch_page_result_once(page, limit, native_params)
        except AuthenticationRequired:
            raise
        except Exception:
            self._check_running()
            self.sleeper(REQUEST_RETRY_WAIT_SECONDS)
            self._check_running()
            return self._fetch_page_result_once(page, limit, native_params)

    def fetch_detail(self, job: Job) -> Job:
        url = job.source_url or DETAIL_URL.format(job_id=job.job_id)
        response = self._get(url)
        return parse_detail_html(response.text, job)
