"""The one interface every language model provider implements."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel


class LLMError(Exception):
    """The provider failed or returned something unusable."""


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMClient(Protocol):
    @property
    def name(self) -> str:
        """Provider and model, for example "ollama:qwen2.5:7b". Stored with each run."""
        ...

    def complete_json(self, messages: list[Message], schema: dict[str, Any]) -> str:
        """Return the model's reply as JSON text that should match `schema`.

        Providers ask the model for schema-shaped JSON where they support it,
        but the caller must still validate: no provider guarantees it.
        """
        ...
