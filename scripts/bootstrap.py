"""One-command setup: `uv run python scripts/bootstrap.py`.

Starts Postgres and Shelf in Docker, migrates the database, installs Chromium
for the UI tests, and indexes the requirements if Ollama is running.
Works the same on Windows, macOS and Linux.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def step(title: str, command: list[str]) -> None:
    print(f"\n== {title}\n$ {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        sys.exit(f"failed: {title} (exit code {result.returncode})")


def main() -> None:
    if shutil.which("docker") is None:
        sys.exit("Docker is not installed or not on PATH. Install Docker Desktop first.")
    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copy(ROOT / ".env.example", env_file)
        print("created .env from .env.example")
    step(
        "Start Postgres and Shelf", ["docker", "compose", "up", "-d", "--wait", "postgres", "shelf"]
    )
    step("Migrate the database", [sys.executable, "-m", "alembic", "upgrade", "head"])
    step(
        "Install Chromium for UI tests", [sys.executable, "-m", "playwright", "install", "chromium"]
    )
    try:
        httpx.get("http://127.0.0.1:11434/api/tags", timeout=3).raise_for_status()
    except httpx.HTTPError:
        print(
            "\nOllama is not running, so requirements were not indexed yet.\n"
            "Install it from https://ollama.com, then run:\n"
            "  ollama pull qwen2.5:7b\n  ollama pull nomic-embed-text\n  uv run verity index"
        )
        return
    step("Index requirements", [sys.executable, "-m", "verity.cli", "index"])
    print("\nReady. Try: uv run verity run SHELF-3")


if __name__ == "__main__":
    main()
