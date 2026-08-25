from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import signal
from typing import Callable, Sequence

from ..auth import AuthManager, CredentialsRequired
from ..cdp import ChromeBrowser
from ..client import NcssClient
from ..collector import Collector
from ..config import CHROME_PROFILE_DIR, CREDENTIAL_PATH, DATABASE_PATH
from ..credentials import CredentialStore, Credentials
from ..crawl_coordinator import CrawlCoordinator
from ..crawl_service import CrawlService
from ..errors import ShutdownRequested
from ..http_server import create_server
from ..logging_utils import configure_logging
from ..service import ApplicationService
from ..shutdown import ShutdownCoordinator
from ..storage import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ncss-harves",
        description="NCSS 浏览器认证、本地缓存与岗位查询服务",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="使用账号密码登录并保存加密账密")
    login.add_argument("--username", help="登录账号；省略时交互输入")
    login.add_argument("--credentials", type=Path, default=CREDENTIAL_PATH, help="加密账密文件路径")
    login.add_argument("--profile", type=Path, default=CHROME_PROFILE_DIR, help="专用 Chrome Profile")
    login.add_argument("--chrome-path", help="Google Chrome 可执行文件路径")

    serve = subparsers.add_parser("serve", help="启动本地查询与按需采集服务")
    serve.add_argument("--host", default="127.0.0.1", help="监听地址")
    serve.add_argument("--port", type=int, default=9091, help="监听端口")
    serve.add_argument("--database", type=Path, default=DATABASE_PATH, help="SQLite 数据库路径")
    serve.add_argument("--credentials", type=Path, default=CREDENTIAL_PATH, help="加密账密文件路径")
    serve.add_argument("--profile", type=Path, default=CHROME_PROFILE_DIR, help="专用 Chrome Profile")
    serve.add_argument("--chrome-path", help="Google Chrome 可执行文件路径")
    return parser


def prompt_credentials(
    *,
    username: str | None = None,
    input_fn: Callable[[str], str] = input,
    password_fn: Callable[[str], str] = getpass.getpass,
) -> Credentials:
    while not (username or "").strip():
        username = input_fn("NCSS 账号: ").strip()
    password = ""
    while not password:
        password = password_fn("NCSS 密码: ")
    return Credentials(username.strip(), password)


def _auth(
    args: argparse.Namespace,
    output: Callable[[str], None] = print,
    stop_requested: Callable[[], bool] = lambda: False,
) -> AuthManager:
    return AuthManager(
        browser_factory=lambda task_stop_requested: ChromeBrowser(
            args.profile,
            executable=args.chrome_path,
            stop_requested=lambda: stop_requested() or task_stop_requested(),
        ),
        credential_store=CredentialStore(args.credentials),
        output=output,
    )


def run_login(args: argparse.Namespace) -> int:
    auth = _auth(args)
    try:
        while True:
            credentials = prompt_credentials(username=args.username)
            try:
                auth.establish(credentials)
                return 0
            except CredentialsRequired as exc:
                print(f"登录失败：{exc}")
                args.username = None
    finally:
        auth.close()


def _install_signals(shutdown: ShutdownCoordinator) -> None:
    def request_stop(_signum: int, _frame: object) -> None:
        shutdown.request_stop()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, request_stop)


def run_serve(args: argparse.Namespace) -> int:
    shutdown = ShutdownCoordinator()
    logger = configure_logging()
    repository = Repository(args.database)
    auth = _auth(args, stop_requested=lambda: shutdown.stopping)
    crawl_service = CrawlService(
        repository=repository,
        client_factory=lambda cancel: NcssClient(
            auth.session(),
            stop_requested=lambda: shutdown.stopping or cancel.is_set(),
        ),
        relogin=lambda task_stop: auth.establish_saved(stop_requested=task_stop),
        shutdown=shutdown,
    )
    crawl_coordinator = CrawlCoordinator(crawl_service.crawl)
    service = ApplicationService(
        repository=repository,
        auth=auth,
        shutdown=shutdown,
        http_factory=lambda: create_server(
            args.host,
            args.port,
            repository=repository,
            shutdown=shutdown,
            logger=logger,
            crawl_coordinator=crawl_coordinator,
        ),
        collector_factory=lambda session: Collector(
            NcssClient(session, stop_requested=lambda: shutdown.stopping)
        ),
        prompt_credentials=prompt_credentials,
        logger=logger,
        crawl_coordinator=crawl_coordinator,
    )
    _install_signals(shutdown)
    try:
        service.run()
        return 0
    except KeyboardInterrupt:
        shutdown.request_stop()
        return 130
    except ShutdownRequested:
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "login":
        return run_login(args)
    if args.command == "serve":
        return run_serve(args)
    parser.error("需要 login 或 serve")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
