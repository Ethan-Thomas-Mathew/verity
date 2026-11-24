# How Verity follows the software testing life cycle

| STLC phase | What happens in Verity | Where |
| --- | --- | --- |
| Requirement analysis | Requirements are indexed; the retriever finds the sections a story needs | `requirements/shelf/`, `src/verity/rag/` |
| Test planning | The planner decides which requirements get API tests and which get UI tests; the coverage check makes sure each requirement has at least one | `agents/graph.py` (planner, coverage) |
| Test case design | Each test is a spec with steps and expected results, also exported as manual test cases | `runners/specs.py`, `/exports/test-cases.csv` |
| Test environment setup | Shelf and PostgreSQL run in Docker; every test starts with `POST /api/test/reset` so tests cannot affect each other | `docker-compose.yml` |
| Test execution | API tests run with httpx, UI tests in Chromium with Playwright | `runners/api_runner.py`, `runners/ui_runner.py` |
| Defect reporting | Each failed test becomes a bug report with steps, expected and actual results, and severity | reporter in `agents/graph.py`, `/exports/bugs.csv` |
| Test closure | Results per requirement; approved tests become the regression suite | `/reports/requirements`, `/exports/postman`, `/exports/pytest` |

## Types of testing covered

- **Functional testing:** every test checks a stated requirement.
- **Negative testing:** the planner is told to test the rule being broken (a fourth loan, an invalid email, a second return).
- **API testing:** status codes, JSON fields and list lengths.
- **UI testing:** form input, button clicks, messages shown and not shown.
- **Regression testing:** approved tests export to a Postman collection and a pytest file, which CI runs on every push.

## Pass, fail and error

| Outcome | Meaning | Becomes a bug report? |
| --- | --- | --- |
| passed | The app did what the requirement says | No |
| failed | The app answered differently from the requirement | Yes |
| error | The test itself was broken (unknown field label, variable never saved) | No; the repair agent may fix it once |

Keeping "error" separate from "failed" keeps broken tests from being reported as bugs in the application.
