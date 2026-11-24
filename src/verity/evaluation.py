"""Measure how well the agents find bugs, using Shelf's planted bugs as the answer key.

Every story runs twice: against a build with all bugs switched on, and against
a build with none. A bug report counts as correct only when its requirement has
a planted bug. Any report against the fixed build is a false report.
"""

import json
import logging
import platform
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from shelf.server import serve_in_thread
from verity.config import Settings
from verity.db.database import transaction
from verity.db.models import Run
from verity.llm.base import LLMClient
from verity.rag.embeddings import Embedder
from verity.rag.store import index_directory
from verity.runs import create_run, execute_run
from verity.stories import Story, load_stories

log = logging.getLogger("verity.evaluation")


@dataclass
class BuildResult:
    runs: int = 0
    failed_runs: int = 0
    tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    repaired: int = 0
    bug_requirements: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    model: str
    started_at: str
    seconds: float
    machine: str
    stories: list[str]
    planted: list[str]
    detected: list[str]
    missed: list[str]
    false_reports_buggy: list[str]
    false_reports_fixed: list[str]
    buggy: BuildResult
    fixed: BuildResult
    note: str = ""

    @property
    def recall(self) -> str:
        return f"{len(self.detected)}/{len(self.planted)}"


def _collect(factory: sessionmaker[Session], run_id: object, into: BuildResult) -> None:
    with factory() as session:
        run = session.get_one(Run, run_id)
        into.runs += 1
        if run.status != "finished":
            into.failed_runs += 1
        for case in run.test_cases:
            into.tests += 1
            into.passed += case.outcome == "passed"
            into.failed += case.outcome == "failed"
            into.errors += case.outcome == "error"
            into.repaired += bool(case.spec.get("repaired"))
        into.bug_requirements += [bug.requirement_id for bug in run.bugs]


def evaluate(
    settings: Settings,
    factory: sessionmaker[Session],
    llm: LLMClient,
    embedder: Embedder,
    shelf_database_url: str,
    ground_truth: Path,
    story_keys: list[str] | None = None,
    use_browser: bool = True,
) -> EvalReport:
    truth = json.loads(ground_truth.read_text())
    planted_by_requirement: dict[str, str] = {req: bug for bug, req in truth["bugs"].items()}
    all_stories = load_stories(settings.requirements_dir)
    stories: list[Story] = [all_stories[k] for k in (story_keys or sorted(all_stories))]
    in_scope = {req for story in stories for req in story.requirements}

    with transaction(factory) as session:
        index_directory(session, embedder, settings.requirements_dir)

    started, clock = datetime.now(UTC), time.monotonic()
    buggy, fixed = BuildResult(), BuildResult()
    for bugs, result in (("all", buggy), ("none", fixed)):
        with serve_in_thread(shelf_database_url, bugs) as url:
            target = settings.model_copy(update={"target_url": url})
            for story in stories:
                run_id = create_run(factory, story, url, llm.name)
                try:
                    execute_run(run_id, story, target, factory, llm, embedder, use_browser)
                except Exception as exc:
                    # Stored on the run and counted as a failed run; the evaluation goes on.
                    log.warning("run for %s on %s build failed: %s", story.key, bugs, exc)
                _collect(factory, run_id, result)

    planted = sorted(req for req in planted_by_requirement if req in in_scope)
    reported = set(buggy.bug_requirements)
    note = ""
    if llm.name in ("replay", "fake"):
        note = "Not a live model: replayed or scripted replies. Measures the plumbing only."
    return EvalReport(
        model=llm.name,
        started_at=started.isoformat(timespec="seconds"),
        seconds=round(time.monotonic() - clock, 1),
        machine=f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        stories=[s.key for s in stories],
        planted=planted,
        detected=sorted(reported & set(planted)),
        missed=sorted(set(planted) - reported),
        false_reports_buggy=sorted(r for r in buggy.bug_requirements if r not in planted),
        false_reports_fixed=sorted(fixed.bug_requirements),
        buggy=buggy,
        fixed=fixed,
        note=note,
    )


def to_markdown(report: EvalReport) -> str:
    lines = [f"# Verity evaluation: {report.model}", ""]
    if report.note:
        lines += [f"**{report.note}**", ""]
    lines += [
        f"- Run at {report.started_at} on {report.machine}, {report.seconds} s",
        f"- Stories: {', '.join(report.stories)}",
        f"- Planted bugs found: **{report.recall}**"
        + (f" (missed {', '.join(report.missed)})" if report.missed else ""),
        f"- False bug reports on the buggy build: **{len(report.false_reports_buggy)}**",
        f"- False bug reports on the fixed build: **{len(report.false_reports_fixed)}**",
        "",
        "| Build | Runs (failed) | Tests | Passed | Failed | Errors | Repaired | Bug reports |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, b in (("all bugs on", report.buggy), ("no bugs", report.fixed)):
        lines.append(
            f"| {name} | {b.runs} ({b.failed_runs}) | {b.tests} | {b.passed} | {b.failed} "
            f"| {b.errors} | {b.repaired} | {len(b.bug_requirements)} |"
        )
    return "\n".join(lines) + "\n"


def save(report: EvalReport, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.replace(":", "").replace("-", "")
    safe_model = "".join(c if c.isalnum() else "-" for c in report.model)
    base = directory / f"{stamp}-{safe_model}"
    data = asdict(report) | {"recall": report.recall}
    base.with_suffix(".json").write_text(json.dumps(data, indent=2))
    base.with_suffix(".md").write_text(to_markdown(report))
    return base.with_suffix(".md")
