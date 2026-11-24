import csv
import io
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from tests.support import serve_shelf
from tests.verity.fakes import AVAILABILITY, DUE_FIXED, LIMIT, UI, FakeModel
from verity.api.app import create_app
from verity.config import Settings
from verity.evaluation import evaluate, save
from verity.exports import postman_collection, pytest_module
from verity.rag.embeddings import HashingEmbedder
from verity.runners.specs import ApiTest, UiTest

pytestmark = pytest.mark.db
ROOT = Path(__file__).parents[2]
PLAN = {"api_tests": [LIMIT, AVAILABILITY, DUE_FIXED], "ui_tests": [UI]}


@pytest.fixture(scope="module")
def buggy_url(shelf_db_url: str) -> Iterator[str]:
    with serve_shelf(shelf_db_url, "all") as url:
        yield url


@pytest.fixture(scope="module")
def fixed_url(shelf_db_url: str) -> Iterator[str]:
    with serve_shelf(shelf_db_url, "none") as url:
        yield url


@pytest.fixture
def api(
    db: sessionmaker[Session], verity_db_url: str, buggy_url: str
) -> Iterator[tuple[TestClient, FakeModel]]:
    settings = Settings(
        database_url=verity_db_url,
        target_url=buggy_url,
        embedding_provider="hashing",
        run_ui_tests=False,
    )
    model = FakeModel([PLAN, PLAN])
    app = create_app(settings, llm=model, embedder=HashingEmbedder())
    with TestClient(app) as client:
        yield client, model
    app.state.engine.dispose()


def test_story_to_bug_reports_over_http(api: tuple[TestClient, FakeModel]) -> None:
    client, _ = api
    assert client.get("/ready").json() == {"status": "ready"}
    assert [s["key"] for s in client.get("/stories").json()][:2] == ["SHELF-1", "SHELF-2"]
    assert client.post("/requirements/index").json()["chunks"] > 10
    assert client.post("/runs", json={"story_key": "NOPE-1"}).status_code == 404

    created = client.post("/runs", json={"story_key": "SHELF-3"})
    assert created.status_code == 202
    run = client.get(f"/runs/{created.json()['run_id']}").json()
    # TestClient finishes background tasks before returning, so the run is done.
    # UI tests are switched off here, so only the API bugs are reported.
    assert run["status"] == "finished", run["error"]
    assert {b["requirement_id"] for b in run["bugs"]} == {"REQ-LOAN-1", "REQ-LOAN-3"}
    assert client.get("/runs").json()[0]["id"] == run["id"]

    report = {r["requirement_id"]: r for r in client.get("/reports/requirements").json()}
    assert report["REQ-LOAN-1"] == {
        "requirement_id": "REQ-LOAN-1",
        "tests": 1,
        "passed": 0,
        "failed": 1,
        "errors": 0,
        "open_bugs": 1,
    }
    assert report["REQ-LOAN-2"]["open_bugs"] == 0


def test_review_and_exports(api: tuple[TestClient, FakeModel]) -> None:
    client, _ = api
    client.post("/requirements/index")
    run_id = client.post("/runs", json={"story_key": "SHELF-3"}).json()["run_id"]
    cases = client.get(f"/runs/{run_id}").json()["test_cases"]
    for case in cases:
        assert (
            client.post(
                f"/test-cases/{case['id']}/review", json={"decision": "approved"}
            ).status_code
            == 200
        )
    assert (
        client.post("/test-cases/999999/review", json={"decision": "approved"}).status_code == 404
    )
    assert (
        client.post(f"/test-cases/{cases[0]['id']}/review", json={"decision": "maybe"}).status_code
        == 422
    )

    collection = client.get("/exports/postman").json()
    assert [f["name"] for f in collection["item"]] == [
        "REQ-LOAN-1: Fourth loan refused",
        "REQ-LOAN-2: Last copy",
        "REQ-LOAN-3: Due in 14 days",
    ]
    assert "def test_req_loan_1_fourth_loan_refused" in client.get("/exports/pytest").text

    rows = list(csv.DictReader(io.StringIO(client.get("/exports/test-cases.csv").text)))
    assert rows[0]["ID"].startswith("TC-") and rows[0]["Steps"].startswith("1. Send POST")
    bugs = list(csv.DictReader(io.StringIO(client.get("/exports/bugs.csv").text)))
    assert {b["Priority"] for b in bugs} == {"High"} and "*Steps to reproduce:*" in bugs[0][
        "Description"
    ]


