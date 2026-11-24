"""Index requirement documents in pgvector and retrieve the parts a story needs."""

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from verity.db.models import Chunk
from verity.rag.embeddings import Embedder

REQUIREMENT_ID = re.compile(r"\b(REQ-[A-Z]+-\d+)\b")


@dataclass(frozen=True)
class Section:
    source: str
    heading: str
    requirement_id: str | None
    content: str


@dataclass(frozen=True)
class Retrieved:
    section: Section
    # "exact": named by the story. "semantic": found by vector search.
    # "reference": always included (the API guide).
    match: str
    distance: float | None


def split_markdown(source: str, text: str) -> list[Section]:
    """Split a document at each "## " heading. Each heading becomes one chunk.

    Requirement sections are short and self-contained, so one section per
    chunk keeps a requirement's rules together instead of cutting them at an
    arbitrary character count.
    """
    sections: list[Section] = []
    heading, lines = "", list[str]()
    for line in [*text.splitlines(), "## "]:
        if line.startswith("## "):
            body = "\n".join(lines).strip()
            if body:
                found = REQUIREMENT_ID.search(heading)
                sections.append(
                    Section(source, heading or source, found.group(1) if found else None, body)
                )
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    return sections


def index_directory(session: Session, embedder: Embedder, directory: Path) -> int:
    """Re-index every Markdown file in `directory`. Returns the number of chunks stored."""
    sections = [
        section
        for path in sorted(directory.glob("*.md"))
        for section in split_markdown(path.name, path.read_text())
    ]
    session.execute(delete(Chunk).where(Chunk.embedder == embedder.name))
    if not sections:
        return 0
    vectors = embedder.embed([f"{s.heading}\n{s.content}" for s in sections])
    session.add_all(
        Chunk(
            source=s.source,
            heading=s.heading,
            requirement_id=s.requirement_id,
            content=s.content,
            embedder=embedder.name,
            embedding=vector,
        )
        for s, vector in zip(sections, vectors, strict=True)
    )
    session.flush()
    return len(sections)


def _section(chunk: Chunk) -> Section:
    return Section(chunk.source, chunk.heading, chunk.requirement_id, chunk.content)


def retrieve(
    session: Session,
    embedder: Embedder,
    query: str,
    requirement_ids: list[str],
    k: int = 3,
    reference_sources: tuple[str, ...] = ("api.md",),
) -> list[Retrieved]:
    """Hybrid retrieval for one story.

    1. "exact": every requirement the story names, fetched by id.
    2. "reference": every section of the reference documents (the API guide),
       because no test can be written without knowing the endpoints.
    3. "semantic": the k sections closest to the story by vector search, which
       finds related requirements the story does not name (a late-fee story
       also needs the loan period, for example).
    """
    exact = session.scalars(
        select(Chunk)
        .where(Chunk.embedder == embedder.name, Chunk.requirement_id.in_(requirement_ids))
        .order_by(Chunk.id)
    ).all()
    reference = session.scalars(
        select(Chunk)
        .where(Chunk.embedder == embedder.name, Chunk.source.in_(reference_sources))
        .order_by(Chunk.id)
    ).all()
    taken = [c.id for c in [*exact, *reference]]
    query_vector = embedder.embed([query])[0]
    distance = Chunk.embedding.cosine_distance(query_vector)
    nearest = session.execute(
        select(Chunk, distance)
        .where(Chunk.embedder == embedder.name, Chunk.id.not_in(taken))
        .order_by(distance)
        .limit(k)
    ).all()
    return (
        [Retrieved(_section(c), "exact", None) for c in exact]
        + [Retrieved(_section(c), "semantic", float(d)) for c, d in nearest]
        + [Retrieved(_section(c), "reference", None) for c in reference]
    )
