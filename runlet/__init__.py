"""
runlet — DAG pipeline orchestration with pluggable artifact storage.
"""

from runlet.artifact_store import (
    ArtifactStore,
    ArtifactStoreDownloadError,
    ArtifactStoreError,
    ArtifactStoreUploadError,
    FilesystemStore,
    build_runtime_stores,
    build_store,
    register_store,
)
from runlet.logging import setup_logging
from runlet.metastore import (
    NoopMetastore,
    RunMetastore,
    build_metastore,
    register_metastore,
)
from runlet.orchestrator.config import PipelineConfig
from runlet.orchestrator.context import PipelineContext, RuntimeContext
from runlet.orchestrator.dag import DAG
from runlet.orchestrator.executor import ThreadedExecutor
from runlet.orchestrator.models import RunnerConfig, RunResult
from runlet.orchestrator.registry import ConfigStepRegistry, PrebuiltStepRegistry, StepRegistry
from runlet.orchestrator.runner import SequentialRunner, build_runner
from runlet.orchestrator.state import RunState, RunStatus, StepStatus
from runlet.pipeline import Pipeline
from runlet.steps.base import BaseStep

__all__ = [
    "DAG",
    "ArtifactStore",
    "ArtifactStoreDownloadError",
    "ArtifactStoreError",
    "ArtifactStoreUploadError",
    "BaseStep",
    "CockroachDBConfig",  # lazy-loaded via __getattr__
    "CockroachDBMetastore",  # lazy-loaded via __getattr__
    "ConfigStepRegistry",
    "FilesystemStore",
    "LLMConfig",  # lazy-loaded via __getattr__
    "LLMProxy",  # lazy-loaded via __getattr__
    "NoopMetastore",
    "Pipeline",
    "PipelineConfig",
    "PipelineContext",
    "PostgresConfig",  # lazy-loaded via __getattr__
    "PostgresMetastore",  # lazy-loaded via __getattr__
    "PrebuiltStepRegistry",
    "RunMetastore",
    "RunResult",
    "RunState",
    "RunStatus",
    "RunnerConfig",
    "RuntimeContext",
    "S3ArtifactStore",  # lazy-loaded via __getattr__
    "S3Config",  # lazy-loaded via __getattr__
    "SequentialRunner",
    "StepRegistry",
    "StepStatus",
    "ThreadedExecutor",
    "build_metastore",
    "build_runner",
    "build_runtime_stores",
    "build_store",
    "register_metastore",
    "register_store",
    "setup_logging",
]


def __getattr__(name: str) -> object:
    if name in ("S3ArtifactStore", "S3Config"):
        from runlet.artifact_store.stores.s3 import S3ArtifactStore, S3Config

        return S3ArtifactStore if name == "S3ArtifactStore" else S3Config
    if name == "LLMProxy":
        from runlet.llm.proxy import LLMProxy

        return LLMProxy
    if name == "LLMConfig":
        from runlet.llm.config import LLMConfig

        return LLMConfig
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
