"""PostgresMetastore — psycopg3-backed lifecycle metastore for PostgreSQL."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from runlet.metastore.metastore import (
    MetastoreConnectionError,
    MetastoreError,
    MetastoreSchemaError,
    RunMetastore,
    RunRecord,
    StepRecord,
)

logger = logging.getLogger(__name__)

# PostgreSQL DDL — uses BIGSERIAL for the step surrogate key.
# For CockroachDB see stores/cockroachdb.py which overrides _SCHEMA_SQL.
_PG_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          TEXT        NOT NULL,
    pipeline_name   TEXT        NOT NULL,
    status          TEXT        NOT NULL,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pipeline_runs_pkey PRIMARY KEY (run_id),
    CONSTRAINT pipeline_runs_status_check
        CHECK (status IN ('running', 'success', 'failed', 'cancelled'))
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_pipeline_name
    ON pipeline_runs (pipeline_name);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
    ON pipeline_runs (status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_created_at
    ON pipeline_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS pipeline_steps (
    id               BIGSERIAL,
    run_id           TEXT             NOT NULL,
    step_name        TEXT             NOT NULL,
    status           TEXT             NOT NULL,
    attempt          INT              NOT NULL DEFAULT 1,
    duration_seconds DOUBLE PRECISION,
    error            TEXT,
    paths            JSONB            NOT NULL DEFAULT '{}',
    schema_info      JSONB            NOT NULL DEFAULT '{}',
    recorded_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT pipeline_steps_pkey          PRIMARY KEY (id),
    CONSTRAINT pipeline_steps_run_step_att  UNIQUE (run_id, step_name, attempt),
    CONSTRAINT pipeline_steps_status_check
        CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    CONSTRAINT pipeline_steps_run_fk
        FOREIGN KEY (run_id) REFERENCES pipeline_runs (run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pipeline_steps_run_id
    ON pipeline_steps (run_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_steps_recorded_at
    ON pipeline_steps (recorded_at DESC);
"""


@dataclass(frozen=True)
class PostgresConfig:
    """
    Connection settings for PostgresMetastore.

    ``dsn`` is a libpq connection string or URL, e.g.:
        ``postgresql://user:pw@localhost:5432/pipeline_metastore``
    """

    dsn: str
    connect_timeout: int = 10

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PostgresConfig:
        if "dsn" not in data:
            raise ValueError("PostgresConfig requires a 'dsn' key")
        return cls(
            dsn=data["dsn"],
            connect_timeout=int(data.get("connect_timeout", 10)),
        )


