"""Runner-level data models."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any


@dataclass(frozen=True)
class RunnerConfig:
    """Runtime configuration for the sequential runner."""

    resume: bool = False
    log_level: str = "INFO"
    max_concurrent_steps: int = 1
    metastore_raw: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunnerConfig:
        return cls(
            resume=data.get("resume", False),
            log_level=data.get("log_level", "INFO"),
            max_concurrent_steps=int(data.get("max_concurrent_steps", 1)),
            metastore_raw=data.get("metastore") or None,
        )


@dataclass(frozen=True)
class RunResult:
    """Immutable summary returned by :meth:`SequentialRunner.run`."""

    run_id: str
    success: bool
    steps_executed: list[str]
    steps_skipped: list[str]
    failed_step: str | None
    error: str | None
    state_uri: str
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)
    status: str = ""  # "SUCCESS", "FAILED", "CANCELLED"
    outputs: dict[str, Any] = dataclass_field(default_factory=dict)
