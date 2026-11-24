"""Scripted stand-ins for a language model, and test specs shared by several tests."""

import json
from collections.abc import Callable
from typing import Any

from verity.agents import prompts
from verity.llm.base import Message


def member_step(save: str = "m") -> dict[str, Any]:
    return {
        "method": "POST",
        "path": "/api/members",
        "body": {"name": "Asha", "email": "asha@example.com"},
        "expect": {"status": 201},
        "save": {save: "id"},
    }


def loan_step(book: int, status: int = 201, **fields: Any) -> dict[str, Any]:
    body = {"member_id": "{{m}}", "book_id": book, "borrowed_on": "2026-01-01"}
    return {
        "method": "POST",
        "path": "/api/loans",
        "body": body,
        "expect": {"status": status, "fields": fields},
    }


LIMIT = {
    "requirement_id": "REQ-LOAN-1",
    "title": "Fourth loan refused",
    "steps": [
        member_step(),
        loan_step(1),
        loan_step(3),
        loan_step(4),
        loan_step(5, 409, detail="loan limit reached"),
    ],
}
AVAILABILITY = {
    "requirement_id": "REQ-LOAN-2",
    "title": "Last copy",
    "steps": [member_step(), loan_step(2), loan_step(2, 409, detail="no copies available")],
}
# Broken on purpose: uses {{m}} without saving it. The repair agent should fix it.
DUE_BROKEN = {
    "requirement_id": "REQ-LOAN-3",
    "title": "Due in 14 days",
    "steps": [loan_step(1, 201, due_on="2026-01-15")],
}
DUE_FIXED = {**DUE_BROKEN, "steps": [member_step(), *DUE_BROKEN["steps"]]}
UI = {
    "requirement_id": "REQ-UI-1",
    "title": "Refused loan shows an error",
    "setup": [member_step(), loan_step(2)],
    "steps": [
        {"action": "goto", "target": "/borrow"},
        {"action": "fill", "target": "Member ID", "value": "{{m}}"},
        {"action": "fill", "target": "Book ID", "value": "2"},
        {"action": "click", "target": "Borrow"},
        {"action": "expect_no_text", "value": "Borrowed"},
    ],
}
OUTSIDE_STORY = {**AVAILABILITY, "requirement_id": "REQ-FEE-1"}


class FakeModel:
    """Answers by role: planner, repair or reporter, recognised by the system prompt."""

    def __init__(
        self,
        plans: list[dict[str, Any]],
        repair: dict[str, Any] | None = None,
        reporter: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.plans, self.repair, self.reporter = list(plans), repair, reporter
        self.prompts: list[str] = []

    @property
    def name(self) -> str:
        return "fake"

    def complete_json(self, messages: list[Message], schema: dict[str, Any]) -> str:
        system, user = messages[0].content, messages[-1].content
        self.prompts.append(user)
        if system == prompts.PLANNER:
            return json.dumps(self.plans.pop(0))
        if system == prompts.REPAIR:
            return json.dumps(self.repair)
        assert system == prompts.REPORTER
        default = {"summary": "Rule broken", "severity": "high", "expected": "e", "actual": "a"}
        return json.dumps(self.reporter(user) if self.reporter else default)
