"""User stories, stored in a Jira-like JSON file next to the requirements."""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from verity.runners.specs import RequirementId


class Story(BaseModel):
    key: str = Field(pattern=r"^[A-Z]+-\d+$")
    summary: str
    description: str
    requirements: list[RequirementId] = Field(min_length=1)


def load_stories(directory: Path) -> dict[str, Story]:
    raw = json.loads((directory / "stories.json").read_text())
    stories = [Story.model_validate(item) for item in raw]
    return {story.key: story for story in stories}
