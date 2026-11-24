"""Turn a model reply into a validated Pydantic object, or fail clearly."""

from pydantic import BaseModel, ValidationError

from verity.llm.base import LLMClient, LLMError, Message


class StructuredOutputError(LLMError):
    """The model's reply still did not match the schema after the retry."""


def ask[T: BaseModel](
    client: LLMClient, messages: list[Message], model: type[T], retries: int = 1
) -> T:
    """Ask for JSON matching `model`. On invalid output, retry with the error shown.

    Models often fix their own mistake when told exactly what was wrong, so one
    retry with the validation error is cheap and usually enough. After that the
    caller gets an exception instead of a guess.
    """
    schema = model.model_json_schema()
    conversation = list(messages)
    for attempt in range(retries + 1):
        reply = client.complete_json(conversation, schema)
        try:
            return model.model_validate_json(reply)
        except ValidationError as exc:
            if attempt == retries:
                raise StructuredOutputError(
                    f"reply did not match {model.__name__} after {retries + 1} attempts: "
                    f"{exc.error_count()} errors"
                ) from exc
            conversation += [
                Message(role="assistant", content=reply),
                Message(
                    role="user",
                    content="That reply was invalid. Fix these errors and reply with JSON only:\n"
                    + exc.json(include_url=False),
                ),
            ]
    raise AssertionError("unreachable")
