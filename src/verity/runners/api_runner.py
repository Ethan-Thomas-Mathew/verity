"""Executes API test specs against the target app with httpx."""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from verity.runners.specs import ApiStep, ApiTest, Scalar

Outcome = Literal["passed", "failed", "error"]
VARIABLE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
MISSING = object()


class SpecError(Exception):
    """The spec itself is broken (for example it uses a variable it never saved)."""


class ExpectationFailed(Exception):
    """The app answered, but not the way the requirement says it should."""


@dataclass
class Result:
    outcome: Outcome
    detail: str
    log: list[str] = field(default_factory=list)


def lookup(data: Any, path: str) -> Any:
    """Follow a dotted path such as "0.title" through JSON. Returns MISSING if absent."""
    current = data
    for part in path.split("."):
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return MISSING
    return current


def substitute(value: Any, variables: dict[str, Any]) -> Any:
    """Replace {{name}} placeholders. A value that is only a placeholder keeps its type."""
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    if not isinstance(value, str):
        return value

    def find(name: str) -> Any:
        if name not in variables:
            raise SpecError(f"variable {{{{{name}}}}} is used before it is saved")
        return variables[name]

    whole = VARIABLE.fullmatch(value.strip())
    if whole:
        return find(whole.group(1))
    return VARIABLE.sub(lambda m: str(find(m.group(1))), value)


def _same(expected: Scalar, actual: Any) -> bool:
    # bool is a subclass of int in Python, so True must not equal 1 here.
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    if isinstance(expected, int | float) and isinstance(actual, int | float):
        return float(expected) == float(actual)
    return bool(expected == actual)


class ApiRunner:
    def __init__(self, http: httpx.Client, base_url: str) -> None:
        self._http, self._base = http, base_url.rstrip("/")

    def reset(self) -> None:
        """Put the target app back to its seed data so tests cannot affect each other."""
        response = self._http.post(f"{self._base}/api/test/reset")
        if response.status_code != 204:
            raise SpecError(f"reset failed with status {response.status_code}")

    def run(self, test: ApiTest) -> Result:
        log: list[str] = []
        try:
            self.reset()
            self.run_steps(test.steps, {}, log)
        except ExpectationFailed as exc:
            return Result("failed", str(exc), log)
        except (SpecError, httpx.HTTPError) as exc:
            return Result("error", str(exc), log)
        return Result("passed", "all expectations met", log)

    def run_steps(
        self, steps: list[ApiStep], variables: dict[str, Any], log: list[str]
    ) -> dict[str, Any]:
        for number, step in enumerate(steps, start=1):
            path = substitute(step.path, variables)
            params = substitute(step.params, variables)
            body = substitute(step.body, variables)
            response = self._http.request(
                step.method, f"{self._base}{path}", params=params, json=body
            )
            log.append(f"{number}. {step.method} {path} -> {response.status_code}")
            self._check(number, step, response)
            if not step.save:
                continue
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise SpecError(f"step {number}: cannot save values from a non-JSON body") from exc
            for name, source in step.save.items():
                value = lookup(data, source)
                if value is MISSING:
                    raise SpecError(f"step {number}: cannot save {name}, no field {source!r}")
                variables[name] = value
        return variables

    @staticmethod
    def _check(number: int, step: ApiStep, response: httpx.Response) -> None:
        where = f"step {number} ({step.method} {step.path})"
        if response.status_code != step.expect.status:
            raise ExpectationFailed(
                f"{where}: expected status {step.expect.status}, got {response.status_code}; "
                f"body {response.text[:200]}"
            )
        if not step.expect.fields and step.expect.length is None:
            return
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ExpectationFailed(f"{where}: expected a JSON body") from exc
        if step.expect.length is not None:
            actual_length = len(data) if isinstance(data, list) else None
            if actual_length != step.expect.length:
                raise ExpectationFailed(
                    f"{where}: expected a list of {step.expect.length}, got {actual_length}"
                )
        for path, expected in step.expect.fields.items():
            actual = lookup(data, path)
            if actual is MISSING:
                raise ExpectationFailed(f"{where}: response has no field {path!r}")
            if not _same(expected, actual):
                raise ExpectationFailed(f"{where}: {path} expected {expected!r}, got {actual!r}")
