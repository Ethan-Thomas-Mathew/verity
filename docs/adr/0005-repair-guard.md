# 0005: Repairs may add steps, never change requests or expectations

## Decision
When a test errors (for example it uses `{{member}}` before saving it), the repair agent gets one chance to fix it. Code then compares the original and the repair: every original request and expected value must still be there, in order. New steps may be added. Anything else is rejected and the test stays an error.

## Why
"Make this test pass" and "make this test run" are different requests, and a model can confuse them. The easiest way to make a failing test pass is to change what it expects. `test_repair_that_changes_an_expectation_is_refused` checks that a repair which changes the expected due date to the buggy value is refused, so BUG-4 is not hidden.

## Trade-off
- Some legitimate repairs are refused, such as fixing a wrong request path. Those stay errors for a person to fix.
- A repaired test is marked `repaired: true` in its spec, so a reviewer knows it was changed.