class PostgresMetastore(RunMetastore):
    """
    Synchronous psycopg3-backed metastore.

    Holds a single connection for the lifetime of the instance (v1 — no
    pooling). A ``threading.Lock`` serialises all operations because psycopg3
    connections are not thread-safe and ``SequentialRunner`` dispatches steps
    via a thread pool.
    """

    _SCHEMA_SQL: str = _PG_SCHEMA_SQL

    def __init__(self, config: PostgresConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._conn: Any = None
        self._connect()

    def _connect(self) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row

            self._conn = psycopg.connect(
                self._config.dsn,
                connect_timeout=self._config.connect_timeout,
                row_factory=dict_row,
                autocommit=False,
            )
        except Exception as exc:
            raise MetastoreConnectionError(
                f"Cannot connect to metastore DB: {exc}"
            ) from exc

    @classmethod
    def from_config(cls, config: PostgresConfig) -> PostgresMetastore:
        return cls(config)

    def init_schema(self) -> None:
        with self._lock:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(self._SCHEMA_SQL)
                self._conn.commit()
            except Exception as exc:
                self._conn.rollback()
                raise MetastoreSchemaError(f"init_schema() failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def record_run_started(self, run_id: str, pipeline_name: str) -> None:
        self._execute(
            """
            INSERT INTO pipeline_runs (run_id, pipeline_name, status, created_at, updated_at)
            VALUES (%s, %s, 'running', now(), now())
            ON CONFLICT (run_id) DO UPDATE
              SET status = 'running',
                  updated_at = now()
            """,
            (run_id, pipeline_name),
        )

    def record_run_success(self, run_id: str) -> None:
        self._execute(
            """
            UPDATE pipeline_runs
               SET status = 'success', updated_at = now(), error = NULL
             WHERE run_id = %s
            """,
            (run_id,),
        )

    def record_run_failed(self, run_id: str, error: str) -> None:
        self._execute(
            """
            UPDATE pipeline_runs
               SET status = 'failed', updated_at = now(), error = %s
             WHERE run_id = %s
            """,
            (error, run_id),
        )

    def record_run_cancelled(self, run_id: str) -> None:
        self._execute(
            """
            UPDATE pipeline_runs
               SET status = 'cancelled', updated_at = now()
             WHERE run_id = %s
            """,
            (run_id,),
        )

    # ------------------------------------------------------------------
    # Step lifecycle — all use UPSERT so pre-execution failures
    # (e.g. step load error before mark_step_running is called) are safe.
    # ------------------------------------------------------------------

    def record_step_running(self, run_id: str, step_name: str, attempt: int) -> None:
        self._execute(
            """
            INSERT INTO pipeline_steps (run_id, step_name, status, attempt, recorded_at)
            VALUES (%s, %s, 'running', %s, now())
            ON CONFLICT (run_id, step_name, attempt) DO UPDATE
              SET status = 'running', recorded_at = now()
            """,
            (run_id, step_name, attempt),
        )

    def record_step_success(
        self,
        run_id: str,
        step_name: str,
        attempt: int,
        duration_seconds: float,
        paths: dict[str, Any],
        schema_info: dict[str, Any],
    ) -> None:
        from psycopg.types.json import Jsonb

        self._execute(
            """
            INSERT INTO pipeline_steps
                (run_id, step_name, status, attempt, duration_seconds, paths, schema_info, recorded_at)
            VALUES (%s, %s, 'success', %s, %s, %s, %s, now())
            ON CONFLICT (run_id, step_name, attempt) DO UPDATE
              SET status = 'success',
                  duration_seconds = EXCLUDED.duration_seconds,
                  paths = EXCLUDED.paths,
                  schema_info = EXCLUDED.schema_info
            """,
            (run_id, step_name, attempt, duration_seconds, Jsonb(paths), Jsonb(schema_info)),
        )

    def record_step_failed(
        self,
        run_id: str,
        step_name: str,
        attempt: int,
        duration_seconds: float,
        error: str,
    ) -> None:
        self._execute(
            """
            INSERT INTO pipeline_steps
                (run_id, step_name, status, attempt, duration_seconds, error, recorded_at)
            VALUES (%s, %s, 'failed', %s, %s, %s, now())
            ON CONFLICT (run_id, step_name, attempt) DO UPDATE
              SET status = 'failed',
                  duration_seconds = EXCLUDED.duration_seconds,
                  error = EXCLUDED.error
            """,
            (run_id, step_name, attempt, duration_seconds, error),
        )

    def record_step_skipped(self, run_id: str, step_name: str) -> None:
        self._execute(
            """
            INSERT INTO pipeline_steps (run_id, step_name, status, attempt, recorded_at)
            VALUES (%s, %s, 'skipped', 0, now())
            ON CONFLICT (run_id, step_name, attempt) DO NOTHING
            """,
            (run_id, step_name),
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            with self._conn.cursor() as cur:
                cur.execute("SELECT * FROM pipeline_runs WHERE run_id = %s", (run_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return _row_to_run_record(row)

    def list_runs(
        self,
        pipeline_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RunRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if pipeline_name is not None:
            clauses.append("pipeline_name = %s")
            params.append(pipeline_name)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        with self._lock:
            with self._conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM pipeline_runs {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    params,
                )
                rows = cur.fetchall()
        return [_row_to_run_record(r) for r in rows]

    def list_steps(self, run_id: str) -> list[StepRecord]:
        with self._lock:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM pipeline_steps WHERE run_id = %s ORDER BY recorded_at ASC, id ASC",
                    (run_id,),
                )
                rows = cur.fetchall()
        return [_row_to_step_record(r) for r in rows]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                finally:
                    self._conn = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._lock:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(sql, params)
                self._conn.commit()
            except Exception as exc:
                self._conn.rollback()
                raise MetastoreError(f"Metastore write failed: {exc}") from exc


def _row_to_run_record(row: dict[str, Any]) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        pipeline_name=row["pipeline_name"],
        status=row["status"],
        error=row.get("error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_step_record(row: dict[str, Any]) -> StepRecord:
    return StepRecord(
        run_id=row["run_id"],
        step_name=row["step_name"],
        status=row["status"],
        attempt=row["attempt"],
        duration_seconds=row.get("duration_seconds"),
        error=row.get("error"),
        paths=row.get("paths") or {},
        schema_info=row.get("schema_info") or {},
        recorded_at=row["recorded_at"],
    )
