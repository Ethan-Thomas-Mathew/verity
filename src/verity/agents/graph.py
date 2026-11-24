"""The multi-agent workflow, built as a LangGraph state graph.

    retrieve -> planner -> coverage --(gaps, first time)--> planner
                              |
                              v
                        api_tester -> ui_tester -> reporter -> END

Each node is one agent with one job. Language models write test specs and bug
report prose; code decides which tests run, whether a test passed, and which
results become bug reports.
"""

import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from verity.agents import prompts
from verity.llm.base import LLMClient, LLMError, Message
from verity.llm.structured import ask
from verity.rag.store import Retrieved
from verity.runners.api_runner import Result
from verity.runners.specs import ApiTest, TestPlan, UiTest, manual_steps
from verity.stories import Story

MAX_PLANNING_ROUNDS = 2


class BugDraft(BaseModel):
    """What the reporter model writes. Ids and links are filled in by code."""

    summary: str = Field(max_length=200)
    severity: Literal["high", "medium", "low"]
    expected: str
    actual: str


@dataclass
class Executed:
    test: ApiTest | UiTest
    result: Result
    repaired: bool = False

    @property
    def kind(self) -> str:
        return "api" if isinstance(self.test, ApiTest) else "ui"


@dataclass
class Bug:
    executed: Executed
    draft: BugDraft
    steps_to_reproduce: list[str]


class State(TypedDict, total=False):
    story: Story
    context: list[Retrieved]
    plan: TestPlan
    planning_rounds: int
    missing: list[str]
    executed: Annotated[list[Executed], operator.add]
    bugs: list[Bug]
    events: Annotated[list[tuple[str, str]], operator.add]


@dataclass
class Tools:
    """Everything the agents can touch. Passed in, so tests can substitute fakes."""

    llm: LLMClient
    retrieve: Callable[[Story], list[Retrieved]]
    run_api: Callable[[ApiTest], Result]
    # None when no browser is available; UI tests are then skipped and logged.
    run_ui: Callable[[list[UiTest]], list[Result]] | None


def _covered(plan: TestPlan) -> set[str]:
    tests: list[ApiTest | UiTest] = [*plan.api_tests, *plan.ui_tests]
    return {t.requirement_id for t in tests}


def _protected(test: ApiTest | UiTest) -> list[object]:
    """What a repair must keep: every request sent and every expected result, in order.

    A repair may add steps (for example a missing setup call) or fix a name such
    as a field label or a saved variable. It may not change what is sent or what
    is expected, because that could turn a real failure into a pass.
    """
    api_steps = test.steps if isinstance(test, ApiTest) else test.setup
    kept: list[object] = [s.model_dump(exclude={"save"}) for s in api_steps]
    if isinstance(test, UiTest):
        kept += [
            (a.action, a.target if a.action == "goto" else "", a.value)
            for a in test.steps
            if a.action != "click"
        ]
    return kept


def _keeps_all(original: list[object], repaired: list[object]) -> bool:
    """True if `original` appears in `repaired` in the same order, with extras allowed."""
    remaining = iter(repaired)
    return all(any(item == other for other in remaining) for item in original)


