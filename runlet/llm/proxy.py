"""Thin LLM proxy wrapping an Instructor-patched OpenAI client."""

from __future__ import annotations

import os
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProxy:
    """
    Thin wrapper around an Instructor-patched OpenAI client.

    Steps access it via ``context.llm``. Requires the ``[llm]`` extra::

        pip install runlet[llm]

    Example usage in a step::

        class Sentiment(BaseModel):
            label: str
            score: float

        result: Sentiment = context.llm.complete(
            messages=[{"role": "user", "content": text}],
            response_model=Sentiment,
        )
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self._client = self._build_client(api_key, base_url)

    @staticmethod
    def _build_client(api_key: str, base_url: str | None) -> Any:
        try:
            import instructor
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "The 'llm' extra is required to use LLM capabilities. "
                "Install it with: pip install runlet[llm]"
            ) from exc
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return instructor.from_openai(OpenAI(**kwargs))

    def complete(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        model: str | None = None,
        **kwargs: Any,
    ) -> T:
        """
        Call the LLM and parse the structured response into *response_model*.

        Parameters
        ----------
        messages:
            OpenAI-format message list.
        response_model:
            A Pydantic BaseModel class; Instructor enforces structured output.
        model:
            Override the default model for this call only.
        **kwargs:
            Forwarded to the underlying Instructor call (temperature, max_tokens, etc.).
        """
        return self._client.chat.completions.create(  # type: ignore[no-any-return]
            model=model or self._model,
            messages=messages,
            response_model=response_model,
            **kwargs,
        )

    @classmethod
    def from_config(cls, config: Any) -> LLMProxy:
        """Build an LLMProxy from an LLMConfig, resolving the API key from the environment."""
        api_key = os.environ.get(config.api_key_env, "")
        if not api_key:
            raise RuntimeError(
                f"LLM API key env var '{config.api_key_env}' is not set or is empty. "
                f"Export it before running the pipeline: export {config.api_key_env}=<key>"
            )
        return cls(model=config.model, api_key=api_key, base_url=config.base_url)
