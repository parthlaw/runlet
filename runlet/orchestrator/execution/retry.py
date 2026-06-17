"""RetryPolicy — per-step retry configuration and backoff logic."""

from __future__ import annotations

import dataclasses
import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_base: float = 1.0
    backoff_multiplier: float = 2.0
    jitter: float = 0.1
    retry_on: tuple[type[Exception], ...] = (Exception,)

    def should_retry(self, attempt: int, exc: Exception) -> bool:
        if attempt >= self.max_attempts:
            return False
        return isinstance(exc, self.retry_on)

    def wait_before_retry(self, attempt: int) -> None:
        delay = self.backoff_base * (self.backoff_multiplier ** (attempt - 1))
        jitter_amt = delay * self.jitter * random.random()
        time.sleep(delay + jitter_amt)

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> RetryPolicy:
        retry_on: tuple[type[Exception], ...] = (Exception,)
        retry_on_names = cfg.get("retry_on")
        if retry_on_names:
            import builtins
            resolved = tuple(
                getattr(builtins, name)
                for name in retry_on_names
                if isinstance(getattr(builtins, name, None), type)
                and issubclass(getattr(builtins, name), Exception)
            )
            if resolved:
                retry_on = resolved
        return cls(
            max_attempts=int(cfg.get("max_attempts", 1)),
            backoff_base=float(cfg.get("backoff_base", 1.0)),
            backoff_multiplier=float(cfg.get("backoff_multiplier", 2.0)),
            jitter=float(cfg.get("jitter", 0.1)),
            retry_on=retry_on,
        )


DEFAULT_POLICY = RetryPolicy()
