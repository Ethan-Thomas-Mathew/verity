"""Shelf: a small library app with planted bugs, used as Verity's system under test."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shelf.bugs import BugSet
from shelf.models import Book, Loan
from shelf.service import (
    Conflict,
    Invalid,
    LibraryService,
    LoanView,
    NotFound,
    reset_database,
    seed_if_empty,
)

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")


class ShelfSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SHELF_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://verity:verity@127.0.0.1:5433/shelf"
    bugs: str = "all"
    # Enables POST /api/test/reset. Never on outside local testing.
    test_mode: bool = False


class MemberIn(BaseModel):
    name: str
    email: str


class MemberOut(BaseModel):
    id: int
    name: str
    email: str


class BookOut(BaseModel):
    id: int
    title: str
    author: str
    available_copies: int


class BorrowIn(BaseModel):
    member_id: int
    book_id: int
    borrowed_on: date = Field(default_factory=date.today)


class ReturnIn(BaseModel):
    returned_on: date = Field(default_factory=date.today)


class LoanOut(BaseModel):
    id: int
    member_id: int
    book_id: int
    borrowed_on: date
    due_on: date
    returned_on: date | None


class MemberLoanOut(BaseModel):
    loan_id: int
    book_id: int
    title: str
    borrowed_on: date
    due_on: date
    returned_on: date | None


class FeeOut(BaseModel):
    loan_id: int
    fee: int


def _book_out(book: Book) -> BookOut:
    return BookOut(
        id=book.id, title=book.title, author=book.author, available_copies=book.available_copies
    )


def _loan_out(loan: Loan) -> LoanOut:
    return LoanOut(
        id=loan.id,
        member_id=loan.member_id,
        book_id=loan.book_id,
        borrowed_on=loan.borrowed_on,
        due_on=loan.due_on,
        returned_on=loan.returned_on,
    )


def _member_loan_out(view: LoanView) -> MemberLoanOut:
    return MemberLoanOut(**view.__dict__)


def create_app(settings: ShelfSettings | None = None) -> FastAPI:
    settings = settings or ShelfSettings()
    bugs = BugSet.parse(settings.bugs)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    seed_if_empty(engine)
    make_session = sessionmaker(engine, expire_on_commit=False)

    app = FastAPI(title="Shelf", description="Sample library app with planted bugs.")
    app.state.engine = engine

    def service() -> Iterator[LibraryService]:
        with make_session() as session:
            try:
                yield LibraryService(session, bugs)
                session.commit()
            except Exception:
                session.rollback()
                raise

    # scope="function" commits before the response is sent. With the default
    # ("request") the commit ran after the client already had its 201, so a fast
    # follow-up request could miss the row it had just created.
    Svc = Annotated[LibraryService, Depends(service, scope="function")]

    @app.exception_handler(NotFound)
    def _not_found(_: Request, exc: NotFound) -> Response:
        return _error(404, str(exc))

    @app.exception_handler(Conflict)
    def _conflict(_: Request, exc: Conflict) -> Response:
        return _error(409, str(exc))

    @app.exception_handler(Invalid)
    def _invalid(_: Request, exc: Invalid) -> Response:
        return _error(422, str(exc))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/members", status_code=201)
    def register(body: MemberIn, svc: Svc) -> MemberOut:
        member = svc.register(body.name, body.email)
        return MemberOut(id=member.id, name=member.name, email=member.email)

    @app.get("/api/books")
    def search(svc: Svc, q: str = "") -> list[BookOut]:
        return [_book_out(b) for b in svc.search(q)]

    @app.post("/api/loans", status_code=201)
    def borrow(body: BorrowIn, svc: Svc) -> LoanOut:
        return _loan_out(svc.borrow(body.member_id, body.book_id, body.borrowed_on))

    @app.post("/api/loans/{loan_id}/return")
    def return_loan(loan_id: int, body: ReturnIn, svc: Svc) -> LoanOut:
        return _loan_out(svc.return_loan(loan_id, body.returned_on))

    @app.get("/api/loans/{loan_id}/fee")
    def late_fee(loan_id: int, svc: Svc, as_of: Annotated[date, Query()]) -> FeeOut:
        return FeeOut(loan_id=loan_id, fee=svc.late_fee(loan_id, as_of))

    @app.get("/api/members/{member_id}/loans")
    def member_loans(member_id: int, svc: Svc) -> list[MemberLoanOut]:
        return [_member_loan_out(v) for v in svc.member_loans(member_id)]

    @app.post("/api/test/reset", status_code=204)
    def reset() -> Response:
        if not settings.test_mode:
            raise HTTPException(status_code=404)
        reset_database(engine)
        return Response(status_code=204)

    # REQ-UI-2
    @app.get("/books", response_class=HTMLResponse)
    def books_page(request: Request, svc: Svc, q: str = "") -> Response:
        books = svc.search(q) if q else []
        return TEMPLATES.TemplateResponse(
            request, "books.html", {"q": q, "books": books, "searched": bool(q)}
        )

    @app.get("/borrow", response_class=HTMLResponse)
    def borrow_form(request: Request) -> Response:
        return TEMPLATES.TemplateResponse(request, "borrow.html", {})

    # REQ-UI-1
    @app.post("/borrow", response_class=HTMLResponse)
    def borrow_submit(
        request: Request,
        member_id: Annotated[int, Form()],
        book_id: Annotated[int, Form()],
    ) -> Response:
        message, error = None, None
        # A fresh session per attempt, so a refused loan never leaves a half-written row.
        with make_session() as session:
            try:
                loan = LibraryService(session, bugs).borrow(member_id, book_id, date.today())
                session.commit()
                message = f"Borrowed. Due back on {loan.due_on.isoformat()}."
            except (NotFound, Conflict) as exc:
                session.rollback()
                error = str(exc).capitalize() + "."
                if bugs.on("BUG-7"):
                    message, error = "Borrowed.", None
        return TEMPLATES.TemplateResponse(
            request, "borrow.html", {"message": message, "error": error}
        )

    return app


def _error(status: int, detail: str) -> Response:
    return JSONResponse(status_code=status, content={"detail": detail})
