from verity.agents import prompts
from verity.runners.specs import TestPlan


def test_planner_example_is_a_valid_plan() -> None:
    # The worked example teaches the format; if the spec changes, it must still validate.
    example = prompts.PLANNER.split("cart):\n", 1)[1]
    plan = TestPlan.model_validate_json(example)
    assert len(plan.api_tests) == 1 and len(plan.ui_tests) == 1
