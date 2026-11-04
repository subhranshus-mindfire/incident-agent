"""Loads prompt text from YAML files in this package, so wording can change without touching code."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROMPTS_DIR = Path(__file__).parent


@lru_cache
def load_prompt(name: str) -> str:
    """Returns the `system` text of app/prompts/<name>.yaml. Raises if the file or key is missing."""
    data: Any = yaml.safe_load((PROMPTS_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    text = data.get("system") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"prompts/{name}.yaml must define a non-empty 'system' text")
    return text.strip()
