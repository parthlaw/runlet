"""SqliteMetastore — stdlib sqlite3-backed lifecycle metastore."""

from __future__ import annotations

import contextlib
import datetime
import json
import logging
import sqlite3
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

_SQLITE_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          TEXT    NOT NULL,
    pipeline_name   TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    error           TEXT,
    outputs         TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
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
    id               INTEGER  PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT     NOT NULL,
    step_name        TEXT     NOT NULL,
    status           TEXT     NOT NULL,
    attempt          INTEGER  NOT NULL DEFAULT 1,
    duration_seconds REAL,
    error            TEXT,
    paths            TEXT     NOT NULL DEFAULT '{}',
    schema_info      TEXT     NOT NULL DEFAULT '{}',
    recorded_at      TEXT     NOT NULL,
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


def _now_iso() -> str:
    return datetime.datetime.now(tz=datetime.UTC).isoformat()


@dataclass(frozen=True)
class SqliteConfig:
    """
    Connection settings for SqliteMetastore.

    ``db_path`` is a file path or ``":memory:"`` for an in-memory database.
    ``timeout`` controls how many seconds SQLite waits on a locked database
    before raising an error (maps to the *timeout* parameter of
    ``sqlite3.connect``).
    """

    db_path: str
    timeout: float = 30.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SqliteConfig:
        if "db_path" not in data:
            raise ValueError("SqliteConfig requires a 'db_path' key")
        return cls(
            db_path=data["db_path"],
            timeout=float(data.get("timeout", 30.0)),
        )


