# 0006: Measure against planted bugs

## Decision
Shelf has 8 bugs, each switched on by `SHELF_BUGS`, each breaking one requirement. Two requirements have no bug. The evaluation runs every story against the buggy build and the fixed build, then scores:
- planted bugs found (recall),
- false reports on the buggy build (clean requirements),
- false reports on the fixed build (any report).

## Why
Without an answer key, "it found some bugs" cannot be checked. The answer key is itself tested: with no bugs every requirement check passes, and with each single bug exactly its requirement fails (`tests/shelf/test_requirements.py`).

## Trade-off
- The bugs and requirements were written together, so they are cleaner than real software. Numbers from Shelf are a sanity check, not a claim about real applications.
- The answer key lives outside `requirements/` and is never indexed, so the agents cannot read it.
