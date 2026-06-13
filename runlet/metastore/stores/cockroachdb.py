"""CockroachDBMetastore — thin subclass of PostgresMetastore with CRDB-compatible DDL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from runlet.metastore.metastore import MetastoreType
from runlet.metastore.stores.postgres import PostgresConfig, PostgresMetastore

# CockroachDB DDL: identical to PostgreSQL except pipeline_steps uses
# INT8 DEFAULT unique_rowid() instead of BIGSERIAL, which maps more
# explicitly to CockroachDB's distributed ID generation semantics.
_CRDB_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          TEXT        NOT NULL,
    pipeline_name   TEXT        NOT NULL,
    status          TEXT        NOT NULL,
    error           TEXT,
    outputs         JSONB       NOT NULL DEFAULT '{}',
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
    id               INT8             NOT NULL DEFAULT unique_rowid(),
    run_id           TEXT             NOT NULL,
    step_name        TEXT             NOT NULL,
    status           TEXT             NOT NULL,
    attempt          INT              NOT NULL DEFAULT 1,
    duration_seconds DOUBLE PRECISION,
    error            TEXT,
    output           JSONB            NOT NULL DEFAULT '{}',
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
class CockroachDBConfig(PostgresConfig):
    """
    Config for CockroachDBMetastore. Identical to PostgresConfig — psycopg3
    connects to CockroachDB the same way. Kept as a distinct type so the
    registry can distinguish the two and callers get a semantically clear type.

    Typical DSN: ``postgresql://user:pw@crdb-host:26257/pipeline_metastore``
    """

    TYPE: ClassVar[MetastoreType] = MetastoreType.COCKROACHDB

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CockroachDBConfig:
        if "dsn" not in data:
            raise ValueError("CockroachDBConfig requires a 'dsn' key")
        return cls(
            dsn=data["dsn"],
            connect_timeout=int(data.get("connect_timeout", 10)),
        )


class CockroachDBMetastore(PostgresMetastore):
    """
    CockroachDB-compatible metastore. Subclasses PostgresMetastore and overrides
    only the schema DDL — all DML (INSERT/UPDATE/SELECT) is inherited unchanged
    since CockroachDB is PostgreSQL-wire-compatible.
    """

    _SCHEMA_SQL: str = _CRDB_SCHEMA_SQL

    @classmethod
    def from_config(cls, config: CockroachDBConfig) -> CockroachDBMetastore:  # type: ignore[override]
        return cls(config)
