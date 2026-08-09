from io import BytesIO

import pytest

from app.runtime import INSECURE_DEV_ENV, SESSION_TOKEN_ENV, create_runtime_app
from app.sidecar import parse_args, wait_for_parent_disconnect


def test_sidecar_uses_loopback_and_accepts_selected_port() -> None:
    arguments = parse_args(["--port", "54321"])

    assert arguments.host == "127.0.0.1"
    assert arguments.port == 54321


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_sidecar_rejects_invalid_port(value: str) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--port", value])


def test_sidecar_terminates_when_parent_stdin_closes() -> None:
    exit_codes: list[int] = []

    wait_for_parent_disconnect(BytesIO(b""), exit_codes.append)

    assert exit_codes == [0]


def test_runtime_refuses_to_start_without_token_or_explicit_development_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SESSION_TOKEN_ENV, raising=False)
    monkeypatch.delenv(INSECURE_DEV_ENV, raising=False)

    with pytest.raises(RuntimeError, match=INSECURE_DEV_ENV):
        create_runtime_app()


def test_runtime_allows_explicit_insecure_browser_development_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SESSION_TOKEN_ENV, raising=False)
    monkeypatch.setenv(INSECURE_DEV_ENV, "1")

    with pytest.warns(RuntimeWarning, match="无会话令牌"):
        application = create_runtime_app()

    assert application.title == "墨舟本地 API"


def test_runtime_accepts_the_desktop_session_token_without_development_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SESSION_TOKEN_ENV, "a" * 64)
    monkeypatch.delenv(INSECURE_DEV_ENV, raising=False)

    application = create_runtime_app()

    assert application.title == "墨舟本地 API"
