"""
RunMetastore — abstract interface for pipeline lifecycle metadata.

The metastore tracks run and step status for querying purposes.
It is additive: the JSON run-state file continues to drive resume logic;
the metastore is for history and cross-run queries.
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar


class MetastoreType(str, Enum):
    NOOP = "noop"
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    COCKROACHDB = "cockroachdb"


class MetastoreConfig:
    """Marker base for all metastore configuration dataclasses."""

    TYPE: ClassVar[MetastoreType]


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    pipeline_name: str
    status: str
    error: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    outputs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepRecord:
    run_id: str
    step_name: str
    status: str
    attempt: int
    duration_seconds: float | None
    error: str | None
    output: dict[str, Any]
    recorded_at: datetime.datetime


class RunMetastore(ABC):
    """
    Abstract interface for persisting pipeline lifecycle metadata.

    All methods are synchronous. Implementations must be thread-safe at the
    method level. Errors should raise MetastoreError or a subclass.
    """

    @abstractmethod
    def init_schema(self) -> None:
        """
        Create tables and indexes if they do not already exist.
        Uses CREATE TABLE IF NOT EXISTS — safe to call on every startup.
        Not a migration tool; use Alembic or equivalent for schema evolution.
        """

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def record_run_started(self, run_id: str, pipeline_name: str) -> None:
        """UPSERT a run row with status='running'. Safe to call on resume."""

    @abstractmethod
    def record_run_success(self, run_id: str, outputs: dict[str, Any] | None = None) -> None:
        """Update run status to 'success' and persist optional step outputs."""

    @abstractmethod
    def record_run_failed(self, run_id: str, error: str) -> None:
        """Update run status to 'failed' and persist the error message."""

    @abstractmethod
    def record_run_cancelled(self, run_id: str) -> None:
        """Update run status to 'cancelled'."""

    # ------------------------------------------------------------------
    # Step lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def record_step_running(self, run_id: str, step_name: str, attempt: int) -> None:
        """
        Upsert a step row with status='running'.
        Each (run_id, step_name, attempt) is a distinct row so the full
        retry history is preserved.
        """

    @abstractmethod
    def record_step_success(
        self,
        run_id: str,
        step_name: str,
        attempt: int,
        duration_seconds: float,
        output: dict[str, Any],
    ) -> None:
        """Upsert step row for (run_id, step_name, attempt) with status='success'."""

    @abstractmethod
    def record_step_failed(
        self,
        run_id: str,
        step_name: str,
        attempt: int,
        duration_seconds: float,
        error: str,
    ) -> None:
        """Upsert step row for (run_id, step_name, attempt) with status='failed'."""

    @abstractmethod
    def record_step_skipped(self, run_id: str, step_name: str) -> None:
        """Insert a step row with status='skipped', attempt=0."""

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @abstractmethod
    def get_run(self, run_id: str) -> RunRecord | None:
        """Return the run record, or None if not found."""

    @abstractmethod
    def list_runs(
        self,
        pipeline_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RunRecord]:
        """List runs ordered by created_at DESC.

        Optionally filter by pipeline_name and/or status.
        """

    @abstractmethod
    def list_steps(self, run_id: str) -> list[StepRecord]:
        """List all step rows for a run, ordered by recorded_at ASC then id ASC."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def close(self) -> None:
        """Close the underlying connection. Safe to call multiple times."""


class MetastoreError(RuntimeError):
    """Base class for metastore errors."""


class MetastoreConnectionError(MetastoreError):
    """Raised when the metastore cannot connect to the backend."""


class MetastoreSchemaError(MetastoreError):
    """Raised when init_schema() fails or the schema is incompatible."""
