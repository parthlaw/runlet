"""
runlet.metastore — DB-agnostic lifecycle metadata store.

Tracks run and step status in SQL for cross-run queries. Additive to
the JSONL state file which continues to drive resume logic.

Usage::

    from runlet.metastore import build_metastore

    metastore = build_metastore({
        "type": "postgres",
        "dsn": "postgresql://user:pw@localhost:5432/pipeline_metastore",
    })
    metastore.init_schema()
"""

from __future__ import annotations

from typing import Any, cast

from runlet.metastore.metastore import (
    MetastoreConnectionError,
    MetastoreError,
    MetastoreSchemaError,
    RunMetastore,
    RunRecord,
    StepRecord,
)
from runlet.metastore.noop import NoopMetastore

METASTORE_REGISTRY: dict[str, type[RunMetastore]] = {
    "noop": NoopMetastore,
}


def register_metastore(name: str, cls: type[RunMetastore]) -> None:
    """Register a custom metastore class under *name*."""
    METASTORE_REGISTRY[name] = cls


def build_metastore(config: dict[str, Any] | None) -> RunMetastore:
    """
    Construct a RunMetastore from a config dict.

    Returns a NoopMetastore when config is None or empty — the runner
    behaves exactly as before with no metastore configured.

    Config shape::

        {"type": "postgres",     "dsn": "postgresql://..."}
        {"type": "cockroachdb",  "dsn": "postgresql://crdb-host:26257/db"}
    """
    if not config:
        return NoopMetastore()

    metastore_type = config.get("type", "noop")

    if metastore_type == "postgres" and "postgres" not in METASTORE_REGISTRY:
        from runlet.metastore.stores.postgres import PostgresMetastore

        METASTORE_REGISTRY["postgres"] = PostgresMetastore

    if metastore_type == "cockroachdb" and "cockroachdb" not in METASTORE_REGISTRY:
        from runlet.metastore.stores.cockroachdb import CockroachDBMetastore

        METASTORE_REGISTRY["cockroachdb"] = CockroachDBMetastore

    cls = METASTORE_REGISTRY.get(metastore_type)
    if cls is None:
        known = ", ".join(METASTORE_REGISTRY)
        raise ValueError(f"Unknown metastore type {metastore_type!r}. Known: {known}")

    return cast(RunMetastore, cast(Any, cls).from_config(config))


__all__ = [
    "METASTORE_REGISTRY",
    "CockroachDBConfig",  # lazy-loaded via __getattr__
    "CockroachDBMetastore",  # lazy-loaded via __getattr__
    "MetastoreConnectionError",
    "MetastoreError",
    "MetastoreSchemaError",
    "NoopMetastore",
    "PostgresConfig",  # lazy-loaded via __getattr__
    "PostgresMetastore",  # lazy-loaded via __getattr__
    "RunMetastore",
    "RunRecord",
    "StepRecord",
    "build_metastore",
    "register_metastore",
]


def __getattr__(name: str) -> object:
    if name in ("PostgresMetastore", "PostgresConfig"):
        from runlet.metastore.stores.postgres import PostgresConfig, PostgresMetastore

        return PostgresMetastore if name == "PostgresMetastore" else PostgresConfig
    if name in ("CockroachDBMetastore", "CockroachDBConfig"):
        from runlet.metastore.stores.cockroachdb import (
            CockroachDBConfig,
            CockroachDBMetastore,
        )

        return CockroachDBMetastore if name == "CockroachDBMetastore" else CockroachDBConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
