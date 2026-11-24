from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(100))
    available_copies: Mapped[int] = mapped_column(Integer)


class Loan(Base):
    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    borrowed_on: Mapped[date] = mapped_column(Date)
    due_on: Mapped[date] = mapped_column(Date)
    returned_on: Mapped[date | None] = mapped_column(Date, nullable=True)


SEED_BOOKS = [
    ("The Hobbit", "J. R. R. Tolkien", 3),
    ("Dune", "Frank Herbert", 1),
    ("Clean Code", "Robert C. Martin", 2),
    ("The Pragmatic Programmer", "Andrew Hunt", 2),
    ("Malgudi Days", "R. K. Narayan", 4),
    ("Wings of Fire", "A. P. J. Abdul Kalam", 5),
]
