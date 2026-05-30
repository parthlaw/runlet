"""LLM configuration parsed from the 'llm' block in pipeline.json."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMConfig:
    """
    Immutable LLM configuration sourced from pipeline.json.

    Attributes
    ----------
    model:
        Default model string, e.g. ``"gpt-4o-mini"``.
    api_key_env:
        Name of the environment variable that holds the API key.
    base_url:
        Optional custom base URL for OpenAI-compatible endpoints.
    """

    model: str
    api_key_env: str
    base_url: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMConfig:
        for key in ("model", "api_key_env"):
            if key not in data:
                raise ValueError(
                    f"LLM config missing required field '{key}': {data!r}"
                )
        return cls(
            model=data["model"],
            api_key_env=data["api_key_env"],
            base_url=data.get("base_url"),
        )
