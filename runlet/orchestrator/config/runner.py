"""Runner-level data models."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from runlet.metastore import MetastoreConfig, build_metastore_config


@dataclass(frozen=True)
class ExecutorConfig:
    """
    Configuration for executor selection.

    Attributes
    ----------
    type:
        ``"sequential"`` or ``"threaded"``.
    max_workers:
        Maximum number of concurrent threads. Only meaningful for
        ``type="threaded"``; ignored by ``SequentialExecutor``.
    """

    type: str
    max_workers: int = 1

    def __post_init__(self) -> None:
        if self.type not in ("sequential", "threaded"):
            raise ValueError(
                f"ExecutorConfig.type must be 'sequential' or 'threaded', got {self.type!r}."
            )
        if self.max_workers < 1:
            raise ValueError(
                f"ExecutorConfig.max_workers must be >= 1, got {self.max_workers}."
            )


_DEFAULT_EXECUTOR = ExecutorConfig(type="sequential")


@dataclass(frozen=True)
class RunnerConfig:
    """Runtime configuration for the runner."""

    resume: bool = False
    log_level: str = "INFO"
    executor: ExecutorConfig = dataclass_field(default_factory=lambda: _DEFAULT_EXECUTOR)
    metastore: MetastoreConfig | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunnerConfig:
        executor = _parse_executor(data)
        return cls(
            resume=data.get("resume", False),
            log_level=data.get("log_level", "INFO"),
            executor=executor,
            metastore=build_metastore_config(data.get("metastore") or None),
        )


def _parse_executor(data: dict[str, Any]) -> ExecutorConfig:
    """Resolve ExecutorConfig from a runner config dict."""
    if "executor" in data:
        block = data["executor"]
        return ExecutorConfig(
            type=block.get("type", "sequential"),
            max_workers=int(block.get("max_workers", 1)),
        )
    return _DEFAULT_EXECUTOR


@dataclass(frozen=True)
class RunResult:
    """Immutable summary returned by :meth:`WorkflowRunner.run`."""

    run_id: str
    success: bool
    steps_executed: list[str]
    steps_skipped: list[str]
    failed_step: str | None
    error: str | None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)
    status: str = ""  # "SUCCESS", "FAILED", "CANCELLED"
    outputs: dict[str, Any] = dataclass_field(default_factory=dict)
