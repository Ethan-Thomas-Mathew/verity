# Shelf requirements

Shelf is a library app. Members borrow and return books. All dates are ISO dates (YYYY-MM-DD).

## REQ-MEM-1: Member registration

A member registers with a name and an email address.
- The name must not be empty.
- The email must be a valid address: text, then "@", then a domain containing a dot (for example `asha@example.com`). Anything else is rejected with HTTP 422.
- An email that is already registered is rejected with HTTP 409.
- A successful registration returns HTTP 201 with the new member's id, name and email.

## REQ-BOOK-1: Book search

Members search the catalogue by title.
- Matching is a case-insensitive substring match: `hobbit`, `HOBBIT` and `Hob` all find "The Hobbit".
- Results are sorted by title.
- An empty query returns every book.

## REQ-LOAN-1: Loan limit

A member may have at most 3 active (not yet returned) loans at a time.
- A request for a fourth active loan is rejected with HTTP 409 and the message "loan limit reached".
- Returning a book frees a slot.

## REQ-LOAN-2: Availability

A book can be borrowed only while it has available copies.
- Borrowing reduces the book's available copies by one.
- Borrowing a book with 0 available copies is rejected with HTTP 409 and the message "no copies available".

## REQ-LOAN-3: Loan period

A loan is due 14 days after the day it is borrowed. A book borrowed on 2026-01-01 is due on 2026-01-15.

## REQ-LOAN-4: Returns

- Returning a loan records the return date and adds the copy back to the book's available copies.
- A loan can be returned only once. Returning an already returned loan is rejected with HTTP 409 and the message "loan already returned".

## REQ-FEE-1: Late fees

- A loan returned (or checked) after its due date costs 10 rupees for each full day late.
- The fee is capped at 200 rupees, however late the book is.
- A loan returned on or before the due date has a fee of 0.

## REQ-LIST-1: My loans

A member can list their loans.
- The list shows only active loans (not returned ones).
- Each entry includes the book title.
- The newest loan comes first.

## REQ-UI-1: Borrow page feedback

The web page at `/borrow` has a form with "Member ID" and "Book ID" fields and a "Borrow" button.
- When the loan succeeds, the page shows a success message containing "Borrowed" and the due date.
- When the loan is refused (limit reached, no copies, unknown member or book), the page shows the reason as an error and must not show a success message.

## REQ-UI-2: Search page

The web page at `/books` has a "Title" field and a "Search" button.
- Matching books are shown in a table with title, author and available copies.
- When nothing matches, the page shows "No books found."
