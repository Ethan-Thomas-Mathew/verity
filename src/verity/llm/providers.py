"""HTTP clients for each provider, written against their REST APIs with httpx.

No vendor SDKs: each provider is about thirty lines, and seeing the raw request
makes it clear what is sent to a hosted model.
"""

import json
from typing import Any

import httpx

from verity.llm.base import LLMError, Message


def _post(http: httpx.Client, url: str, body: dict[str, Any], headers: dict[str, str]) -> Any:
    try:
        response = http.post(url, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise LLMError(f"timed out calling {url}") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"could not reach {url}: {exc}") from exc
    if response.status_code >= 400:
        # Error bodies can be long; the first 300 characters carry the reason.
        raise LLMError(f"{url} returned {response.status_code}: {response.text[:300]}")
    try:
        return response.json()
    except ValueError as exc:
        raise LLMError(f"{url} returned a body that is not JSON") from exc


def _dig(data: Any, *path: str | int) -> Any:
    """Read a nested field, turning a missing key into an LLMError instead of a KeyError."""
    current = data
    for key in path:
        try:
            current = current[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected response shape, missing {path}") from exc
    return current


class OllamaClient:
    def __init__(self, http: httpx.Client, base_url: str, model: str) -> None:
        self._http, self._url, self._model = http, base_url.rstrip("/"), model

    @property
    def name(self) -> str:
        return f"ollama:{self._model}"

    def complete_json(self, messages: list[Message], schema: dict[str, Any]) -> str:
        body = {
            "model": self._model,
            "messages": [m.model_dump() for m in messages],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0},
        }
        data = _post(self._http, f"{self._url}/api/chat", body, {})
        return str(_dig(data, "message", "content"))


class OpenAIClient:
    def __init__(self, http: httpx.Client, base_url: str, model: str, api_key: str) -> None:
        self._http, self._url, self._model = http, base_url.rstrip("/"), model
        self._headers = {"Authorization": f"Bearer {api_key}"}

    @property
    def name(self) -> str:
        return f"openai:{self._model}"

    def complete_json(self, messages: list[Message], schema: dict[str, Any]) -> str:
        body = {
            "model": self._model,
            "messages": [m.model_dump() for m in messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": schema},
            },
            "temperature": 0,
        }
        data = _post(self._http, f"{self._url}/chat/completions", body, self._headers)
        return str(_dig(data, "choices", 0, "message", "content"))


class GeminiClient:
    URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, http: httpx.Client, model: str, api_key: str) -> None:
        self._http, self._model = http, model
        self._headers = {"x-goog-api-key": api_key}

    @property
    def name(self) -> str:
        return f"gemini:{self._model}"

    def complete_json(self, messages: list[Message], schema: dict[str, Any]) -> str:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in messages
            if m.role != "system"
        ]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
                "temperature": 0,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{self.URL}/{self._model}:generateContent"
        data = _post(self._http, url, body, self._headers)
        return str(_dig(data, "candidates", 0, "content", "parts", 0, "text"))


class AnthropicClient:
    URL = "https://api.anthropic.com/v1/messages"
    TOOL = "submit"

    def __init__(self, http: httpx.Client, model: str, api_key: str) -> None:
        self._http, self._model = http, model
        self._headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}

    @property
    def name(self) -> str:
        return f"anthropic:{self._model}"

    def complete_json(self, messages: list[Message], schema: dict[str, Any]) -> str:
        # Claude returns schema-shaped JSON most reliably as the input of a
        # forced tool call, so the schema is offered as the only tool.
        body = {
            "model": self._model,
            "max_tokens": 4096,
            "temperature": 0,
            "system": "\n\n".join(m.content for m in messages if m.role == "system"),
            "messages": [m.model_dump() for m in messages if m.role != "system"],
            "tools": [
                {"name": self.TOOL, "description": "Submit the answer.", "input_schema": schema}
            ],
            "tool_choice": {"type": "tool", "name": self.TOOL},
        }
        data = _post(self._http, self.URL, body, self._headers)
        for block in _dig(data, "content"):
            if block.get("type") == "tool_use":
                return json.dumps(block.get("input"))
        raise LLMError("anthropic reply contained no tool_use block")
