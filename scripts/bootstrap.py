"""One-command setup: `uv run python scripts/bootstrap.py`.

Everything runs inside Docker, so the same steps work on Windows, macOS and
Linux, including Windows machines where Smart App Control blocks Python's
compiled extensions on the host. Ollama runs on the host; the containers reach
it at host.docker.internal.
"""

import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def step(title: str, command: list[str]) -> None:
    print(f"\n== {title}\n$ {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        sys.exit(f"failed: {title} (exit code {result.returncode})")


def ollama_running() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3):
            return True
    except (urllib.error.URLError, TimeoutError):
        return False


def main() -> None:
    if shutil.which("docker") is None:
        sys.exit("Docker is not installed or not on PATH. Install Docker Desktop first.")
    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copy(ROOT / ".env.example", env_file)
        print("created .env from .env.example")
    step(
        "Build and start Postgres and Shelf",
        ["docker", "compose", "up", "-d", "--build", "--wait", "postgres", "shelf"],
    )
    step("Migrate the database", ["docker", "compose", "run", "--rm", "migrate"])
    if not ollama_running():
        print(
            "\nOllama is not running, so requirements were not indexed yet.\n"
            "Start the Ollama app, then run:\n"
            "  docker compose --profile full run --rm api verity index"
        )
        return
    step(
        "Index requirements",
        ["docker", "compose", "--profile", "full", "run", "--rm", "api", "verity", "index"],
    )
    print("\nReady. Try: docker compose --profile full run --rm api verity run SHELF-3")


if __name__ == "__main__":
    main()
