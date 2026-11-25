# Verity

Verity is a multi-agent QA assistant. Give it a user story, and a team of AI
agents reads the matching requirements, writes API and browser tests, runs them
against the application, and files bug reports for whatever breaks. A person
reviews the tests before they join the regression suite, which can be exported
as a Postman collection or a plain pytest file.

It ships with **Shelf**, a small library app with **8 planted bugs** that can be
switched on and off. Because the bugs are known, Verity's bug-finding can be
measured instead of guessed.

## How it works

```mermaid
flowchart LR
    S[User story<br/>SHELF-3] --> R[Retriever<br/>pgvector]
    R --> P[Planner agent<br/>LLM]
    P --> C{Coverage check}
    C -- gaps, once --> P
    C --> A[API tester<br/>httpx]
    A --> U[UI tester<br/>Playwright]
    U --> B[Reporter agent<br/>LLM]
    B --> DB[(PostgreSQL)]
    A -. broken test .-> F[Repair agent<br/>LLM]
    F -.-> A
    A & U --> T[Shelf<br/>app under test]
```

1. **Retriever** collects the requirement sections the story names (exact match on id), the API reference, and the 3 other sections closest to the story by vector search, which brings in related requirements the story does not name.
2. **Planner** turns the story and those documents into test specs. A coverage check sends it back once if any requirement has no test.
3. **API tester** and **UI tester** run the specs with httpx and a real Chromium browser. If a test is broken (not failed), the **repair agent** may fix it, but code rejects any repair that changes a request or an expected value.
4. **Reporter** writes the wording of a bug report for each failed test.

The agents are nodes in a [LangGraph](https://github.com/langchain-ai/langgraph) state graph (`src/verity/agents/graph.py`).

**The model writes, code decides.** Models write test specs and bug report text. Code validates every spec, runs it, decides pass or fail, and decides which results become bug reports. A model cannot invent a bug, hide a failure, or run code on the machine: specs are data with a fixed set of actions, and requests can only go to the target app.

## Quick start

Needs Docker and [Ollama](https://ollama.com). Everything else runs in containers.

```bash
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
python scripts/bootstrap.py                                  # build, start Postgres + Shelf, migrate, index
docker compose --profile full run --rm api verity stories
docker compose --profile full run --rm api verity run SHELF-3   # plan, test and report on "Borrow a book"
docker compose --profile full up -d api                      # REST API at http://127.0.0.1:8000/docs
```

For development on the host instead, `uv sync` and run the same commands as `uv run verity ...`.

To use a hosted model, set `VERITY_LLM_PROVIDER` to `gemini`, `openai` or `anthropic` and the matching `VERITY_*_API_KEY` in `.env` (see `.env.example`). Nothing needs a key by default.

Shelf runs at http://127.0.0.1:8001. Switch its bugs with `SHELF_BUGS=all`, `none` or a list such as `BUG-1,BUG-4` before `docker compose up -d shelf`.

## REST API

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/stories` | User stories |
| POST | `/requirements/index` | Re-index the requirement documents |
| POST | `/runs` | Start a run for a story (202, runs in the background) |
| GET | `/runs/{id}` | Tests, results, bug reports and the agents' trace |
| POST | `/test-cases/{id}/review` | Approve or reject a test for the regression suite |
| GET | `/reports/requirements` | Pass, fail and open bugs per requirement |
| GET | `/exports/postman` | Approved API tests as a Postman collection |
| GET | `/exports/pytest` | Approved tests as a pytest file |
| GET | `/exports/test-cases.csv` | All tests as manual test cases |
| GET | `/exports/bugs.csv` | Bug reports in Jira's CSV import format |

## Evaluation

```bash
docker compose --profile full run --rm -e VERITY_RECORD_DIR=eval/recordings api \
  verity eval --shelf-database-url postgresql+psycopg://verity:verity@postgres:5432/shelf_test
```

runs every story against Shelf with all bugs on, then with none, and scores the
bug reports against `eval/ground_truth.json`:

- **Planted bugs found**: requirements with a planted bug that got a bug report (out of 8).
- **False reports on the buggy build**: bug reports against requirements that have no planted bug.
- **False reports on the fixed build**: any bug report at all.

The answer key itself is tested: `tests/shelf/test_requirements.py` proves that each planted bug breaks exactly one requirement and that the fixed build meets all ten.

**Results with a real model: not measured yet.** The tests use a scripted model, which checks the workflow and the safety rules, not a model's skill. Run the command above with your model and the report is saved to `eval/results/`.

## Design decisions

Recorded in [docs/adr](docs/adr/README.md). The main ones:

- Agents write declarative test specs, never code ([ADR 0001](docs/adr/0001-specs-not-code.md)).
- Code decides outcomes and bugs; the model only writes prose ([ADR 0002](docs/adr/0002-code-decides.md)).
- A repair may add steps but never change a request or an expected value ([ADR 0005](docs/adr/0005-repair-guard.md)).
- Hybrid retrieval in pgvector instead of a separate vector database ([ADR 0004](docs/adr/0004-hybrid-retrieval-pgvector.md)).
- Measured against planted bugs, not judged by eye ([ADR 0006](docs/adr/0006-planted-bugs.md)).

## Testing and quality

- 56 tests: unit, integration against real PostgreSQL, browser tests in Chromium, the exported pytest suite and the Postman collection run in Newman against both builds.
- 92% line and branch coverage; CI fails below 85%.
- Ruff lint and format, mypy in strict mode on code and tests.
- CI also builds the Docker image and smoke-tests the Compose stack.

## Limitations

- Bug-finding with a real model is not measured yet (see Evaluation).
- Shelf is small and its bugs were planted by the same person who wrote the requirements. Results will not transfer to real applications as they are.
- UI tests support five actions (open, type, click, check text, check text absent). Anything richer needs new actions in the runner.
- The API has no login. Every port binds to 127.0.0.1, and it is meant for local use only.
- A test's expected values come from the model's reading of the requirements. A misread requirement gives a wrong test; human review before approval is the safeguard.

## Project layout

```
src/shelf/          sample app under test, with switchable planted bugs
src/verity/agents/  LangGraph workflow and prompts
src/verity/llm/     Ollama, OpenAI, Gemini and Claude clients; record and replay
src/verity/rag/     embeddings and pgvector retrieval
src/verity/runners/ test spec format, API runner, Playwright runner
src/verity/api/     REST API
requirements/shelf/ requirements, API reference and user stories (what the agents read)
eval/               answer key for the evaluation
```

See [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) for a guided tour and interview questions, and [docs/TEST_PROCESS.md](docs/TEST_PROCESS.md) for how Verity maps to the software testing life cycle.
