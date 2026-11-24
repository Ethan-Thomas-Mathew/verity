# Shelf HTTP API

Base URL is configurable (default `http://127.0.0.1:8001`). Request and response bodies are JSON. Errors return `{"detail": "<message>"}`.

## Test setup

- `POST /api/test/reset` returns 204. It deletes all members and loans and reloads the seed books. Call it at the start of every test.

Seed books after a reset (ids are assigned in this order, starting at 1):

| id | title | author | available_copies |
| --- | --- | --- | --- |
| 1 | The Hobbit | J. R. R. Tolkien | 3 |
| 2 | Dune | Frank Herbert | 1 |
| 3 | Clean Code | Robert C. Martin | 2 |
| 4 | The Pragmatic Programmer | Andrew Hunt | 2 |
| 5 | Malgudi Days | R. K. Narayan | 4 |
| 6 | Wings of Fire | A. P. J. Abdul Kalam | 5 |

## Members

- `POST /api/members` with `{"name": str, "email": str}` returns 201 `{"id", "name", "email"}`.
- `GET /api/members/{member_id}/loans` returns 200, a list of `{"loan_id", "book_id", "title", "borrowed_on", "due_on", "returned_on"}`.

## Books

- `GET /api/books?q=<text>` returns 200, a list of `{"id", "title", "author", "available_copies"}`.

## Loans

- `POST /api/loans` with `{"member_id": int, "book_id": int, "borrowed_on": "YYYY-MM-DD"}` returns 201 `{"id", "member_id", "book_id", "borrowed_on", "due_on", "returned_on"}`. `borrowed_on` is optional and defaults to today.
- `POST /api/loans/{loan_id}/return` with `{"returned_on": "YYYY-MM-DD"}` returns 200 with the loan. `returned_on` is optional and defaults to today.
- `GET /api/loans/{loan_id}/fee?as_of=YYYY-MM-DD` returns 200 `{"loan_id", "fee"}`, the late fee in rupees as of that date (or as of the return date if the loan was returned).

## Web pages

- `GET /books` is the search page.
- `GET /borrow` is the borrow form; submitting it posts to `/borrow`.
