# 0009: Commit before the response is sent

## Context
A test that registered a member and immediately borrowed a book failed about one run in four with "member not found".

## Cause
Shelf's database session was a FastAPI dependency with `yield`, committing after the `yield`. By default that code runs after the response is sent, so a fast client could use the new id before the row was committed.

## Decision
The dependency uses `Depends(service, scope="function")`, which runs the commit before the response. `tests/shelf/test_commit_before_response.py` creates 100 members and uses each at once; it fails reliably without the fix.

## Lesson
A flaky test was a real bug. Re-running until it passed would have hidden it.
