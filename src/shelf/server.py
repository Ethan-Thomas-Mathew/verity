"""Start Shelf in a background thread. Used by the evaluation and by tests."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import uvicorn

from shelf.app import ShelfSettings, create_app


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@contextmanager
def serve_in_thread(database_url: str, bugs: str) -> Iterator[str]:
    """Run Shelf in test mode on a free local port; yields its base URL."""
    app = create_app(ShelfSettings(database_url=database_url, bugs=bugs, test_mode=True))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while True:
        try:
            if httpx.get(f"{url}/health").status_code == 200:
                break
        except httpx.HTTPError:
            if time.monotonic() > deadline:
                raise RuntimeError("Shelf did not start within 10 seconds") from None
            time.sleep(0.05)
    try:
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        app.state.engine.dispose()
