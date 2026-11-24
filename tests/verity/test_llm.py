import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from verity.config import Settings
from verity.llm.base import LLMError, Message
from verity.llm.factory import build_llm
from verity.llm.providers import AnthropicClient, GeminiClient, OllamaClient, OpenAIClient
from verity.llm.replay import RecordingClient, ReplayClient
from verity.llm.structured import StructuredOutputError, ask

MESSAGES = [
    Message(role="system", content="Be brief."),
    Message(role="user", content="Say hi."),
]
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}}


class Reply(BaseModel):
    text: str


def mock_http(reply: dict[str, Any], seen: list[httpx.Request], status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=reply)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ollama_sends_schema_as_format() -> None:
    seen: list[httpx.Request] = []
    http = mock_http({"message": {"content": '{"text": "hi"}'}}, seen)
    assert OllamaClient(http, "http://ollama:11434/", "qwen").complete_json(MESSAGES, SCHEMA) == (
        '{"text": "hi"}'
    )
    body = json.loads(seen[0].content)
    assert seen[0].url == "http://ollama:11434/api/chat"
    assert body["format"] == SCHEMA and body["stream"] is False


def test_openai_uses_json_schema_response_format() -> None:
    seen: list[httpx.Request] = []
    http = mock_http({"choices": [{"message": {"content": '{"text": "hi"}'}}]}, seen)
    OpenAIClient(http, "https://api.openai.com/v1", "m", "sk-test").complete_json(MESSAGES, SCHEMA)
    body = json.loads(seen[0].content)
    assert seen[0].headers["authorization"] == "Bearer sk-test"
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA


def test_gemini_moves_system_prompt_and_renames_roles() -> None:
    seen: list[httpx.Request] = []
    reply = {"candidates": [{"content": {"parts": [{"text": '{"text": "hi"}'}]}}]}
    http = mock_http(reply, seen)
    history = [*MESSAGES, Message(role="assistant", content="x"), Message(role="user", content="y")]
    GeminiClient(http, "gemini-test", "g-key").complete_json(history, SCHEMA)
    body = json.loads(seen[0].content)
    assert seen[0].headers["x-goog-api-key"] == "g-key"
    assert body["systemInstruction"]["parts"][0]["text"] == "Be brief."
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["generationConfig"]["responseJsonSchema"] == SCHEMA


def test_anthropic_forces_a_tool_call_and_returns_its_input() -> None:
    seen: list[httpx.Request] = []
    reply = {"content": [{"type": "tool_use", "name": "submit", "input": {"text": "hi"}}]}
    http = mock_http(reply, seen)
    out = AnthropicClient(http, "claude-test", "a-key").complete_json(MESSAGES, SCHEMA)
    body = json.loads(seen[0].content)
    assert json.loads(out) == {"text": "hi"}
    assert body["tool_choice"] == {"type": "tool", "name": "submit"}
    assert body["system"] == "Be brief." and body["messages"][0]["role"] == "user"


def test_http_errors_and_bad_shapes_become_llm_errors() -> None:
    with pytest.raises(LLMError, match="401"):
        OllamaClient(mock_http({"error": "no"}, [], 401), "http://o", "m").complete_json(
            MESSAGES, SCHEMA
        )
    with pytest.raises(LLMError, match="unexpected response shape"):
        OllamaClient(mock_http({"nope": 1}, []), "http://o", "m").complete_json(MESSAGES, SCHEMA)
    with pytest.raises(LLMError, match="no tool_use"):
        AnthropicClient(mock_http({"content": []}, []), "m", "k").complete_json(MESSAGES, SCHEMA)


class Scripted:
    def __init__(self, replies: list[str]) -> None:
        self.replies, self.calls = list(replies), list[list[Message]]()

    @property
    def name(self) -> str:
        return "scripted"

    def complete_json(self, messages: list[Message], schema: dict[str, Any]) -> str:
        self.calls.append(messages)
        return self.replies.pop(0)


def test_ask_retries_once_with_the_validation_error() -> None:
    llm = Scripted(['{"wrong": 1}', '{"text": "fixed"}'])
    assert ask(llm, MESSAGES, Reply).text == "fixed"
    retry = llm.calls[1]
    assert retry[-2].role == "assistant" and "text" in retry[-1].content


def test_ask_gives_up_after_the_retry() -> None:
    with pytest.raises(StructuredOutputError, match="Reply after 2 attempts"):
        ask(Scripted(["{}", "{}"]), MESSAGES, Reply)


def test_record_then_replay(tmp_path: Path) -> None:
    recorder = RecordingClient(Scripted(['{"text": "hi"}']), tmp_path)
    assert recorder.complete_json(MESSAGES, SCHEMA) == '{"text": "hi"}'
    assert ReplayClient(tmp_path).complete_json(MESSAGES, SCHEMA) == '{"text": "hi"}'
    with pytest.raises(LLMError, match="no recorded reply"):
        ReplayClient(tmp_path).complete_json([*MESSAGES, MESSAGES[1]], SCHEMA)


def test_hosted_provider_needs_its_key() -> None:
    with pytest.raises(ValidationError, match="VERITY_GEMINI_API_KEY"):
        Settings(llm_provider="gemini")
    settings = Settings(llm_provider="gemini", gemini_api_key=SecretStr("k"))
    assert settings.model_name == "gemini-3.5-flash"
    assert build_llm(settings).name == "gemini:gemini-3.5-flash"


def test_factory_wraps_with_recorder_and_builds_replay(tmp_path: Path) -> None:
    assert isinstance(build_llm(Settings(record_dir=tmp_path)), RecordingClient)
    assert build_llm(Settings(llm_provider="replay", replay_dir=tmp_path)).name == "replay"
    openai = build_llm(
        Settings(llm_provider="openai", openai_api_key=SecretStr("k"), llm_model="x")
    )
    assert openai.name == "openai:x"
    claude = build_llm(Settings(llm_provider="anthropic", anthropic_api_key=SecretStr("k")))
    assert claude.name.startswith("anthropic:")


def test_blank_keys_count_as_missing() -> None:
    with pytest.raises(ValidationError, match="VERITY_OPENAI_API_KEY"):
        Settings(llm_provider="openai", openai_api_key="")
