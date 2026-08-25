from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

import pytest
import requests

from ncss_harves.client import BrowserCookie, NcssClient, session_from_browser
from ncss_harves.errors import AuthenticationRequired, ResponseError, ShutdownRequested
from ncss_harves.models import Job


@dataclass
class FakeResponse:
    payload: object | None = None
    text: str = ""
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self) -> object:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, FakeResponse)
        return response


def list_response(count: int = 1) -> FakeResponse:
    jobs = [{"jobId": f"job-{index}", "jobName": f"岗位 {index}"} for index in range(count)]
    return FakeResponse({"flag": True, "data": {"list": jobs, "total": count}})


def auth_response() -> FakeResponse:
    return FakeResponse({"flag": False, "data": None, "global": [{"des": "请登录后查看"}]})


def test_verify_uses_page_six() -> None:
    session = FakeSession([list_response()])
    client = NcssClient(session)  # type: ignore[arg-type]

    assert client.verify_authenticated() is True
    assert session.calls[-1]["params"] == {"jobName": "", "offset": 6, "limit": 1}


def test_verify_rejects_login_business_response() -> None:
    client = NcssClient(FakeSession([auth_response()]))  # type: ignore[arg-type]

    with pytest.raises(AuthenticationRequired, match="请登录"):
        client.verify_authenticated()


def test_list_retries_once_after_five_seconds() -> None:
    session = FakeSession([requests.Timeout(), list_response(2)])
    sleeper = Mock()
    client = NcssClient(session, sleeper=sleeper)  # type: ignore[arg-type]

    assert [job.job_id for job in client.fetch_page(1, 20)] == ["job-0", "job-1"]
    sleeper.assert_called_once_with(5.0)
    assert len(session.calls) == 2


def test_list_only_retries_once() -> None:
    session = FakeSession([requests.Timeout(), requests.ConnectionError()])
    client = NcssClient(session, sleeper=Mock())  # type: ignore[arg-type]

    with pytest.raises(requests.ConnectionError):
        client.fetch_page(1, 20)
    assert len(session.calls) == 2


def test_authentication_error_is_not_retried() -> None:
    session = FakeSession([auth_response(), list_response()])
    sleeper = Mock()
    client = NcssClient(session, sleeper=sleeper)  # type: ignore[arg-type]

    with pytest.raises(AuthenticationRequired):
        client.fetch_page(7, 20)
    assert len(session.calls) == 1
    sleeper.assert_not_called()


def test_detail_is_requested_once_and_parsed() -> None:
    html = '<h1 id="jobName">数据工程师</h1><div class="jobdetail-box">建设数据平台</div>'
    session = FakeSession([FakeResponse(text=html)])
    client = NcssClient(session)  # type: ignore[arg-type]

    result = client.fetch_detail(Job(job_id="abc", job_name="旧名称"))

    assert result.job_name == "数据工程师"
    assert result.description == "建设数据平台"
    assert session.calls[0]["timeout"] == 10.0
    assert session.calls[0]["url"].endswith("/abc/detail.html")


def test_detail_does_not_retry_normal_failure() -> None:
    session = FakeSession([requests.Timeout(), FakeResponse(text="unused")])
    client = NcssClient(session, sleeper=Mock())  # type: ignore[arg-type]

    with pytest.raises(requests.Timeout):
        client.fetch_detail(Job(job_id="abc"))
    assert len(session.calls) == 1


def test_stop_is_checked_before_request_and_retry() -> None:
    state = {"stopping": True}
    session = FakeSession([list_response()])
    client = NcssClient(session, stop_requested=lambda: state["stopping"])  # type: ignore[arg-type]

    with pytest.raises(ShutdownRequested):
        client.fetch_page(1)
    assert session.calls == []

    state["stopping"] = False
    session.responses = [requests.Timeout(), list_response()]
    sleeper = Mock(side_effect=lambda _: state.update(stopping=True))
    client = NcssClient(session, sleeper=sleeper, stop_requested=lambda: state["stopping"])  # type: ignore[arg-type]
    with pytest.raises(ShutdownRequested):
        client.fetch_page(1)
    assert len(session.calls) == 1


def test_session_from_browser_copies_headers_and_cookie_scope() -> None:
    cookies = [BrowserCookie("SESSION", "value", ".ncss.cn", "/student", secure=True)]
    session = session_from_browser(cookies, "Real Chrome UA")

    assert session.headers["User-Agent"] == "Real Chrome UA"
    assert session.headers["X-Requested-With"] == "XMLHttpRequest"
    cookie = next(iter(session.cookies))
    assert (cookie.name, cookie.value, cookie.domain, cookie.path, cookie.secure) == (
        "SESSION", "value", ".ncss.cn", "/student", True
    )


def test_invalid_json_is_a_response_error() -> None:
    session = FakeSession([FakeResponse(ValueError("bad json")), FakeResponse(ValueError("bad json"))])
    client = NcssClient(session, sleeper=Mock())  # type: ignore[arg-type]

    with pytest.raises(ResponseError, match="invalid JSON"):
        client.fetch_page(1)


def test_fetch_page_result_uses_native_params_and_remote_total() -> None:
    session = FakeSession([
        FakeResponse(
            {
                "flag": True,
                "data": {
                    "list": [{"jobId": "1", "jobName": "岗位"}],
                    "pagenation": {"total": 321},
                },
            }
        )
    ])
    client = NcssClient(session)  # type: ignore[arg-type]

    result = client.fetch_page_result(
        7, 40, {"areaCode": "110000", "jobType": "03"}
    )

    assert result.total == 321
    assert result.page == 7
    assert result.limit == 40
    assert [job.job_id for job in result.jobs] == ["1"]
    assert session.calls[0]["params"] == {
        "jobName": "",
        "offset": 7,
        "limit": 40,
        "areaCode": "110000",
        "jobType": "03",
    }


def test_fetch_page_result_prefers_web_page_count() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "flag": True,
                    "data": {
                        "list": [],
                        "pagenation": {"count": 306_284, "total": 50},
                    },
                }
            )
        ]
    )
    client = NcssClient(session)  # type: ignore[arg-type]

    assert client.fetch_page_result(1, 20).total == 306_284


def test_internship_list_uses_internship_referer() -> None:
    session = FakeSession([list_response()])
    client = NcssClient(session)  # type: ignore[arg-type]

    client.fetch_page_result(1, 20, {"jobType": "03"})

    assert session.calls[0]["headers"]["Referer"].endswith("/internindex.html")


def test_missing_remote_total_is_rejected() -> None:
    response = FakeResponse({"flag": True, "data": {"list": []}})
    client = NcssClient(FakeSession([response, response]), sleeper=Mock())  # type: ignore[arg-type]

    with pytest.raises(ResponseError, match="remote total"):
        client.fetch_page_result(1, 20)
