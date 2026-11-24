"""Run Shelf: `uv run shelf` (or `python -m shelf`). Settings come from SHELF_* variables."""

import os

import uvicorn

from shelf.app import create_app


def main() -> None:
    host = os.environ.get("SHELF_HOST", "127.0.0.1")
    port = int(os.environ.get("SHELF_PORT", "8001"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
