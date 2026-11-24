import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from verity.cli import main
from verity.llm.base import LLMError
from verity.rag.embeddings import OllamaEmbedder


def test_stories_lists_every_story(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["stories"]) == 0
    assert "SHELF-3  Borrow a book" in capsys.readouterr().out


@pytest.mark.db
def test_index_and_unknown_story(
    db: sessionmaker[Session],
    verity_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("VERITY_DATABASE_URL", verity_db_url)
    monkeypatch.setenv("VERITY_EMBEDDING_PROVIDER", "hashing")
    assert main(["index"]) == 0
    assert "with hashing:512" in capsys.readouterr().out
    assert main(["run", "NOPE-9"]) == 2
    assert "unknown story NOPE-9" in capsys.readouterr().err


def test_ollama_embedder_request_and_errors() -> None:
    seen: list[httpx.Request] = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    embedder = OllamaEmbedder(httpx.Client(transport=httpx.MockTransport(ok)), "http://o/", "nomic")
    assert embedder.embed(["a"]) == [[0.1, 0.2]]
    assert seen[0].url == "http://o/api/embed" and embedder.name == "ollama:nomic"
    with pytest.raises(LLMError, match="1 vectors for 2 texts"):
        embedder.embed(["a", "b"])

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="model not pulled")

    broken = OllamaEmbedder(httpx.Client(transport=httpx.MockTransport(down)), "http://o", "x")
    with pytest.raises(LLMError, match="embedding with ollama:x failed"):
        broken.embed(["a"])
