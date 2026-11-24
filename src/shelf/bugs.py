"""Planted bugs in the Shelf sample app.

Shelf exists so Verity has something with known defects to test. Each bug is
switched on by name through SHELF_BUGS, which lets the evaluation run the same
tests against a buggy build (to count bugs found) and a fixed build (to count
false bug reports).
"""

from collections.abc import Iterable

ALL_BUGS = frozenset(
    {
        "BUG-1",  # REQ-LOAN-1: a fourth active loan is allowed
        "BUG-2",  # REQ-BOOK-1: title search is case-sensitive
        "BUG-3",  # REQ-LOAN-4: returning a loan twice succeeds
        "BUG-4",  # REQ-LOAN-3: due date is 13 days after borrowing
        "BUG-5",  # REQ-FEE-1: late fee has no cap
        "BUG-6",  # REQ-MEM-1: email without "@" is accepted
        "BUG-7",  # REQ-UI-1: borrow page reports success after a refused loan
        "BUG-8",  # REQ-LIST-1: member loan list includes returned loans
    }
)


class BugSet:
    def __init__(self, enabled: Iterable[str]) -> None:
        requested = frozenset(enabled)
        unknown = requested - ALL_BUGS
        if unknown:
            raise ValueError(f"unknown bug ids: {sorted(unknown)}")
        self._enabled = requested

    @classmethod
    def parse(cls, spec: str) -> "BugSet":
        """Parse "all", "none" or a comma-separated list such as "BUG-1,BUG-4"."""
        spec = spec.strip()
        if spec == "all":
            return cls(ALL_BUGS)
        if spec in ("", "none"):
            return cls(())
        return cls(part.strip() for part in spec.split(","))

    def on(self, bug_id: str) -> bool:
        if bug_id not in ALL_BUGS:
            raise ValueError(f"unknown bug id: {bug_id}")
        return bug_id in self._enabled

    @property
    def enabled(self) -> frozenset[str]:
        return self._enabled
