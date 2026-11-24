"""Verity's REST API. Bind it to 127.0.0.1: it has no login and is meant for local use."""

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session, selectinload, sessionmaker

from verity import exports
from verity.config import Settings
from verity.db.database import make_engine, transaction
from verity.db.models import BugReport, Run, TestCase
from verity.llm.base import LLMClient
from verity.llm.factory import build_llm
from verity.rag.embeddings import Embedder
from verity.rag.store import index_directory
from verity.runners.specs import ApiTest, UiTest
from verity.runs import build_embedder, create_run, execute_run
from verity.stories import Story, load_stories

log = logging.getLogger("verity.api")


class RunRequest(BaseModel):
    story_key: str


class RunCreated(BaseModel):
    run_id: uuid.UUID


class ReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]


class TestCaseOut(BaseModel):
    __test__ = False

    id: int
    requirement_id: str
    kind: str
    title: str
    outcome: str | None
    detail: str | None
    review: str
    spec: dict[str, Any]


class BugOut(BaseModel):
    id: int
    test_case_id: int
    requirement_id: str
    summary: str
    severity: str
    steps_to_reproduce: list[str]
    expected: str
    actual: str


class EventOut(BaseModel):
    agent: str
    message: str
    created_at: datetime


class RunOut(BaseModel):
    id: uuid.UUID
    story_key: str
    model: str
    status: str
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class RunDetail(RunOut):
    test_cases: list[TestCaseOut]
    bugs: list[BugOut]
    events: list[EventOut]


class RequirementStatus(BaseModel):
    requirement_id: str
    tests: int
    passed: int
    failed: int
    errors: int
    open_bugs: int


def spec_of(case: TestCase) -> ApiTest | UiTest:
    model = ApiTest if case.kind == "api" else UiTest
    return model.model_validate(case.spec)


def create_app(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    embedder: Embedder | None = None,
) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    llm = llm or build_llm(settings)
    embedder = embedder or build_embedder(settings)

    app = FastAPI(
        title="Verity",
        description="Multi-agent QA assistant: user stories in, tests and bug reports out.",
    )
    app.state.engine = engine

    def session() -> Any:
        with factory() as s:
            yield s

    Db = Annotated[Session, Depends(session)]

    def stories() -> dict[str, Story]:
        return load_stories(settings.requirements_dir)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready(db: Db) -> Response:
        try:
            db.execute(text("SELECT 1"))
        except Exception as exc:
            log.warning("database not ready: %s", exc)
            return JSONResponse(status_code=503, content={"status": "database unavailable"})
        return JSONResponse({"status": "ready"})

    @app.get("/stories")
    def list_stories() -> list[Story]:
        return list(stories().values())

    @app.post("/requirements/index")
    def index_requirements() -> dict[str, int]:
        with transaction(factory) as db:
            count = index_directory(db, embedder, settings.requirements_dir)
        return {"chunks": count}

    @app.post("/runs", status_code=202)
    def start_run(body: RunRequest, background: BackgroundTasks) -> RunCreated:
        story = stories().get(body.story_key)
        if story is None:
            raise HTTPException(404, f"unknown story {body.story_key}")
        run_id = create_run(factory, story, settings.target_url, llm.name)

        def work() -> None:
            try:
                execute_run(run_id, story, settings, factory, llm, embedder)
            except Exception:
                # execute_run already stored the error on the run; log the traceback too.
                log.exception("run %s failed", run_id)

        background.add_task(work)
        return RunCreated(run_id=run_id)

    @app.get("/runs")
    def list_runs(db: Db) -> list[RunOut]:
        runs = db.scalars(select(Run).order_by(Run.created_at.desc()).limit(100))
        return [RunOut.model_validate(r, from_attributes=True) for r in runs]

    @app.get("/runs/{run_id}")
    def get_run(run_id: uuid.UUID, db: Db) -> RunDetail:
        run = db.scalar(
            select(Run)
            .where(Run.id == run_id)
            .options(selectinload(Run.test_cases), selectinload(Run.bugs), selectinload(Run.events))
        )
        if run is None:
            raise HTTPException(404, "run not found")
        return RunDetail.model_validate(run, from_attributes=True)

    @app.post("/test-cases/{case_id}/review")
    def review(case_id: int, body: ReviewRequest) -> TestCaseOut:
        with transaction(factory) as db:
            case_row = db.get(TestCase, case_id)
            if case_row is None:
                raise HTTPException(404, "test case not found")
            if case_row.outcome == "error" and body.decision == "approved":
                raise HTTPException(409, "a test that could not run cannot join the suite")
            case_row.review = body.decision
            return TestCaseOut.model_validate(case_row, from_attributes=True)

    @app.get("/reports/requirements")
    def requirement_report(db: Db) -> list[RequirementStatus]:
        """Test results and bug counts per requirement, across all runs.

        One query joins test cases to their bug reports, so a requirement with
        tests but no bugs still appears with open_bugs = 0.
        """
        rows = db.execute(
            select(
                TestCase.requirement_id,
                func.count(func.distinct(TestCase.id)),
                func.count(func.distinct(case((TestCase.outcome == "passed", TestCase.id)))),
                func.count(func.distinct(case((TestCase.outcome == "failed", TestCase.id)))),
                func.count(func.distinct(case((TestCase.outcome == "error", TestCase.id)))),
                func.count(func.distinct(BugReport.id)),
            )
            .outerjoin(BugReport, BugReport.test_case_id == TestCase.id)
            .group_by(TestCase.requirement_id)
            .order_by(TestCase.requirement_id)
        ).all()
        return [
            RequirementStatus(
                requirement_id=r[0],
                tests=r[1],
                passed=r[2],
                failed=r[3],
                errors=r[4],
                open_bugs=r[5],
            )
            for r in rows
        ]

    def approved(db: Session) -> list[TestCase]:
        return list(
            db.scalars(select(TestCase).where(TestCase.review == "approved").order_by(TestCase.id))
        )

    @app.get("/exports/postman")
    def export_postman(db: Db) -> dict[str, Any]:
        tests = [s for s in map(spec_of, approved(db)) if isinstance(s, ApiTest)]
        return exports.postman_collection(tests, settings.target_url)

    @app.get("/exports/pytest", response_class=PlainTextResponse)
    def export_pytest(db: Db) -> str:
        specs = [spec_of(c) for c in approved(db)]
        return exports.pytest_module(
            [s for s in specs if isinstance(s, ApiTest)],
            [s for s in specs if isinstance(s, UiTest)],
        )

    @app.get("/exports/test-cases.csv", response_class=PlainTextResponse)
    def export_cases(db: Db) -> Response:
        cases = db.scalars(select(TestCase).order_by(TestCase.id))
        body = exports.test_cases_csv((c.id, spec_of(c), c.outcome, c.review) for c in cases)
        return Response(body, media_type="text/csv")

    @app.get("/exports/bugs.csv", response_class=PlainTextResponse)
    def export_bugs(db: Db) -> Response:
        bugs = db.scalars(select(BugReport).order_by(BugReport.id))
        rows = [BugOut.model_validate(b, from_attributes=True).model_dump() for b in bugs]
        return Response(exports.jira_csv(rows), media_type="text/csv")

    return app
