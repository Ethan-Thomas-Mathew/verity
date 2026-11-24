import pytest

from shelf.bugs import ALL_BUGS, BugSet


def test_parse_all_none_and_list() -> None:
    assert BugSet.parse("all").enabled == ALL_BUGS
    assert BugSet.parse("none").enabled == frozenset()
    assert BugSet.parse("").enabled == frozenset()
    assert BugSet.parse("BUG-1, BUG-4").enabled == {"BUG-1", "BUG-4"}


def test_unknown_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="BUG-99"):
        BugSet.parse("BUG-99")
    with pytest.raises(ValueError):
        BugSet.parse("none").on("BUG-99")
