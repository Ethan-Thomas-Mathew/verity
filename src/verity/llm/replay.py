"""Record real model replies and play them back.

A recorded run can be replayed in CI with no model installed, so a test that
passed once on a real model keeps checking the code around it on every push.
Each reply is stored under a hash of the exact request; a changed prompt is a
cache miss, never a silent reuse of an old answer.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from verity.llm.base import LLMClient, LLMError, Message


def request_key(messages: list[Message], schema: dict[str, Any]) -> str:
    payload = json.dumps(
        {"messages": [m.model_dump() for m in messages], "schema": schema}, sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


class RecordingClient:
    def __init__(self, inner: LLMClient, directory: Path) -> None:
        self._inner, self._dir = inner, directory
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return self._inner.name

    def complete_json(self, messages: list[Message], schema: dict[str, Any]) -> str:
        reply = self._inner.complete_json(messages, schema)
        path = self._dir / f"{request_key(messages, schema)}.json"
        path.write_text(json.dumps({"model": self._inner.name, "reply": reply}, indent=2))
        return reply


class ReplayClient:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    @property
    def name(self) -> str:
        return "replay"

    def complete_json(self, messages: list[Message], schema: dict[str, Any]) -> str:
        path = self._dir / f"{request_key(messages, schema)}.json"
        if not path.exists():
            raise LLMError(f"no recorded reply for this request ({path.name})")
        reply: str = json.loads(path.read_text())["reply"]
        return reply
