from io import BytesIO

import pytest

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
