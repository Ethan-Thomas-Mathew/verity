# Walkthrough

A guided tour, written so you can explain every part in your own words.

## Part 1: The idea in one minute

QA engineers read requirements, write test cases, run them, and report bugs. Verity gives each of those jobs to an agent:

| Job | Who does it | Uses a model? |
| --- | --- | --- |
| Find the relevant requirements | Retriever | Only for embeddings |
| Write the tests | Planner | Yes |
| Check every requirement has a test | Coverage check | No |
| Run API tests | API tester | No (repair only, if a test is broken) |
| Run UI tests | UI tester | No |
| Write bug reports | Reporter | Yes, for the wording only |

The rule behind it: **the model writes, code decides.** A model reads text and writes test specs and prose. Plain Python decides whether a test passed and whether a bug report is created.

## Part 2: Follow one run

`uv run verity run SHELF-3` (story: "Borrow a book", requirements REQ-LOAN-1, REQ-LOAN-2, REQ-LOAN-3, REQ-UI-1).

1. **`runs.py: create_run`** saves a row in `runs` with status `queued`.
2. **Retriever** (`rag/store.py: retrieve`): fetches the four named requirement sections by id and the API reference (which tells the planner which endpoints exist), then embeds the story and adds the 3 nearest other sections by pgvector's cosine distance. That is how a related requirement the story does not name still reaches the planner.
3. **Planner** (`agents/graph.py: planner`): sends the documents and the story to the model and asks for a `TestPlan` (`runners/specs.py`). `llm/structured.py: ask` validates the JSON. If it is invalid, the model gets the errors and one more try. Tests for requirements outside the story are dropped.
4. **Coverage**: if, say, REQ-LOAN-3 has no test, the graph goes back to the planner once with "you missed REQ-LOAN-3".
5. **API tester**: for each test, `ApiRunner.run` resets Shelf, sends each request, checks status and fields, and saves values like the new member's id for later steps. Result: `passed`, `failed` or `error`.
6. **Repair**: an `error` test goes to the repair agent once. Code rejects the repair if it changed any request or expected value (`_protected` and `_keeps_all`).
7. **UI tester**: Playwright opens Chromium, fills the borrow form, clicks Borrow, and checks the page text.
8. **Reporter**: for each `failed` test, the model writes a summary and severity. Steps to reproduce come from `manual_steps`, written by code.
9. **`runs.py: _save`** stores tests, bug reports and the trace. `GET /runs/{id}` shows them.

## Part 3: What each folder is for

- `src/shelf/`: the app being tested. `bugs.py` lists the 8 planted bugs; `service.py` has the rules, each with an `if self._bugs.on("BUG-n")` switch.
- `src/verity/llm/`: one class per provider, all with the same `complete_json` method. `replay.py` records and replays replies.
- `src/verity/rag/`: embeddings and retrieval.
- `src/verity/runners/`: the spec format and the two runners.
- `src/verity/agents/`: the LangGraph graph and the prompts.
- `src/verity/api/`: the REST API. `src/verity/cli.py`: the command line.
- `src/verity/evaluation.py`: scoring against the planted bugs.
- `migrations/`: Alembic database migrations.
- `tests/`: 56 tests. `tests/shelf/test_requirements.py` proves the answer key.

## Part 4: Interview questions

**1. Why not let the model write Playwright or pytest code directly?**
Running model-written code lets a wrong or manipulated model do anything on the machine. Specs are data: Pydantic validates them, paths must be relative, and the UI has five allowed actions. Code is still produced, by Verity's exporter, after a person approves the tests.

**2. How do you know it finds bugs, and is not just producing plausible text?**
Shelf has 8 planted bugs, each switchable, and a tested answer key. The evaluation runs every story with all bugs on and with none, then counts bugs found and false reports. I have not run it with a real model yet, and the README says so.

**3. What is RAG doing here?**
The planner needs the exact rules ("at most 3 active loans", "409 with message loan limit reached"). Retrieval gives it only what this story needs: the named requirements by id, the API reference, and the closest other sections by vector similarity, which catches related rules the story does not name. Everything is stored in PostgreSQL with pgvector, so there is no separate vector database to run.

**4. What stops the model from hiding a bug?**
Three things. Pass or fail is decided by code comparing responses with expected values. Only failed tests become bug reports, whatever the reporter writes. A repair that changes an expected value is rejected; there is a test where the "repair" quietly changes the expected due date, and it is refused.

**5. Why LangGraph instead of a simple loop?**
Five roles and a loop back to the planner. The graph declares that flow in one place, and the state between agents is typed. The model does not choose the order, because the order is known.

**6. Tell me about a bug you found while building it.**
A test failed about one run in four with "member not found" right after creating the member. FastAPI ran the database commit after sending the response, so a fast client could use an id before it was committed. The fix was `Depends(..., scope="function")`, and a regression test creates 100 members and uses each at once. It fails reliably without the fix.

**7. What is the biggest limitation?**
Bug-finding with a real model is not measured yet, and Shelf is small with bugs I planted myself. Next steps: run the evaluation with a local model and a hosted model, publish the numbers as they are, and record the replies so CI can replay them.

## Part 5: Honest notes

- Built with AI-assisted development (Claude Code). Be ready to explain each part above in your own words.
- Hosted providers (Gemini, OpenAI, Claude) are tested against mocked HTTP responses, not live APIs.
