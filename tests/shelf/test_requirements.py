"""Proves the evaluation's answer key.

With no bugs enabled, Shelf meets every requirement. With exactly one bug
enabled, exactly the requirement listed for it in eval/ground_truth.json fails.
If this file passes, a bug report against a requirement can be scored as right
or wrong without human judgement.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shelf.app import ShelfSettings, create_app

pytestmark = pytest.mark.db

GROUND_TRUTH = json.loads((Path(__file__).parents[2] / "eval" / "ground_truth.json").read_text())
Check = Callable[[TestClient], None]


def _member(c: TestClient, email: str = "asha@example.com") -> int:
    r = c.post("/api/members", json={"name": "Asha", "email": email})
    assert r.status_code == 201, r.text
    member_id: int = r.json()["id"]
    return member_id


def _borrow(c: TestClient, member: int, book: int, on: str = "2026-01-01") -> int:
    r = c.post("/api/loans", json={"member_id": member, "book_id": book, "borrowed_on": on})
    assert r.status_code == 201, r.text
    loan_id: int = r.json()["id"]
    return loan_id


def check_mem_1(c: TestClient) -> None:
    _member(c)
    assert c.post("/api/members", json={"name": "B", "email": "b.example.com"}).status_code == 422
    assert c.post("/api/members", json={"name": "", "email": "x@example.com"}).status_code == 422
    assert (
        c.post("/api/members", json={"name": "A", "email": "asha@example.com"}).status_code == 409
    )


def check_book_1(c: TestClient) -> None:
    titles = [b["title"] for b in c.get("/api/books", params={"q": "hobbit"}).json()]
    assert titles == ["The Hobbit"]


def check_loan_1(c: TestClient) -> None:
    m = _member(c)
    for book in (1, 3, 4):
        _borrow(c, m, book)
    r = c.post("/api/loans", json={"member_id": m, "book_id": 5})
    assert r.status_code == 409 and r.json()["detail"] == "loan limit reached"


def check_loan_2(c: TestClient) -> None:
    m1, m2 = _member(c), _member(c, "ravi@example.com")
    _borrow(c, m1, 2)
    assert c.get("/api/books", params={"q": "Dune"}).json()[0]["available_copies"] == 0
    r = c.post("/api/loans", json={"member_id": m2, "book_id": 2})
    assert r.status_code == 409 and r.json()["detail"] == "no copies available"


def check_loan_3(c: TestClient) -> None:
    m = _member(c)
    r = c.post("/api/loans", json={"member_id": m, "book_id": 1, "borrowed_on": "2026-01-01"})
    assert r.json()["due_on"] == "2026-01-15"


def check_loan_4(c: TestClient) -> None:
    m = _member(c)
    loan = _borrow(c, m, 2)
    assert (
        c.post(f"/api/loans/{loan}/return", json={"returned_on": "2026-01-05"}).status_code == 200
    )
    assert c.get("/api/books", params={"q": "Dune"}).json()[0]["available_copies"] == 1
    again = c.post(f"/api/loans/{loan}/return", json={"returned_on": "2026-01-06"})
    assert again.status_code == 409 and again.json()["detail"] == "loan already returned"


def check_fee_1(c: TestClient) -> None:
    m = _member(c)
    loan = _borrow(c, m, 1, "2026-01-01")  # due 2026-01-15 when the loan period is right
    due_on = c.get(f"/api/members/{m}/loans").json()[0]["due_on"]
    on_time = c.get(f"/api/loans/{loan}/fee", params={"as_of": due_on}).json()["fee"]
    very_late = c.get(f"/api/loans/{loan}/fee", params={"as_of": "2026-12-31"}).json()["fee"]
    assert (on_time, very_late) == (0, 200)


def check_list_1(c: TestClient) -> None:
    m = _member(c)
    first = _borrow(c, m, 1, "2026-01-01")
    _borrow(c, m, 3, "2026-01-02")
    c.post(f"/api/loans/{first}/return", json={"returned_on": "2026-01-03"})
    loans = c.get(f"/api/members/{m}/loans").json()
    assert [entry["title"] for entry in loans] == ["Clean Code"]


def check_ui_1(c: TestClient) -> None:
    m = _member(c)
    ok = c.post("/borrow", data={"member_id": m, "book_id": 2}).text
    assert "Borrowed" in ok
    refused = c.post("/borrow", data={"member_id": m, "book_id": 2}).text
    assert "No copies available" in refused and "Borrowed" not in refused


def check_ui_2(c: TestClient) -> None:
    assert "The Hobbit" in c.get("/books", params={"q": "Hobbit"}).text
    assert "No books found." in c.get("/books", params={"q": "zzz"}).text


CHECKS: dict[str, Check] = {
    "REQ-MEM-1": check_mem_1,
    "REQ-BOOK-1": check_book_1,
    "REQ-LOAN-1": check_loan_1,
    "REQ-LOAN-2": check_loan_2,
    "REQ-LOAN-3": check_loan_3,
    "REQ-LOAN-4": check_loan_4,
    "REQ-FEE-1": check_fee_1,
    "REQ-LIST-1": check_list_1,
    "REQ-UI-1": check_ui_1,
    "REQ-UI-2": check_ui_2,
}


@pytest.fixture
def shelf(shelf_db_url: str) -> Iterator[Callable[[str], TestClient]]:
    apps = []

    def build(bugs: str) -> TestClient:
        app = create_app(ShelfSettings(database_url=shelf_db_url, bugs=bugs, test_mode=True))
        apps.append(app)
        return TestClient(app)

    yield build
    for app in apps:
        app.state.engine.dispose()


def _failing(client: TestClient) -> set[str]:
    failed = set()
    for req, check in CHECKS.items():
        assert client.post("/api/test/reset").status_code == 204
        try:
            check(client)
        except AssertionError:
            failed.add(req)
    return failed


def test_every_requirement_has_a_check() -> None:
    covered = set(GROUND_TRUTH["bugs"].values()) | set(GROUND_TRUTH["clean_requirements"])
    assert covered == set(CHECKS)


def test_fixed_build_meets_every_requirement(shelf: Callable[[str], TestClient]) -> None:
    assert _failing(shelf("none")) == set()


@pytest.mark.parametrize("bug", sorted(GROUND_TRUTH["bugs"]))
def test_each_bug_breaks_only_its_requirement(shelf: Callable[[str], TestClient], bug: str) -> None:
    assert _failing(shelf(bug)) == {GROUND_TRUTH["bugs"][bug]}


def test_reset_is_hidden_outside_test_mode(shelf_db_url: str) -> None:
    app = create_app(ShelfSettings(database_url=shelf_db_url, bugs="none", test_mode=False))
    try:
        assert TestClient(app).post("/api/test/reset").status_code == 404
    finally:
        app.state.engine.dispose()