def test_cannot_approve_a_test_that_errored(api: tuple[TestClient, FakeModel]) -> None:
    client, model = api
    broken = {**LIMIT, "steps": LIMIT["steps"][1:]}  # uses {{m}} without saving it
    model.plans = [{"api_tests": [broken], "ui_tests": []}] * 2
    model.repair = None  # the repair returns "null", which fails validation
    client.post("/requirements/index")
    run_id = client.post("/runs", json={"story_key": "SHELF-3"}).json()["run_id"]
    [case] = client.get(f"/runs/{run_id}").json()["test_cases"]
    assert case["outcome"] == "error"
    assert (
        client.post(f"/test-cases/{case['id']}/review", json={"decision": "approved"}).status_code
        == 409
    )


def _run_exported(module: str, url: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "test_regression.py"
    path.write_text(module)
    env = {**os.environ, "TARGET_URL": url, "BROWSER": os.environ.get("VERITY_TEST_BROWSER", "")}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )


def test_exported_pytest_passes_on_fixed_and_fails_on_buggy(
    fixed_url: str, buggy_url: str, tmp_path: Path
) -> None:
    api = [ApiTest.model_validate(t) for t in (LIMIT, AVAILABILITY, DUE_FIXED)]
    module = pytest_module(api, [])
    compile(module, "test_regression.py", "exec")
    fixed = _run_exported(module, fixed_url, tmp_path)
    assert fixed.returncode == 0, fixed.stdout
    buggy = _run_exported(module, buggy_url, tmp_path)
    assert "2 failed, 1 passed" in buggy.stdout, buggy.stdout


@pytest.mark.browser
def test_exported_ui_test_runs_in_a_browser(
    fixed_url: str, buggy_url: str, tmp_path: Path, browser_executable: str | None
) -> None:
    module = pytest_module([], [UiTest.model_validate(UI)])
    fixed = _run_exported(module, fixed_url, tmp_path)
    assert fixed.returncode == 0, fixed.stdout[-3000:]
    assert "1 failed" in _run_exported(module, buggy_url, tmp_path).stdout


@pytest.mark.skipif(shutil.which("npx") is None, reason="needs Node.js for Newman")
def test_postman_collection_runs_in_newman(fixed_url: str, buggy_url: str, tmp_path: Path) -> None:
    collection = postman_collection(
        [ApiTest.model_validate(t) for t in (LIMIT, AVAILABILITY, DUE_FIXED)], fixed_url
    )
    path = tmp_path / "collection.json"
    path.write_text(json.dumps(collection))

    def newman(url: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "npx",
                "--yes",
                "newman@6",
                "run",
                str(path),
                "--env-var",
                f"baseUrl={url}",
                "--reporters",
                "cli",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

    fixed = newman(fixed_url)
    assert fixed.returncode == 0, fixed.stdout[-2000:]
    buggy = newman(buggy_url)
    assert buggy.returncode != 0
    assert "expected 201 to equal 409" in buggy.stdout or "status is 409" in buggy.stdout


def test_evaluation_scores_against_the_answer_key(
    db: sessionmaker[Session], shelf_db_url: str, tmp_path: Path
) -> None:
    settings = Settings(embedding_provider="hashing")
    model = FakeModel([PLAN] * 4)
    report = evaluate(
        settings,
        db,
        model,
        HashingEmbedder(),
        shelf_db_url,
        ROOT / "eval" / "ground_truth.json",
        ["SHELF-3"],
        use_browser=False,
    )
    assert report.planted == ["REQ-LOAN-1", "REQ-LOAN-3", "REQ-UI-1"]
    # The UI test is skipped without a browser, so the UI bug is missed.
    assert report.detected == ["REQ-LOAN-1", "REQ-LOAN-3"] and report.missed == ["REQ-UI-1"]
    assert report.false_reports_buggy == [] and report.false_reports_fixed == []
    assert report.buggy.tests == 3 and report.fixed.passed == 3
    assert report.note.startswith("Not a live model")
    markdown = save(report, tmp_path).read_text()
    assert "Planted bugs found: **2/3**" in markdown
