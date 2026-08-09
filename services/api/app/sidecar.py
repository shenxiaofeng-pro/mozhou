import argparse
import os
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import BinaryIO

import uvicorn


@dataclass(frozen=True)
class SidecarArguments:
    host: str
    port: int


def _valid_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(argv: Sequence[str] | None = None) -> SidecarArguments:
    parser = argparse.ArgumentParser(description="Mozhou local API sidecar")
    parser.add_argument("--port", type=_valid_port, required=True)
    namespace = parser.parse_args(argv)
    return SidecarArguments(host="127.0.0.1", port=namespace.port)


def wait_for_parent_disconnect(
    stream: BinaryIO,
    terminate: Callable[[int], object],
) -> None:
    try:
        while stream.read(1):
            pass
    finally:
        terminate(0)


def start_parent_disconnect_watchdog() -> None:
    watchdog = threading.Thread(
        target=wait_for_parent_disconnect,
        args=(sys.stdin.buffer, os._exit),
        name="mozhou-parent-watchdog",
        daemon=True,
    )
    watchdog.start()


def main(argv: Sequence[str] | None = None) -> None:
    arguments = parse_args(argv)
    start_parent_disconnect_watchdog()
    from app.main import app

    uvicorn.run(
        app,
        host=arguments.host,
        port=arguments.port,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
