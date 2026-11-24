"""Executes UI test specs in a real Chromium browser with Playwright."""

from types import TracebackType
from typing import Any, Self

import httpx
from playwright.sync_api import Browser, Page, Playwright, expect, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from verity.runners.api_runner import ApiRunner, ExpectationFailed, Result, SpecError, substitute
from verity.runners.specs import UiAction, UiTest

STEP_TIMEOUT_MS = 3000


class UiRunner:
    """Use as a context manager so the browser is always closed."""

    def __init__(self, api: ApiRunner, base_url: str, executable: str | None = None) -> None:
        self._api, self._base, self._executable = api, base_url.rstrip("/"), executable
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def __enter__(self) -> Self:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(executable_path=self._executable)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def run(self, test: UiTest) -> Result:
        if self._browser is None:
            raise RuntimeError("UiRunner must be used inside a with block")
        log: list[str] = []
        context = self._browser.new_context()
        page = context.new_page()
        page.set_default_timeout(STEP_TIMEOUT_MS)
        try:
            self._api.reset()
            variables = self._api.run_steps(test.setup, {}, log)
            for number, action in enumerate(test.steps, start=1):
                self._do(page, action, variables)
                log.append(f"{number}. {action.action} {action.target} {action.value}".rstrip())
        except ExpectationFailed as exc:
            return Result("failed", str(exc), log)
        except AssertionError as exc:
            # Playwright's expect() raises AssertionError when the page is wrong.
            return Result("failed", _first_line(exc), log)
        except PlaywrightTimeout as exc:
            # A field or button the spec names does not exist. That is a broken
            # spec, not evidence of a bug, so it is not reported as a failure.
            return Result("error", f"element not found: {_first_line(exc)}", log)
        except (SpecError, PlaywrightError, httpx.HTTPError) as exc:
            return Result("error", _first_line(exc), log)
        finally:
            context.close()
        return Result("passed", "all expectations met", log)

    def _do(self, page: Page, action: UiAction, variables: dict[str, Any]) -> None:
        target = str(substitute(action.target, variables))
        value = str(substitute(action.value, variables))
        match action.action:
            case "goto":
                if not target.startswith("/") or "://" in target:
                    raise SpecError("goto target must be a path on the target app")
                page.goto(f"{self._base}{target}")
            case "fill":
                page.get_by_label(target, exact=True).fill(value)
            case "click":
                page.get_by_role("button", name=target).click()
                # A click may submit a form. Wait for the next page, or a following
                # expect_no_text could pass by checking the old page.
                page.wait_for_load_state("networkidle")
            case "expect_text":
                expect(page.locator("body")).to_contain_text(value, timeout=STEP_TIMEOUT_MS)
            case "expect_no_text":
                expect(page.locator("body")).not_to_contain_text(value, timeout=STEP_TIMEOUT_MS)


def _first_line(exc: BaseException) -> str:
    return (str(exc).strip().splitlines() or [type(exc).__name__])[0][:300]
