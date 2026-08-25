from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import urlopen

from .client import BrowserCookie
from .config import LOGIN_URL, PERSON_CENTER_URL
from .credentials import Credentials
from .errors import ShutdownRequested
from .process_control import ProcessOwner


class CdpError(RuntimeError):
    pass


class UnexpectedLoginPage(CdpError):
    pass


class CdpConnection:
    def __init__(self, websocket: Any) -> None:
        self.websocket = websocket
        self._next_id = 0

    def command(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        self._next_id += 1
        command_id = self._next_id
        self.websocket.send(
            json.dumps({"id": command_id, "method": method, "params": params or {}})
        )
        while True:
            message = json.loads(self.websocket.recv())
            if message.get("id") != command_id:
                continue
            if "error" in message:
                error = message["error"]
                if isinstance(error, dict):
                    error = error.get("message") or error
                raise CdpError(str(error))
            result = message.get("result", {})
            if not isinstance(result, dict):
                raise CdpError(f"invalid CDP result for {method}")
            return result

    def evaluate(self, expression: str) -> object:
        result = self.command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        remote = result.get("result", {})
        if not isinstance(remote, dict):
            raise CdpError("invalid Runtime.evaluate result")
        if remote.get("subtype") == "error":
            raise CdpError(str(remote.get("description") or "JavaScript evaluation failed"))
        return remote.get("value")

    def close(self) -> None:
        self.websocket.close()


def fill_login_form(cdp: CdpConnection, credentials: Credentials) -> None:
    current_url = str(cdp.evaluate("location.href") or "")
    parsed = urlsplit(current_url)
    if parsed.hostname != "account.chsi.com.cn" or parsed.path != "/passport/login":
        raise UnexpectedLoginPage(f"refusing to fill credentials on {parsed.hostname or 'unknown'}{parsed.path}")
    username = json.dumps(credentials.username, ensure_ascii=False)
    password = json.dumps(credentials.password, ensure_ascii=False)
    expression = f"""
(() => {{
  if (location.hostname !== "account.chsi.com.cn" || location.pathname !== "/passport/login") {{
    return {{ok: false, reason: "unexpected login origin"}};
  }}
  const username = document.querySelector('#username, input[name="username"], input[name="loginName"]');
  const password = document.querySelector('#password, input[name="password"]');
  const form = password && password.closest('form');
  const submit = form && form.querySelector('button[type="submit"], input[type="submit"], button.login-btn');
  if (!username || !password || !form || !submit) {{
    return {{ok: false, reason: "missing login form fields"}};
  }}
  const setValue = (element, value) => {{
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(element, value);
    element.dispatchEvent(new Event('input', {{bubbles: true}}));
    element.dispatchEvent(new Event('change', {{bubbles: true}}));
  }};
  setValue(username, {username});
  setValue(password, {password});
  submit.click();
  return {{ok: true}};
}})()
""".strip()
    result = cdp.evaluate(expression)
    if not isinstance(result, dict) or result.get("ok") is not True:
        reason = result.get("reason") if isinstance(result, dict) else "invalid script result"
        raise UnexpectedLoginPage(str(reason))


class ChromeBrowser:
    def __init__(
        self,
        profile_dir: Path,
        *,
        executable: str | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.executable = executable or self.find_executable()
        self.sleeper = sleeper
        self.stop_requested = stop_requested
        self.owner: ProcessOwner | None = None
        self.cdp: CdpConnection | None = None

    @staticmethod
    def find_executable() -> str:
        candidates = [
            os.environ.get("NCSS_HARVES_CHROME_PATH", ""),
            str(Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe"),
            str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        raise FileNotFoundError("找不到 Google Chrome；请设置 NCSS_HARVES_CHROME_PATH")

    @staticmethod
    def read_devtools_port(profile_dir: Path) -> tuple[int, str]:
        lines = (Path(profile_dir) / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
        if len(lines) < 2:
            raise CdpError("invalid DevToolsActivePort")
        try:
            port = int(lines[0])
        except ValueError as exc:
            raise CdpError("invalid DevTools port") from exc
        return port, lines[1]

    def start(self, url: str = LOGIN_URL, *, timeout: float = 15.0) -> "ChromeBrowser":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        active_port = self.profile_dir / "DevToolsActivePort"
        active_port.unlink(missing_ok=True)
        command = [
            self.executable,
            f"--user-data-dir={self.profile_dir.resolve()}",
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ]
        self.owner = ProcessOwner.spawn(command)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stop_requested():
                self.close()
                raise ShutdownRequested("shutdown requested during Chrome startup")
            if self.owner.process.poll() is not None:
                self.close()
                raise CdpError("Chrome 启动失败；专用 Profile 可能正被其他进程占用")
            try:
                port, _ = self.read_devtools_port(self.profile_dir)
                target_url = self._page_websocket_url(port)
                self.cdp = self._connect(target_url)
                self.cdp.command("Page.enable")
                if not self.is_business_url(self.current_url()):
                    self.navigate(url)
                while time.monotonic() < deadline:
                    if self.stop_requested():
                        self.close()
                        raise ShutdownRequested("shutdown requested during Chrome startup")
                    if self.is_business_url(self.current_url()):
                        return self
                    self.sleeper(0.1)
            except (FileNotFoundError, OSError, ValueError, CdpError):
                self.sleeper(0.1)
        self.close()
        raise TimeoutError("等待 Chrome CDP 启动超时")

    @staticmethod
    def _page_websocket_url(port: int) -> str:
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2.0) as response:
            targets = json.loads(response.read().decode("utf-8"))
        if not isinstance(targets, list):
            raise CdpError("invalid Chrome target list")
        return ChromeBrowser.select_page_websocket_url(targets)

    @staticmethod
    def is_business_url(url: str) -> bool:
        hostname = (urlsplit(str(url)).hostname or "").lower()
        return hostname == "account.chsi.com.cn" or hostname == "ncss.cn" or hostname.endswith(".ncss.cn")

    @staticmethod
    def select_page_websocket_url(targets: list[object]) -> str:
        pages = [
            target
            for target in targets
            if isinstance(target, dict)
            and target.get("type") == "page"
            and target.get("webSocketDebuggerUrl")
        ]
        for target in pages:
            if ChromeBrowser.is_business_url(str(target.get("url") or "")):
                return str(target["webSocketDebuggerUrl"])
        if pages:
            return str(pages[0]["webSocketDebuggerUrl"])
        raise CdpError("Chrome 没有可用页面")

    @staticmethod
    def _connect(url: str) -> CdpConnection:
        try:
            import websocket
        except ImportError as exc:  # pragma: no cover - installation dependent
            raise RuntimeError("websocket-client is required for Chrome login") from exc
        return CdpConnection(
            websocket.create_connection(url, timeout=5.0, suppress_origin=True)
        )

    def _require_cdp(self) -> CdpConnection:
        if self.cdp is None:
            raise CdpError("Chrome CDP is not connected")
        return self.cdp

    def current_url(self) -> str:
        return str(self._require_cdp().evaluate("location.href") or "")

    def navigate(self, url: str) -> None:
        self._require_cdp().command("Page.navigate", {"url": url})

    def redirect_exception_page(self) -> bool:
        if urlsplit(self.current_url()).path != "/student/exception.html":
            return False
        self.navigate(PERSON_CENTER_URL)
        return True

    def establish_login(self, credentials: Credentials, *, timeout: float = 120.0) -> None:
        cdp = self._require_cdp()
        deadline = time.monotonic() + timeout
        submitted = False
        while time.monotonic() < deadline:
            if self.stop_requested():
                raise ShutdownRequested("shutdown requested during browser login")
            current = self.current_url()
            parsed = urlsplit(current)
            if parsed.hostname == "account.chsi.com.cn" and parsed.path == "/passport/login":
                if not submitted:
                    fill_login_form(cdp, credentials)
                    submitted = True
            elif parsed.hostname and parsed.hostname.endswith("ncss.cn"):
                if parsed.path == "/student/exception.html":
                    self.navigate(PERSON_CENTER_URL)
                else:
                    return
            self.sleeper(0.25)
        raise TimeoutError("等待 NCSS 登录跳转超时")

    def cookies(self) -> tuple[BrowserCookie, ...]:
        result = self._require_cdp().command("Storage.getCookies")
        cookies = result.get("cookies", [])
        if not isinstance(cookies, list):
            raise CdpError("invalid Storage.getCookies result")
        exported: list[BrowserCookie] = []
        for item in cookies:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "")
            normalized = domain.lstrip(".")
            if not (normalized.endswith("ncss.cn") or normalized.endswith("chsi.com.cn")):
                continue
            exported.append(
                BrowserCookie(
                    name=str(item.get("name") or ""),
                    value=str(item.get("value") or ""),
                    domain=domain,
                    path=str(item.get("path") or "/"),
                    secure=bool(item.get("secure", False)),
                )
            )
        return tuple(cookie for cookie in exported if cookie.name)

    def user_agent(self) -> str:
        return str(self._require_cdp().evaluate("navigator.userAgent") or "")

    def close(self) -> None:
        cdp, owner = getattr(self, "cdp", None), getattr(self, "owner", None)
        self.cdp = None
        self.owner = None
        if cdp is not None:
            try:
                cdp.command("Browser.close")
            except Exception:
                pass
            try:
                cdp.close()
            except Exception:
                pass
        if owner is not None:
            owner.close()

    def __enter__(self) -> "ChromeBrowser":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()
