"""Regression test: a row must be committed before its 201 response is sent.

With FastAPI's default dependency scope, Shelf committed after replying, so a
client that used the new id straight away sometimes got "member not found".
"""

import httpx
import pytest

from shelf.server import serve_in_thread

pytestmark = pytest.mark.db


def test_new_member_is_usable_immediately(shelf_db_url: str) -> None:
    with serve_in_thread(shelf_db_url, "none") as url, httpx.Client(base_url=url) as http:
        assert http.post("/api/test/reset").status_code == 204
        for n in range(100):
            member = http.post(
                "/api/members", json={"name": "A", "email": f"a{n}@example.com"}
            ).json()["id"]
            loans = http.get(f"/api/members/{member}/loans")
            assert loans.status_code == 200, f"attempt {n}: {loans.text}"
