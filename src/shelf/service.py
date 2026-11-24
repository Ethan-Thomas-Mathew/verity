"""Library rules for Shelf. Each rule cites the requirement it implements."""

import re
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shelf.bugs import BugSet
from shelf.models import SEED_BOOKS, Base, Book, Loan, Member

LOAN_LIMIT = 3
LOAN_DAYS = 14
FEE_PER_DAY = 10
FEE_CAP = 200
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ShelfError(Exception):
    """Base class for rule violations the API turns into HTTP errors."""


class NotFound(ShelfError):
    pass


class Conflict(ShelfError):
    pass


class Invalid(ShelfError):
    pass


@dataclass(frozen=True)
class LoanView:
    loan_id: int
    book_id: int
    title: str
    borrowed_on: date
    due_on: date
    returned_on: date | None


class LibraryService:
    def __init__(self, session: Session, bugs: BugSet) -> None:
        self._s = session
        self._bugs = bugs

    # REQ-MEM-1
    def register(self, name: str, email: str) -> Member:
        if not name.strip():
            raise Invalid("name is required")
        email_ok = "." in email if self._bugs.on("BUG-6") else EMAIL_PATTERN.match(email)
        if not email_ok:
            raise Invalid("email is not valid")
        member = Member(name=name.strip(), email=email.lower())
        self._s.add(member)
        try:
            self._s.flush()
        except IntegrityError as exc:
            self._s.rollback()
            raise Conflict("email is already registered") from exc
        return member

    # REQ-BOOK-1
    def search(self, query: str) -> list[Book]:
        pattern = f"%{query}%"
        condition = (
            Book.title.like(pattern) if self._bugs.on("BUG-2") else Book.title.ilike(pattern)
        )
        return list(self._s.scalars(select(Book).where(condition).order_by(Book.title)))

    # REQ-LOAN-1, REQ-LOAN-2, REQ-LOAN-3
    def borrow(self, member_id: int, book_id: int, borrowed_on: date) -> Loan:
        if self._s.get(Member, member_id) is None:
            raise NotFound("member not found")
        # Lock the book row so two borrowers cannot take the last copy at once.
        book = self._s.get(Book, book_id, with_for_update=True)
        if book is None:
            raise NotFound("book not found")
        active = (
            self._s.scalar(
                select(func.count())
                .select_from(Loan)
                .where(Loan.member_id == member_id, Loan.returned_on.is_(None))
            )
            or 0
        )
        at_limit = active > LOAN_LIMIT if self._bugs.on("BUG-1") else active >= LOAN_LIMIT
        if at_limit:
            raise Conflict("loan limit reached")
        if book.available_copies <= 0:
            raise Conflict("no copies available")
        days = LOAN_DAYS - 1 if self._bugs.on("BUG-4") else LOAN_DAYS
        loan = Loan(
            member_id=member_id,
            book_id=book_id,
            borrowed_on=borrowed_on,
            due_on=borrowed_on + timedelta(days=days),
        )
        book.available_copies -= 1
        self._s.add(loan)
        self._s.flush()
        return loan

    # REQ-LOAN-4
    def return_loan(self, loan_id: int, returned_on: date) -> Loan:
        loan = self._s.get(Loan, loan_id, with_for_update=True)
        if loan is None:
            raise NotFound("loan not found")
        if loan.returned_on is not None and not self._bugs.on("BUG-3"):
            raise Conflict("loan already returned")
        loan.returned_on = returned_on
        book = self._s.get(Book, loan.book_id, with_for_update=True)
        assert book is not None  # foreign key guarantees the book exists
        book.available_copies += 1
        self._s.flush()
        return loan

    # REQ-FEE-1
    def late_fee(self, loan_id: int, as_of: date) -> int:
        loan = self._s.get(Loan, loan_id)
        if loan is None:
            raise NotFound("loan not found")
        end = loan.returned_on or as_of
        days_late = max(0, (end - loan.due_on).days)
        fee = days_late * FEE_PER_DAY
        return fee if self._bugs.on("BUG-5") else min(fee, FEE_CAP)

    # REQ-LIST-1
    def member_loans(self, member_id: int) -> list[LoanView]:
        if self._s.get(Member, member_id) is None:
            raise NotFound("member not found")
        query = (
            select(Loan, Book.title)
            .join(Book, Book.id == Loan.book_id)
            .where(Loan.member_id == member_id)
            .order_by(Loan.borrowed_on.desc(), Loan.id.desc())
        )
        if not self._bugs.on("BUG-8"):
            query = query.where(Loan.returned_on.is_(None))
        return [
            LoanView(loan.id, loan.book_id, title, loan.borrowed_on, loan.due_on, loan.returned_on)
            for loan, title in self._s.execute(query)
        ]


def reset_database(engine: Engine) -> None:
    """Drop all data and reload the seed books. Only reachable in test mode."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add_all(Book(title=t, author=a, available_copies=c) for t, a, c in SEED_BOOKS)


def seed_if_empty(engine: Engine) -> None:
    """Create the tables and load the seed books on first start."""
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        if session.scalar(select(func.count()).select_from(Book)) == 0:
            session.add_all(Book(title=t, author=a, available_copies=c) for t, a, c in SEED_BOOKS)
