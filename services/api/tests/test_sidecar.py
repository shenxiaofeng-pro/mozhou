from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import DatabaseIntegrityError, DatabaseMigrationError
from app.runtime import (
    DEFER_JOB_RUNTIME_ENV,
    INSECURE_DEV_ENV,
    SESSION_TOKEN_ENV,
    create_runtime_app,
)
from app.sidecar import (
    parse_args,
    startup_failure_for,
    wait_for_parent_disconnect,
    write_startup_failure,
)


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


def test_desktop_can_restore_credentials_before_starting_job_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_token = "b" * 64
    monkeypatch.setenv(SESSION_TOKEN_ENV, session_token)
    monkeypatch.setenv(DEFER_JOB_RUNTIME_ENV, "1")
    monkeypatch.setenv("MOZHOU_DATA_DIR", str(tmp_path))
    application = create_runtime_app()

    with TestClient(application) as client:
        assert application.state.job_runtime.is_running is False
        response = client.post(
            "/api/runtime/start",
            headers={"X-Mozhou-Session-Token": session_token},
        )
        assert response.json() == {"status": "running"}
        assert application.state.job_runtime.is_running is True


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (DatabaseIntegrityError("private sqlite detail"), "database_integrity"),
        (DatabaseMigrationError("private migration detail"), "database_migration_failed"),
        (RuntimeError("private runtime detail"), "local_api_startup_failed"),
    ],
)
def test_startup_failure_status_is_actionable_and_sanitized(
    tmp_path: Path,
    error: BaseException,
    code: str,
) -> None:
    status_file = tmp_path / "runtime" / "startup-status.json"
    failure = startup_failure_for(error)

    write_startup_failure(status_file, failure)
    payload = status_file.read_text(encoding="utf-8")

    assert failure.code == code
    assert code in payload
    assert "private" not in payload
    assert str(tmp_path) not in payload
