"""The test format the agents write.

Agents never write executable code. They write these declarative specs, which
Pydantic validates and Verity's own runners execute. A spec can only send HTTP
requests to the target app and drive its pages with a fixed set of actions,
so a confused or manipulated model cannot run arbitrary code on this machine.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Scalar = str | int | float | bool | None

# Small models often describe a field's type instead of its expected value.
TYPE_NAMES = frozenset(
    {
        "int",
        "integer",
        "str",
        "string",
        "float",
        "number",
        "bool",
        "boolean",
        "date",
        "datetime",
        "list",
        "array",
        "dict",
        "object",
    }
)

REQUIREMENT_PATTERN = r"^REQ-[A-Z]+-\d+$"
RequirementId = Annotated[str, Field(pattern=REQUIREMENT_PATTERN)]


class Expect(BaseModel):
    status: int = Field(ge=100, le=599, description="Expected HTTP status code.")
    fields: dict[str, Scalar] = Field(
        default_factory=dict,
        description='Expected values by dotted JSON path, e.g. {"detail": "loan limit reached", '
        '"0.title": "The Hobbit"}.',
    )
    length: int | None = Field(
        default=None, ge=0, description="Expected length when the body is a JSON list."
    )

    @field_validator("fields")
    @classmethod
    def _values_not_types(cls, fields: dict[str, Scalar]) -> dict[str, Scalar]:
        typed = sorted(
            k for k, v in fields.items() if isinstance(v, str) and v.lower() in TYPE_NAMES
        )
        if typed:
            raise ValueError(
                f"fields {typed} give a type name, not a value. Put the exact value the "
                'requirement promises (for example "loan limit reached" or 1), or leave the '
                "field out to skip checking it"
            )
        return fields


class ApiStep(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(description='Path on the target app, e.g. "/api/loans/{{loan_id}}/return".')
    params: dict[str, str] = Field(default_factory=dict, description="Query string parameters.")
    body: dict[str, Any] | None = Field(default=None, description="JSON request body.")
    expect: Expect
    save: dict[str, str] = Field(
        default_factory=dict,
        description='Values to keep for later steps: {"member_id": "id"} saves the response '
        'field "id" as {{member_id}}.',
    )

    @field_validator("path")
    @classmethod
    def _relative_path(cls, path: str) -> str:
        # Only paths on the configured target. A full URL could send requests anywhere.
        if not path.startswith("/") or "://" in path or path.startswith("//"):
            raise ValueError("path must start with / and must not be a full URL")
        return path


class ApiTest(BaseModel):
    requirement_id: RequirementId
    title: str = Field(max_length=200)
    steps: list[ApiStep] = Field(min_length=1, max_length=12)


class UiAction(BaseModel):
    action: Literal["goto", "fill", "click", "expect_text", "expect_no_text"]
    target: str = Field(
        default="",
        description="goto: page path. fill: the field's label. click: the button's text.",
    )
    value: str = Field(default="", description="fill: text to type. expect_*: text to look for.")

    @model_validator(mode="after")
    def _has_what_it_needs(self) -> "UiAction":
        if self.action in ("goto", "fill", "click") and not self.target.strip():
            raise ValueError(
                f"{self.action} needs a target (page path, field label or button text)"
            )
        if self.action != "goto" and self.action != "click" and not self.value.strip():
            raise ValueError(f"{self.action} needs a value")
        return self


class UiTest(BaseModel):
    requirement_id: RequirementId
    title: str = Field(max_length=200)
    setup: list[ApiStep] = Field(
        default_factory=list,
        max_length=8,
        description="API calls that prepare data first, e.g. registering a member.",
    )
    steps: list[UiAction] = Field(min_length=1, max_length=15)


class TestPlan(BaseModel):
    """What the planner agent returns for one user story."""

    __test__ = False  # tells pytest this is not a test class

    api_tests: list[ApiTest] = Field(default_factory=list, max_length=15)
    ui_tests: list[UiTest] = Field(default_factory=list, max_length=6)


def manual_steps(test: ApiTest | UiTest) -> list[str]:
    """The same test written as numbered steps a person could follow by hand."""
    lines: list[str] = []

    def api(step: ApiStep) -> None:
        query = "&".join(f"{k}={v}" for k, v in step.params.items())
        target = step.path + (f"?{query}" if query else "")
        line = f"Send {step.method} {target}"
        if step.body is not None:
            line += f" with body {step.body}"
        line += f"; expect status {step.expect.status}"
        checks = [f"{path} = {value!r}" for path, value in step.expect.fields.items()]
        if step.expect.length is not None:
            checks.append(f"list length = {step.expect.length}")
        if checks:
            line += " and " + ", ".join(checks)
        lines.append(line)

    if isinstance(test, ApiTest):
        for step in test.steps:
            api(step)
        return lines
    for step in test.setup:
        api(step)
    for action in test.steps:
        match action.action:
            case "goto":
                lines.append(f"Open {action.target}")
            case "fill":
                lines.append(f'Type "{action.value}" into "{action.target}"')
            case "click":
                lines.append(f'Click "{action.target}"')
            case "expect_text":
                lines.append(f'Check the page shows "{action.value}"')
            case "expect_no_text":
                lines.append(f'Check the page does not show "{action.value}"')
    return lines
