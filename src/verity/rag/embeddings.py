"""Text embeddings: a local Ollama model, or a deterministic hashing embedder for tests."""

import hashlib
import math
import re
from typing import Protocol

import httpx

from verity.llm.base import LLMError


class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    def __init__(self, http: httpx.Client, base_url: str, model: str) -> None:
        self._http, self._url, self._model = http, base_url.rstrip("/"), model

    @property
    def name(self) -> str:
        return f"ollama:{self._model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = self._http.post(
                f"{self._url}/api/embed", json={"model": self._model, "input": texts}
            )
            response.raise_for_status()
            vectors: list[list[float]] = response.json()["embeddings"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"embedding with {self.name} failed: {exc}") from exc
        if len(vectors) != len(texts):
            raise LLMError(f"{self.name} returned {len(vectors)} vectors for {len(texts)} texts")
        return vectors


class HashingEmbedder:
    """Bag of words hashed into a fixed-size vector.

    It only matches shared words, not meaning, so retrieval is weaker than a
    real embedding model. It needs no model download, which makes tests and CI
    fast and repeatable.
    """

    def __init__(self, dimensions: int = 512) -> None:
        self._dims = dimensions

    @property
    def name(self) -> str:
        return f"hashing:{self._dims}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self._dims
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.sha1(word.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self._dims
            vector[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]
