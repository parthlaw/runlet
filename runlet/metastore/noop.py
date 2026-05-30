"""NoopMetastore — null-object implementation. Used when no metastore is configured."""

from __future__ import annotations

from typing import Any

from runlet.metastore.metastore import RunMetastore, RunRecord, StepRecord


class NoopMetastore(RunMetastore):
    """All write methods are silent no-ops; all queries return empty results."""

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> NoopMetastore:
        return cls()

    def init_schema(self) -> None:
        pass

    def record_run_started(self, run_id: str, pipeline_name: str) -> None:
        pass

    def record_run_success(self, run_id: str) -> None:
        pass

    def record_run_failed(self, run_id: str, error: str) -> None:
        pass

    def record_run_cancelled(self, run_id: str) -> None:
        pass

    def record_step_running(self, run_id: str, step_name: str, attempt: int) -> None:
        pass

    def record_step_success(
        self,
        run_id: str,
        step_name: str,
        attempt: int,
        duration_seconds: float,
        paths: dict[str, Any],
        schema_info: dict[str, Any],
    ) -> None:
        pass

    def record_step_failed(
        self,
        run_id: str,
        step_name: str,
        attempt: int,
        duration_seconds: float,
        error: str,
    ) -> None:
        pass

    def record_step_skipped(self, run_id: str, step_name: str) -> None:
        pass

    def get_run(self, run_id: str) -> RunRecord | None:
        return None

    def list_runs(
        self,
        pipeline_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RunRecord]:
        return []

    def list_steps(self, run_id: str) -> list[StepRecord]:
        return []

    def close(self) -> None:
        pass