class SqliteMetastore(RunMetastore):
    """
    Synchronous sqlite3-backed metastore.

    Uses a single connection for the lifetime of the instance.
    A ``threading.Lock`` serialises all operations; ``check_same_thread=False``
    on the connection lets the owning thread and worker threads share it safely
    under the lock.

    WAL journal mode is enabled on connect for better concurrent read
    throughput without complicating the single-writer model.

    JSON blobs (outputs, paths, schema_info) are stored as TEXT and
    serialised/deserialised in Python.  Timestamps are stored as ISO 8601
    TEXT and reconstructed as timezone-aware ``datetime.datetime`` objects.
    """

    _SCHEMA_SQL: str = _SQLITE_SCHEMA_SQL

    def __init__(self, config: SqliteConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._connect()

    def _connect(self) -> None:
        try:
            conn = sqlite3.connect(
                self._config.db_path,
                timeout=self._config.timeout,
                check_same_thread=False,
                isolation_level=None,  # manual transaction control via BEGIN/COMMIT
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            self._conn = conn
        except Exception as exc:
            raise MetastoreConnectionError(
                f"Cannot open SQLite metastore at {self._config.db_path!r}: {exc}"
            ) from exc

    @classmethod
    def from_config(cls, config: SqliteConfig | dict[str, Any]) -> SqliteMetastore:
        if isinstance(config, dict):
            config = SqliteConfig.from_dict(config)
        return cls(config)

    def init_schema(self) -> None:
        with self._lock:
            assert self._conn is not None
            try:
                self._conn.executescript(self._SCHEMA_SQL)
            except Exception as exc:
                raise MetastoreSchemaError(f"init_schema() failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def record_run_started(self, run_id: str, pipeline_name: str) -> None:
        now = _now_iso()
        self._execute(
            """
            INSERT INTO pipeline_runs (run_id, pipeline_name, status, created_at, updated_at)
            VALUES (?, ?, 'running', ?, ?)
            ON CONFLICT (run_id) DO UPDATE
              SET status = 'running',
                  updated_at = excluded.updated_at
            """,
            (run_id, pipeline_name, now, now),
        )

    def record_run_success(self, run_id: str, outputs: dict[str, Any] | None = None) -> None:
        self._execute(
            """
            UPDATE pipeline_runs
               SET status = 'success', updated_at = ?, error = NULL,
                   outputs = ?
             WHERE run_id = ?
            """,
            (_now_iso(), json.dumps(outputs or {}), run_id),
        )

    def record_run_failed(self, run_id: str, error: str) -> None:
        self._execute(
            """
            UPDATE pipeline_runs
               SET status = 'failed', updated_at = ?, error = ?
             WHERE run_id = ?
            """,
            (_now_iso(), error, run_id),
        )

    def record_run_cancelled(self, run_id: str) -> None:
        self._execute(
            """
            UPDATE pipeline_runs
               SET status = 'cancelled', updated_at = ?
             WHERE run_id = ?
            """,
            (_now_iso(), run_id),
        )

    # ------------------------------------------------------------------
    # Step lifecycle
    # ------------------------------------------------------------------

    def record_step_running(self, run_id: str, step_name: str, attempt: int) -> None:
        now = _now_iso()
        self._execute(
            """
            INSERT INTO pipeline_steps (run_id, step_name, status, attempt, recorded_at)
            VALUES (?, ?, 'running', ?, ?)
            ON CONFLICT (run_id, step_name, attempt) DO UPDATE
              SET status = 'running', recorded_at = excluded.recorded_at
            """,
            (run_id, step_name, attempt, now),
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
        self._execute(
            """
            INSERT INTO pipeline_steps
                (run_id, step_name, status, attempt,
                 duration_seconds, paths, schema_info, recorded_at)
            VALUES (?, ?, 'success', ?, ?, ?, ?, ?)
            ON CONFLICT (run_id, step_name, attempt) DO UPDATE
              SET status = 'success',
                  duration_seconds = excluded.duration_seconds,
                  paths = excluded.paths,
                  schema_info = excluded.schema_info
            """,
            (
                run_id,
                step_name,
                attempt,
                duration_seconds,
                json.dumps(paths),
                json.dumps(schema_info),
                _now_iso(),
            ),
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
            VALUES (?, ?, 'failed', ?, ?, ?, ?)
            ON CONFLICT (run_id, step_name, attempt) DO UPDATE
              SET status = 'failed',
                  duration_seconds = excluded.duration_seconds,
                  error = excluded.error
            """,
            (run_id, step_name, attempt, duration_seconds, error, _now_iso()),
        )

    def record_step_skipped(self, run_id: str, step_name: str) -> None:
        self._execute(
            """
            INSERT INTO pipeline_steps (run_id, step_name, status, attempt, recorded_at)
            VALUES (?, ?, 'skipped', 0, ?)
            ON CONFLICT (run_id, step_name, attempt) DO NOTHING
            """,
            (run_id, step_name, _now_iso()),
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
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
            clauses.append("pipeline_name = ?")
            params.append(pipeline_name)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        with self._lock:
            assert self._conn is not None
            rows = self._conn.execute(
                f"SELECT * FROM pipeline_runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [_row_to_run_record(r) for r in rows]

    def list_steps(self, run_id: str) -> list[StepRecord]:
        with self._lock:
            assert self._conn is not None
            rows = self._conn.execute(
                "SELECT * FROM pipeline_steps WHERE run_id = ? ORDER BY recorded_at ASC, id ASC",
                (run_id,),
            ).fetchall()
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
            assert self._conn is not None
            try:
                self._conn.execute("BEGIN")
                self._conn.execute(sql, params)
                self._conn.execute("COMMIT")
            except Exception as exc:
                with contextlib.suppress(Exception):
                    self._conn.execute("ROLLBACK")
                raise MetastoreError(f"Metastore write failed: {exc}") from exc


def _row_to_run_record(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        pipeline_name=row["pipeline_name"],
        status=row["status"],
        error=row["error"],
        created_at=datetime.datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.datetime.fromisoformat(row["updated_at"]),
        outputs=json.loads(row["outputs"] or "{}"),
    )


def _row_to_step_record(row: sqlite3.Row) -> StepRecord:
    return StepRecord(
        run_id=row["run_id"],
        step_name=row["step_name"],
        status=row["status"],
        attempt=row["attempt"],
        duration_seconds=row["duration_seconds"],
        error=row["error"],
        paths=json.loads(row["paths"] or "{}"),
        schema_info=json.loads(row["schema_info"] or "{}"),
        recorded_at=datetime.datetime.fromisoformat(row["recorded_at"]),
    )
