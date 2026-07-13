import socket
from collections.abc import Generator
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def block_unmocked_network(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    original_connect = socket.socket.connect

    def guarded_connect(sock: socket.socket, address: Any) -> None:
        if isinstance(address, tuple) and address:
            host = str(address[0]).lower()
            if host in {"127.0.0.1", "::1", "localhost"}:
                original_connect(sock, address)
                return
        raise AssertionError("Tests must not make live network requests")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield
