import socket
from collections.abc import Iterator
from typing import Any

import pytest
from gateway_fixtures import LIVE_TESTS


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail any test that tries to open a network connection (unless live tests are on)."""
    if not LIVE_TESTS:

        def refuse(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("Network access is disabled in tests; use recorded fixtures")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)
        monkeypatch.setattr(socket, "getaddrinfo", refuse)
    yield
