"""Typed settings, read from VERITY_* environment variables or a .env file."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["ollama", "openai", "gemini", "anthropic", "replay"]
EmbeddingProvider = Literal["ollama", "hashing"]

DEFAULT_MODELS: dict[Provider, str] = {
    "ollama": "qwen2.5:7b",
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-3.5-flash",
    "anthropic": "claude-haiku-5-5",
    "replay": "replay",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VERITY_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://verity:verity@127.0.0.1:5433/verity"

    # Which language model the agents use. Ollama runs locally and needs no key.
    llm_provider: Provider = "ollama"
    llm_model: str | None = None
    llm_timeout_seconds: float = 120.0
    ollama_url: str = "http://127.0.0.1:11434"
    openai_url: str = "https://api.openai.com/v1"
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    # Model replies are saved here when record_dir is set, and read from
    # replay_dir when llm_provider is "replay". This makes runs repeatable.
    record_dir: Path | None = None
    replay_dir: Path = Path("eval/recordings")

    embedding_provider: EmbeddingProvider = "ollama"
    embedding_model: str = "nomic-embed-text"

    # The application under test.
    target_url: str = "http://127.0.0.1:8001"
    request_timeout_seconds: float = 10.0
    # Leave unset to use the browser installed by `playwright install chromium`.
    browser_executable: str | None = None
    run_ui_tests: bool = True

    requirements_dir: Path = Path("requirements/shelf")

    @field_validator("openai_api_key", "gemini_api_key", "anthropic_api_key", mode="before")
    @classmethod
    def _blank_key_is_no_key(cls, value: object) -> object:
        # Docker Compose passes unset keys as empty strings.
        return None if value == "" else value

    @model_validator(mode="after")
    def _key_for_hosted_provider(self) -> "Settings":
        keys = {
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
            "anthropic": self.anthropic_api_key,
        }
        if self.llm_provider in keys and keys[self.llm_provider] is None:
            raise ValueError(
                f"VERITY_LLM_PROVIDER={self.llm_provider} needs "
                f"VERITY_{self.llm_provider.upper()}_API_KEY"
            )
        return self

    @property
    def model_name(self) -> str:
        return self.llm_model or DEFAULT_MODELS[self.llm_provider]
