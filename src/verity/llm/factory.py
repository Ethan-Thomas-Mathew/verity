import httpx
from pydantic import SecretStr

from verity.config import Settings
from verity.llm.base import LLMClient
from verity.llm.providers import AnthropicClient, GeminiClient, OllamaClient, OpenAIClient
from verity.llm.replay import RecordingClient, ReplayClient


def _secret(value: SecretStr | None) -> str:
    if value is None:  # Settings validation already rejects this; kept for the type checker.
        raise ValueError("missing API key")
    return value.get_secret_value()


def build_llm(settings: Settings, http: httpx.Client | None = None) -> LLMClient:
    http = http or httpx.Client(timeout=settings.llm_timeout_seconds)
    model = settings.model_name
    client: LLMClient
    match settings.llm_provider:
        case "ollama":
            client = OllamaClient(http, settings.ollama_url, model)
        case "openai":
            client = OpenAIClient(
                http, settings.openai_url, model, _secret(settings.openai_api_key)
            )
        case "gemini":
            client = GeminiClient(http, model, _secret(settings.gemini_api_key))
        case "anthropic":
            client = AnthropicClient(http, model, _secret(settings.anthropic_api_key))
        case "replay":
            return ReplayClient(settings.replay_dir)
    if settings.record_dir is not None:
        return RecordingClient(client, settings.record_dir)
    return client
