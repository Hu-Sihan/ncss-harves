from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ncss_harves.cdp import (
    CdpConnection,
    CdpError,
    ChromeBrowser,
    UnexpectedLoginPage,
    fill_login_form,
)
from ncss_harves.client import BrowserCookie
from ncss_harves.config import PERSON_CENTER_URL
from ncss_harves.credentials import Credentials
from ncss_harves import process_control
from ncss_harves.process_control import ProcessOwner, _WindowsJobBackend


class FakeSocket:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = [json.dumps(message) for message in messages]
        self.sent: list[dict[str, object]] = []
        self.closed = False

    def send(self, value: str) -> None:
        self.sent.append(json.loads(value))

    def recv(self) -> str:
        return self.messages.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeCdp:
    def __init__(self, *, url: str, form_result: object = None) -> None:
        self.url = url
        self.form_result = form_result if form_result is not None else {"ok": True}
        self.expressions: list[str] = []
        self.commands: list[tuple[str, dict[str, object]]] = []

    def evaluate(self, expression: str) -> object:
        self.expressions.append(expression)
        if "location.href" in expression and "hostname" not in expression:
            return self.url
        return self.form_result

    def command(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        params = params or {}
        self.commands.append((method, params))
        if method == "Storage.getCookies":
            return {
                "cookies": [
                    {"name": "NCSS", "value": "a", "domain": ".ncss.cn", "path": "/", "secure": True},
                    {"name": "CHSI", "value": "b", "domain": "account.chsi.com.cn", "path": "/"},
                    {"name": "OTHER", "value": "c", "domain": ".example.com", "path": "/"},
                ]
            }
        return {}


def test_cdp_command_ignores_events_and_matches_id() -> None:
    socket = FakeSocket(
        [
            {"method": "Network.loadingFinished", "params": {}},
            {"id": 1, "result": {"value": "ok"}},
        ]
    )
    connection = CdpConnection(socket)  # type: ignore[arg-type]

    assert connection.command("Runtime.test") == {"value": "ok"}
    assert socket.sent == [{"id": 1, "method": "Runtime.test", "params": {}}]


def test_cdp_command_surfaces_protocol_error() -> None:
    connection = CdpConnection(FakeSocket([{"id": 1, "error": {"message": "denied"}}]))  # type: ignore[arg-type]

    with pytest.raises(CdpError, match="denied"):
        connection.command("Storage.getCookies")


def test_login_script_refuses_non_chsi_page() -> None:
    cdp = FakeCdp(url="https://www.ncss.cn/student/jobs/index.html")

    with pytest.raises(UnexpectedLoginPage):
        fill_login_form(cdp, Credentials("user", "password"))  # type: ignore[arg-type]


def test_login_script_submits_only_valid_chsi_form() -> None:
    cdp = FakeCdp(url="https://account.chsi.com.cn/passport/login?service=test")

    fill_login_form(cdp, Credentials("user-value", "password-value"))  # type: ignore[arg-type]

    expression = cdp.expressions[-1]
    assert "account.chsi.com.cn" in expression
    assert "/passport/login" in expression
    assert json.dumps("user-value") in expression
    assert json.dumps("password-value") in expression


def test_login_script_reports_missing_fields() -> None:
    cdp = FakeCdp(
        url="https://account.chsi.com.cn/passport/login",
        form_result={"ok": False, "reason": "missing login form fields"},
    )

    with pytest.raises(UnexpectedLoginPage, match="missing login form fields"):
        fill_login_form(cdp, Credentials("user", "password"))  # type: ignore[arg-type]


def test_exception_page_is_redirected_to_person_center() -> None:
    cdp = FakeCdp(url="https://www.ncss.cn/student/exception.html")
    browser = ChromeBrowser.__new__(ChromeBrowser)
    browser.cdp = cdp

    assert browser.redirect_exception_page() is True
    assert cdp.commands[-1] == ("Page.navigate", {"url": PERSON_CENTER_URL})


def test_cookie_export_only_includes_chsi_and_ncss_domains() -> None:
    cdp = FakeCdp(url="https://www.ncss.cn/student/resume/personcenter.html")
    browser = ChromeBrowser.__new__(ChromeBrowser)
    browser.cdp = cdp

    assert browser.cookies() == (
        BrowserCookie("NCSS", "a", ".ncss.cn", "/", True),
        BrowserCookie("CHSI", "b", "account.chsi.com.cn", "/", False),
    )


def test_process_owner_only_closes_spawned_process() -> None:
    spawned = Mock(pid=123)
    unrelated = Mock(pid=456)
    backend = Mock()
    owner = ProcessOwner(spawned, backend=backend)

    owner.close()

    backend.close.assert_called_once_with(spawned)
    unrelated.terminate.assert_not_called()


def test_windows_job_object_uses_empty_anonymous_name(monkeypatch: pytest.MonkeyPatch) -> None:
    job_handle = Mock()
    process_handle = Mock()
    create_job = Mock(return_value=job_handle)
    win32job = SimpleNamespace(
        CreateJobObject=create_job,
        QueryInformationJobObject=Mock(return_value={"BasicLimitInformation": {"LimitFlags": 0}}),
        SetInformationJobObject=Mock(),
        AssignProcessToJobObject=Mock(),
        JobObjectExtendedLimitInformation=9,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x2000,
    )
    win32api = SimpleNamespace(OpenProcess=Mock(return_value=process_handle))
    win32con = SimpleNamespace(PROCESS_SET_QUOTA=1, PROCESS_TERMINATE=2)
    monkeypatch.setitem(sys.modules, "win32job", win32job)
    monkeypatch.setitem(sys.modules, "win32api", win32api)
    monkeypatch.setitem(sys.modules, "win32con", win32con)

    _WindowsJobBackend(Mock(pid=123))

    create_job.assert_called_once_with(None, "")
    process_handle.Close.assert_called_once()


def test_spawn_cleans_exact_process_when_owner_initialization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock(pid=321)
    cleanup = Mock()
    monkeypatch.setattr(process_control.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(process_control, "_cleanup_failed_spawn", cleanup, raising=False)

    def fail_owner(_self: object, _process: object, **_kwargs: object) -> None:
        raise RuntimeError("job object failed")

    monkeypatch.setattr(ProcessOwner, "__init__", fail_owner)

    with pytest.raises(RuntimeError, match="job object failed"):
        ProcessOwner.spawn(["chrome.exe"])

    cleanup.assert_called_once_with(process)


def test_devtools_active_port_is_read_from_profile(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text("43123\n/devtools/browser/id\n", encoding="utf-8")

    assert ChromeBrowser.read_devtools_port(profile) == (43123, "/devtools/browser/id")


def test_cdp_target_prefers_chsi_or_ncss_over_about_blank() -> None:
    targets = [
        {"type": "page", "url": "about:blank", "webSocketDebuggerUrl": "ws://blank"},
        {
            "type": "page",
            "url": "https://account.chsi.com.cn/passport/login?service=ncss",
            "webSocketDebuggerUrl": "ws://login",
        },
    ]

    assert ChromeBrowser.select_page_websocket_url(targets) == "ws://login"


def test_cdp_target_accepts_ncss_page_after_single_sign_on_redirect() -> None:
    targets = [
        {"type": "page", "url": "chrome://newtab/", "webSocketDebuggerUrl": "ws://newtab"},
        {
            "type": "page",
            "url": "https://www.ncss.cn/student/exception.html",
            "webSocketDebuggerUrl": "ws://ncss",
        },
    ]

    assert ChromeBrowser.select_page_websocket_url(targets) == "ws://ncss"


def test_only_chsi_or_ncss_urls_are_business_pages() -> None:
    assert ChromeBrowser.is_business_url("https://account.chsi.com.cn/passport/login") is True
    assert ChromeBrowser.is_business_url("https://www.ncss.cn/student/exception.html") is True
    assert ChromeBrowser.is_business_url("about:blank") is False
    assert ChromeBrowser.is_business_url("chrome://newtab/") is False