def build_graph(tools: Tools) -> CompiledStateGraph:  # type: ignore[type-arg]
    def retrieve(state: State) -> State:
        context = tools.retrieve(state["story"])
        names = ", ".join(f"{r.section.heading} ({r.match})" for r in context)
        return {"context": context, "events": [("retriever", f"retrieved {names}")]}

    def planner(state: State) -> State:
        story = state["story"]
        request = prompts.story_text(story)
        if state.get("missing"):
            request += (
                "\nYour previous plan had no tests for: "
                + ", ".join(state["missing"])
                + ". Return a complete plan that covers every listed requirement."
            )
        plan = ask(
            tools.llm,
            [
                Message(role="system", content=prompts.PLANNER),
                Message(role="user", content=f"{prompts.documents(state['context'])}\n\n{request}"),
            ],
            TestPlan,
        )
        # The model may only test what this story asks for.
        allowed = set(story.requirements)
        kept = TestPlan(
            api_tests=[t for t in plan.api_tests if t.requirement_id in allowed],
            ui_tests=[t for t in plan.ui_tests if t.requirement_id in allowed],
        )
        dropped = (
            len(plan.api_tests) + len(plan.ui_tests) - len(kept.api_tests) - len(kept.ui_tests)
        )
        rounds = state.get("planning_rounds", 0) + 1
        message = f"round {rounds}: {len(kept.api_tests)} API and {len(kept.ui_tests)} UI tests"
        if dropped:
            message += f"; dropped {dropped} for requirements outside the story"
        return {"plan": kept, "planning_rounds": rounds, "events": [("planner", message)]}

    def coverage(state: State) -> State:
        missing = sorted(set(state["story"].requirements) - _covered(state["plan"]))
        note = (
            "every requirement has a test" if not missing else "no tests for " + ", ".join(missing)
        )
        return {"missing": missing, "events": [("coverage", note)]}

    def after_coverage(state: State) -> str:
        if state["missing"] and state["planning_rounds"] < MAX_PLANNING_ROUNDS:
            return "planner"
        return "api_tester"

    def repair[T: (ApiTest, UiTest)](test: T, error: str) -> T | None:
        try:
            fixed = ask(
                tools.llm,
                [
                    Message(role="system", content=prompts.REPAIR),
                    Message(
                        role="user",
                        content=f"Test:\n{test.model_dump_json()}\n\nError:\n{error}",
                    ),
                ],
                type(test),
            )
        except LLMError:
            return None
        same_target = fixed.requirement_id == test.requirement_id
        if not same_target or not _keeps_all(_protected(test), _protected(fixed)):
            return None  # a "repair" that edits expectations could hide a real bug
        return fixed

    def api_tester(state: State) -> State:
        executed: list[Executed] = []
        events: list[tuple[str, str]] = []
        for test in state["plan"].api_tests:
            result = tools.run_api(test)
            repaired = False
            if result.outcome == "error":
                fixed = repair(test, result.detail)
                if fixed is not None:
                    events.append(("api_tester", f"repaired '{test.title}': {result.detail}"))
                    test, result, repaired = fixed, tools.run_api(fixed), True
            executed.append(Executed(test, result, repaired))
            events.append(("api_tester", f"{result.outcome}: {test.title}"))
        return {"executed": executed, "events": events}

    def ui_tester(state: State) -> State:
        tests = state["plan"].ui_tests
        if not tests:
            return {"events": [("ui_tester", "no UI tests planned")]}
        if tools.run_ui is None:
            return {"events": [("ui_tester", f"skipped {len(tests)} UI tests: no browser")]}
        results = tools.run_ui(tests)
        executed = [Executed(t, r) for t, r in zip(tests, results, strict=True)]
        return {
            "executed": executed,
            "events": [("ui_tester", f"{e.result.outcome}: {e.test.title}") for e in executed],
        }

    def reporter(state: State) -> State:
        bugs: list[Bug] = []
        events: list[tuple[str, str]] = []
        requirement_text = {r.section.requirement_id: r.section.content for r in state["context"]}
        # Only a test that ran and failed can become a bug. Errors are broken tests.
        for executed in [e for e in state.get("executed", []) if e.result.outcome == "failed"]:
            test = executed.test
            prompt = (
                f"Requirement {test.requirement_id}:\n"
                f"{requirement_text.get(test.requirement_id, '(text not retrieved)')}\n\n"
                f"Test: {test.title}\n"
                f"<test_output>\n{executed.result.detail}\n</test_output>"
            )
            try:
                draft = ask(
                    tools.llm,
                    [
                        Message(role="system", content=prompts.REPORTER),
                        Message(role="user", content=prompt),
                    ],
                    BugDraft,
                )
            except LLMError as exc:
                # The failure is real even if the prose could not be written.
                draft = BugDraft(
                    summary=f"{test.requirement_id} failed: {test.title}"[:200],
                    severity="medium",
                    expected=f"Behaviour described in {test.requirement_id}",
                    actual=executed.result.detail,
                )
                events.append(("reporter", f"wrote a plain report, model failed: {exc}"))
            bugs.append(Bug(executed, draft, manual_steps(test)))
        events.append(("reporter", f"{len(bugs)} bug reports"))
        return {"bugs": bugs, "events": events}

    graph = StateGraph(State)
    for name, node in [
        ("retrieve", retrieve),
        ("planner", planner),
        ("coverage", coverage),
        ("api_tester", api_tester),
        ("ui_tester", ui_tester),
        ("reporter", reporter),
    ]:
        graph.add_node(name, node)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "planner")
    graph.add_edge("planner", "coverage")
    graph.add_conditional_edges("coverage", after_coverage, ["planner", "api_tester"])
    graph.add_edge("api_tester", "ui_tester")
    graph.add_edge("ui_tester", "reporter")
    graph.add_edge("reporter", END)
    return graph.compile()
