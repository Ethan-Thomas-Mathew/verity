from collections.abc import Iterator

import httpx
import pytest
from pydantic import ValidationError

from tests.support import serve_shelf
from verity.runners.api_runner import MISSING, ApiRunner, lookup, substitute
from verity.runners.specs import ApiStep, ApiTest, UiTest, manual_steps
from verity.runners.ui_runner import UiRunner

pytestmark = pytest.mark.db

LOAN_LIMIT = ApiTest.model_validate(
    {
        "requirement_id": "REQ-LOAN-1",
        "title": "A fourth active loan is refused",
        "steps": [
            {
                "method": "POST",
                "path": "/api/members",
                "body": {"name": "Asha", "email": "asha@example.com"},
                "expect": {"status": 201},
                "save": {"member": "id"},
            },
            *[
                {
                    "method": "POST",
                    "path": "/api/loans",
                    "body": {"member_id": "{{member}}", "book_id": book},
                    "expect": {"status": 201},
                }
                for book in (1, 3, 4)
            ],
            {
                "method": "POST",
                "path": "/api/loans",
                "body": {"member_id": "{{member}}", "book_id": 5},
                "expect": {"status": 409, "fields": {"detail": "loan limit reached"}},
            },
        ],
    }
)

BORROW_REFUSED_UI = UiTest.model_validate(
    {
        "requirement_id": "REQ-UI-1",
        "title": "A refused loan shows an error, not success",
        "setup": [
            {
                "method": "POST",
                "path": "/api/members",
                "body": {"name": "Asha", "email": "asha@example.com"},
                "expect": {"status": 201},
                "save": {"member": "id"},
            },
            {
                "method": "POST",
                "path": "/api/loans",
                "body": {"member_id": "{{member}}", "book_id": 2},
                "expect": {"status": 201},
            },
        ],
        "steps": [
            {"action": "goto", "target": "/borrow"},
            {"action": "fill", "target": "Member ID", "value": "{{member}}"},
            {"action": "fill", "target": "Book ID", "value": "2"},
            {"action": "click", "target": "Borrow"},
            {"action": "expect_text", "value": "No copies available"},
            {"action": "expect_no_text", "value": "Borrowed"},
        ],
    }
)


@pytest.fixture(scope="module")
def fixed_url(shelf_db_url: str) -> Iterator[str]:
    with serve_shelf(shelf_db_url, "none") as url:
        yield url


@pytest.fixture(scope="module")
def buggy_url(shelf_db_url: str) -> Iterator[str]:
    with serve_shelf(shelf_db_url, "all") as url:
        yield url


def test_api_test_passes_on_fixed_build(fixed_url: str) -> None:
    with httpx.Client() as http:
        result = ApiRunner(http, fixed_url).run(LOAN_LIMIT)
    assert result.outcome == "passed", result.detail
    assert len(result.log) == 5


def test_api_test_fails_on_buggy_build_with_a_useful_message(buggy_url: str) -> None:
    with httpx.Client() as http:
        result = ApiRunner(http, buggy_url).run(LOAN_LIMIT)
    assert result.outcome == "failed"
    assert "step 5" in result.detail and "expected status 409, got 201" in result.detail


def test_broken_spec_is_an_error_not_a_failure(fixed_url: str) -> None:
    broken = LOAN_LIMIT.model_copy(update={"steps": LOAN_LIMIT.steps[1:]})
    with httpx.Client() as http:
        result = ApiRunner(http, fixed_url).run(broken)
    assert result.outcome == "error"
    assert "{{member}}" in result.detail


def test_wrong_field_value_fails(fixed_url: str) -> None:
    test = ApiTest.model_validate(
        {
            "requirement_id": "REQ-BOOK-1",
            "title": "Search",
            "steps": [
                {
                    "method": "GET",
                    "path": "/api/books",
                    "params": {"q": "hobbit"},
                    "expect": {"status": 200, "length": 1, "fields": {"0.title": "Dune"}},
                }
            ],
        }
    )
    with httpx.Client() as http:
        result = ApiRunner(http, fixed_url).run(test)
    assert result.outcome == "failed"
    assert "0.title expected 'Dune', got 'The Hobbit'" in result.detail


def test_full_urls_are_rejected_by_the_spec() -> None:
    with pytest.raises(ValidationError, match="full URL"):
        ApiStep.model_validate(
            {"method": "GET", "path": "https://evil.example/x", "expect": {"status": 200}}
        )
    with pytest.raises(ValidationError):
        ApiStep.model_validate(
            {"method": "GET", "path": "//evil.example/x", "expect": {"status": 200}}
        )


def test_lookup_and_substitute() -> None:
    data = [{"id": 7, "tags": ["a", "b"]}]
    assert lookup(data, "0.tags.1") == "b"
    assert lookup(data, "1.id") is MISSING
    assert substitute({"id": "{{x}}", "path": "/l/{{x}}"}, {"x": 7}) == {"id": 7, "path": "/l/7"}


def test_manual_steps_read_like_a_test_case() -> None:
    steps = manual_steps(LOAN_LIMIT)
    assert steps[0].startswith("Send POST /api/members with body")
    assert steps[-1].endswith("detail = 'loan limit reached'")
    ui = manual_steps(BORROW_REFUSED_UI)
    assert 'Type "{{member}}" into "Member ID"' in ui
    assert ui[-1] == 'Check the page does not show "Borrowed"'


@pytest.mark.browser
def test_ui_test_passes_on_fixed_and_fails_on_buggy(
    fixed_url: str, buggy_url: str, browser_executable: str | None
) -> None:
    with httpx.Client() as http:
        with UiRunner(ApiRunner(http, fixed_url), fixed_url, browser_executable) as ui:
            fixed = ui.run(BORROW_REFUSED_UI)
        with UiRunner(ApiRunner(http, buggy_url), buggy_url, browser_executable) as ui:
            buggy = ui.run(BORROW_REFUSED_UI)
    assert fixed.outcome == "passed", fixed.detail
    assert buggy.outcome == "failed", buggy.detail


@pytest.mark.browser
def test_ui_missing_field_is_an_error(fixed_url: str, browser_executable: str | None) -> None:
    test = UiTest.model_validate(
        {
            "requirement_id": "REQ-UI-2",
            "title": "Uses a label that does not exist",
            "steps": [
                {"action": "goto", "target": "/books"},
                {"action": "fill", "target": "Author", "value": "Tolkien"},
            ],
        }
    )
    with (
        httpx.Client() as http,
        UiRunner(ApiRunner(http, fixed_url), fixed_url, browser_executable) as ui,
    ):
        result = ui.run(test)
    assert result.outcome == "error"
    assert result.detail.startswith("element not found")
