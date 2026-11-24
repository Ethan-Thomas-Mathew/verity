"""Runs one story end to end: build the agents' tools, run the graph, save everything."""

import contextlib
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session, sessionmaker

from verity.agents.graph import Bug, Executed, State, Tools, build_graph
from verity.config import Settings
from verity.db.database import transaction
from verity.db.models import BugReport, Run, RunEvent, TestCase
from verity.llm.base import LLMClient
from verity.rag.embeddings import Embedder, HashingEmbedder, OllamaEmbedder
from verity.rag.store import Retrieved, retrieve
from verity.runners.api_runner import ApiRunner, Result
from verity.runners.specs import UiTest
from verity.runners.ui_runner import UiRunner
from verity.stories import Story


def build_embedder(settings: Settings, http: httpx.Client | None = None) -> Embedder:
    if settings.embedding_provider == "hashing":
        return HashingEmbedder()
    return OllamaEmbedder(
        http or httpx.Client(timeout=settings.llm_timeout_seconds),
        settings.ollama_url,
        settings.embedding_model,
    )


def create_run(
    factory: sessionmaker[Session], story: Story, target_url: str, model: str
) -> uuid.UUID:
    with transaction(factory) as session:
        run = Run(story_key=story.key, target_url=target_url, model=model, status="queued")
        session.add(run)
        session.flush()
        return run.id


def execute_run(
    run_id: uuid.UUID,
    story: Story,
    settings: Settings,
    factory: sessionmaker[Session],
    llm: LLMClient,
    embedder: Embedder,
    use_browser: bool = True,
) -> None:
    """Run the agent graph for one story and store the results under `run_id`.

    Any exception marks the run as failed with its message, so a run never stays
    "running" forever and the caller can see why it stopped.
    """
    with transaction(factory) as session:
        run = session.get_one(Run, run_id)
        run.status = "running"

    try:
        state = _invoke(story, settings, factory, llm, embedder, use_browser)
    except Exception as exc:
        with transaction(factory) as session:
            run = session.get_one(Run, run_id)
            run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
        raise

    with transaction(factory) as session:
        _save(session, run_id, state)
        run = session.get_one(Run, run_id)
        run.status, run.finished_at = "finished", datetime.now(UTC)


def _invoke(
    story: Story,
    settings: Settings,
    factory: sessionmaker[Session],
    llm: LLMClient,
    embedder: Embedder,
    use_browser: bool,
) -> State:
    def find_context(s: Story) -> list[Retrieved]:
        with factory() as session:
            query = f"{s.summary}. {s.description}"
            return retrieve(session, embedder, query, list(s.requirements))

    with contextlib.ExitStack() as stack:
        http = stack.enter_context(httpx.Client(timeout=settings.request_timeout_seconds))
        api = ApiRunner(http, settings.target_url)
        ui: UiRunner | None = None

        def run_ui(tests: list[UiTest]) -> list[Result]:
            nonlocal ui
            if ui is None:  # start the browser only when a UI test actually runs
                ui = stack.enter_context(
                    UiRunner(api, settings.target_url, settings.browser_executable)
                )
            return [ui.run(t) for t in tests]

        tools = Tools(
            llm=llm, retrieve=find_context, run_api=api.run, run_ui=run_ui if use_browser else None
        )
        result: State = build_graph(tools).invoke({"story": story, "events": []})  # type: ignore[assignment]
        return result


def _save(session: Session, run_id: uuid.UUID, state: State) -> None:
    for agent, message in state.get("events", []):
        session.add(RunEvent(run_id=run_id, agent=agent, message=message))
    rows: dict[int, TestCase] = {}
    for position, executed in enumerate(state.get("executed", [])):
        row = _test_case(run_id, position, executed)
        session.add(row)
        rows[id(executed)] = row
    session.flush()
    for bug in state.get("bugs", []):
        session.add(_bug_report(run_id, rows[id(bug.executed)], bug))


def _test_case(run_id: uuid.UUID, position: int, executed: Executed) -> TestCase:
    spec = executed.test.model_dump(mode="json")
    if executed.repaired:
        spec["repaired"] = True
    return TestCase(
        run_id=run_id,
        position=position,
        requirement_id=executed.test.requirement_id,
        kind=executed.kind,
        title=executed.test.title,
        spec=spec,
        outcome=executed.result.outcome,
        detail="\n".join([executed.result.detail, *executed.result.log]),
        review="pending",
    )


def _bug_report(run_id: uuid.UUID, row: TestCase, bug: Bug) -> BugReport:
    return BugReport(
        run_id=run_id,
        test_case_id=row.id,
        requirement_id=row.requirement_id,
        summary=bug.draft.summary,
        severity=bug.draft.severity,
        steps_to_reproduce=bug.steps_to_reproduce,
        expected=bug.draft.expected,
        actual=bug.draft.actual,
    )
