from __future__ import annotations

import threading
import time
from typing import Any, Callable

import requests

from .cdp import ChromeBrowser
from .client import NcssClient, session_from_browser
from .credentials import CredentialStore, Credentials
from .errors import AuthenticationRequired, ResponseError


class CredentialsRequired(RuntimeError):
    """Automatic login cannot continue without new interactive credentials."""


class AuthManager:
    def __init__(
        self,
        *,
        browser_factory: Callable[[Callable[[], bool]], ChromeBrowser],
        credential_store: CredentialStore,
        client_factory: Callable[[Any], NcssClient] = NcssClient,
        session_factory: Callable[[Any, str], requests.Session] = session_from_browser,
        sleeper: Callable[[float], None] = time.sleep,
        output: Callable[[str], None] = print,
    ) -> None:
        self.browser_factory = browser_factory
        self.credential_store = credential_store
        self.client_factory = client_factory
        self.session_factory = session_factory
        self.sleeper = sleeper
        self.output = output
        self._login_lock = threading.Lock()
        self._session_lock = threading.Lock()
        self.current_session: requests.Session | Any | None = None

    def establish_saved(
        self, stop_requested: Callable[[], bool] = lambda: False
    ) -> requests.Session:
        credentials = self.credential_store.load()
        if credentials is None:
            raise CredentialsRequired("找不到加密账密文件，需要重新输入账号密码")
        return self.establish(credentials, stop_requested=stop_requested)

    def establish(
        self,
        credentials: Credentials,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> requests.Session:
        with self._login_lock:
            browser = self.browser_factory(stop_requested)
            with browser:
                try:
                    browser.establish_login(credentials)
                except TimeoutError as exc:
                    raise CredentialsRequired("浏览器登录未完成，需要重新输入账号密码") from exc
                for attempt in range(2):
                    session = self.session_factory(browser.cookies(), browser.user_agent())
                    verified = False
                    try:
                        verified = self.client_factory(session).verify_authenticated()
                    except (AuthenticationRequired, ResponseError, requests.RequestException):
                        verified = False
                    if verified:
                        try:
                            self.credential_store.save(credentials)
                        except Exception:
                            session.close()
                            raise
                        self._replace_session(session)
                        self.output("NCSS 登录成功，第 6 页验证通过。")
                        return session
                    session.close()
                    if attempt == 0:
                        self.sleeper(5.0)
            raise CredentialsRequired("NCSS 第 6 页连续两次验证失败，需要重新输入账号密码")

    def _replace_session(self, session: requests.Session) -> None:
        with self._session_lock:
            old_session = self.current_session
            self.current_session = session
        if old_session is not None and old_session is not session:
            old_session.close()

    def session(self) -> requests.Session:
        with self._session_lock:
            if self.current_session is None:
                raise CredentialsRequired("当前没有可用的 NCSS 会话")
            return self.current_session

    def close(self) -> None:
        with self._session_lock:
            session = self.current_session
            self.current_session = None
        if session is not None:
            session.close()
