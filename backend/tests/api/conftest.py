"""API test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_sse_exit_signal() -> Iterator[None]:
    """Clear ``sse_starlette``'s process-global shutdown event between tests.

    The library caches an ``asyncio.Event`` on a module-level singleton so a running
    server can tell streams to stop. Each ``TestClient`` spins up its own event loop, so
    the second test in a module inherits an event bound to the first test's loop and
    every stream fails with "bound to a different event loop". Nothing about the
    application is wrong; the fixture just gives each loop a clean singleton.
    """
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    yield
    AppStatus.should_exit_event = None
