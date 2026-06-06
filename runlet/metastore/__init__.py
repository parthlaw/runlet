"""
runlet.metastore — DB-agnostic lifecycle metadata store.

Tracks run and step status in SQL for cross-run queries. Additive to
the JSONL state file which continues to drive resume logic.

Usage::

    from runlet.metastore import build_metastore, build_metastore_config

    cfg = build_metastore_config({
        "type": "sqlite",
        "db_path": "/var/data/pipeline_metastore.db",
    })
    metastore = build_metastore(cfg)
    metastore.init_schema()
"""

from __future__ import annotations

from typing import Any

from runlet.metastore.metastore import (
    MetastoreConfig,
    MetastoreConnectionError,
    MetastoreError,
    MetastoreSchemaError,
    MetastoreType,
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


def build_metastore_config(data: dict[str, Any] | None) -> MetastoreConfig | None:
    """Parse a raw ``metastore`` config dict into a typed :class:`MetastoreConfig`."""
    if not data:
        return None
    metastore_type = MetastoreType(data.get("type", MetastoreType.NOOP.value))
    if metastore_type == MetastoreType.NOOP:
        return None
    if metastore_type == MetastoreType.SQLITE:
        from runlet.metastore.stores.sqlite import SqliteConfig

        return SqliteConfig.from_dict(data)
    if metastore_type == MetastoreType.POSTGRES:
        from runlet.metastore.stores.postgres import PostgresConfig

        return PostgresConfig.from_dict(data)
    if metastore_type == MetastoreType.COCKROACHDB:
        from runlet.metastore.stores.cockroachdb import CockroachDBConfig

        return CockroachDBConfig.from_dict(data)
    raise ValueError(f"Unhandled metastore type {metastore_type!r}")


def build_metastore(config: MetastoreConfig | None) -> RunMetastore:
    """
    Construct a :class:`RunMetastore` from a typed :class:`MetastoreConfig`.

    Returns a :class:`NoopMetastore` when *config* is ``None``.
    """
    if config is None:
        return NoopMetastore()
    from runlet.metastore.stores.sqlite import SqliteConfig, SqliteMetastore

    if isinstance(config, SqliteConfig):
        return SqliteMetastore(config)
    from runlet.metastore.stores.cockroachdb import CockroachDBConfig, CockroachDBMetastore

    if isinstance(config, CockroachDBConfig):
        return CockroachDBMetastore(config)
    from runlet.metastore.stores.postgres import PostgresConfig, PostgresMetastore

    if isinstance(config, PostgresConfig):
        return PostgresMetastore(config)
    raise ValueError(f"Unknown metastore config: {type(config).__name__!r}")


__all__ = [
    "METASTORE_REGISTRY",
    "CockroachDBConfig",  # lazy-loaded via __getattr__
    "CockroachDBMetastore",  # lazy-loaded via __getattr__
    "MetastoreConfig",
    "MetastoreConnectionError",
    "MetastoreError",
    "MetastoreSchemaError",
    "MetastoreType",
    "NoopMetastore",
    "PostgresConfig",  # lazy-loaded via __getattr__
    "PostgresMetastore",  # lazy-loaded via __getattr__
    "RunMetastore",
    "RunRecord",
    "SqliteConfig",  # lazy-loaded via __getattr__
    "SqliteMetastore",  # lazy-loaded via __getattr__
    "StepRecord",
    "build_metastore",
    "build_metastore_config",
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
    if name in ("SqliteMetastore", "SqliteConfig"):
        from runlet.metastore.stores.sqlite import SqliteConfig, SqliteMetastore

        return SqliteMetastore if name == "SqliteMetastore" else SqliteConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
