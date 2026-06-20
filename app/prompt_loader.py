"""Load and render bot prompt templates."""

from functools import lru_cache
from pathlib import Path
from typing import Any


PROMPT_ROOT = Path(__file__).resolve().parent / "prompts"


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@lru_cache(maxsize=32)
def load_prompt(profile: str, name: str) -> str:
    prompt_path = PROMPT_ROOT / profile / f"{name}.txt"
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def render_prompt(profile: str, name: str, **variables: Any) -> str:
    template = load_prompt(profile, name)
    safe_variables = _SafeFormatDict({
        key: "" if value is None else str(value)
        for key, value in variables.items()
    })
    return template.format_map(safe_variables)
