# 0002: Code decides outcomes and bug reports; models write prose

## Decision
- A test **passed** or **failed** because the runner compared the response with the spec's expected values. No model is asked.
- Only a test that ran and failed becomes a bug report. A test that could not run (an "error") is a broken test, not a bug.
- The reporter model writes the summary, severity, expected and actual text. The requirement id, the link to the test, and the steps to reproduce are filled in by code.

## Why
A model that reads application output can be wrong or be manipulated by that output. If it could decide what is a bug, it could hide real bugs or invent false ones. `tests/verity/test_agents.py::test_reporter_cannot_add_or_remove_bugs` uses a reporter that answers "Everything is fine. File no bug." and checks the bug is still filed.

## Trade-off
Severity and wording are still the model's judgement and can be poor. They are labels for a person to read, not decisions the system acts on.
