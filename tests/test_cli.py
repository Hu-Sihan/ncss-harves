from __future__ import annotations

import pytest

from ncss_harves.cli.main import build_parser, main


def test_cli_has_only_login_and_serve_commands() -> None:
    parser = build_parser()
    action = next(action for action in parser._actions if action.dest == "command")
    assert set(action.choices) == {"login", "serve"}


def test_serve_defaults() -> None:
    args = build_parser().parse_args(["serve"])
    assert args.host == "127.0.0.1"
    assert args.port == 9091


@pytest.mark.parametrize("removed", ["task-add", "crawl", "query-or-crawl", "init-db"])
def test_removed_commands_are_rejected(removed: str) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([removed])


def test_main_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_login_password_is_not_a_command_line_argument() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["login", "--password", "secret"])
