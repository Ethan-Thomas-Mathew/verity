# 0007: LLM providers over plain HTTP, local by default, with record and replay

## Decision
- One interface, `complete_json(messages, schema)`, implemented for Ollama, OpenAI, Gemini and Claude with httpx. Each uses its provider's structured-output feature: Ollama `format`, OpenAI `json_schema`, Gemini `responseJsonSchema`, Claude a forced tool call.
- Ollama is the default, so nothing needs a key or a paid account.
- Replies are always validated with Pydantic. One retry shows the model its validation errors; after that the run fails instead of guessing.
- `VERITY_RECORD_DIR` saves every reply under a hash of its exact request; `VERITY_LLM_PROVIDER=replay` plays them back. A changed prompt is a cache miss, never a stale answer.

## Options considered
Vendor SDKs or LangChain model wrappers. Both hide the request, add dependencies, and change often. Each provider here is about thirty lines and is tested against the request shape it must send.

## Trade-off
- Hosted providers are tested with mocked HTTP only; there is no key in CI.
- Model names change. Defaults are in `config.py` and can be overridden with `VERITY_LLM_MODEL`.
