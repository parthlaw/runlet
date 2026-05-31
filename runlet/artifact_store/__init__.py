"""
artifact_store — pluggable artifact persistence for pipeline runs.
"""

from __future__ import annotations

from typing import Any, cast

from runlet.artifact_store.store import (
    ArtifactStore,
    ArtifactStoreDownloadError,
    ArtifactStoreError,
    ArtifactStoreUploadError,
)
from runlet.artifact_store.stores.filesystem import (
    FilesystemConfig,
    FilesystemStore,
)

# Registry maps store type names to classes. Third-party stores can be added
# via register_store() without modifying library code.
STORE_REGISTRY: dict[str, type[ArtifactStore]] = {
    "filesystem": FilesystemStore,
}


def register_store(name: str, cls: type[ArtifactStore]) -> None:
    """Register a custom store class under *name* for use with build_store."""
    STORE_REGISTRY[name] = cls


def build_store(config: dict[str, Any]) -> ArtifactStore:
    """
    Construct an :class:`ArtifactStore` from a pipeline config ``store`` block.

    Parameters
    ----------
    config:
        Dict with a ``type`` key (default ``"filesystem"``). Remaining keys are
        passed to the concrete store's ``from_config`` classmethod.
    """
    store_type = config.get("type", "filesystem")

    # Lazy-register S3 on first use to avoid importing boto3 unconditionally.
    if store_type == "s3" and "s3" not in STORE_REGISTRY:
        from runlet.artifact_store.stores.s3 import S3ArtifactStore

        STORE_REGISTRY["s3"] = S3ArtifactStore

    cls = STORE_REGISTRY.get(store_type)
    if cls is None:
        known = ", ".join(STORE_REGISTRY)
        raise ValueError(f"Unknown store type {store_type!r}. Known: {known}")
    return cast(ArtifactStore, cast(Any, cls).from_config(config))


def build_runtime_stores(
    store_raw: dict[str, Any],
    store_overrides: dict[str, Any] | None = None,
) -> tuple[ArtifactStore, ArtifactStore, str]:
    """
    Build pipeline-internal and user-facing artifact stores for a run.

    Returns (store, upload_store, store_prefix).

    ``store`` is scoped to pipeline artifacts (intermediate JSONL, run state).
    ``upload_store`` is unscoped for reading source files and writing final results.

    ``store_overrides`` carries per-run infrastructure config (bucket, prefix)
    computed by the caller before the runner is created — never derived from
    step data. Keys: ``bucket`` (str), ``prefix`` (str).
    """
    store_type = store_raw.get("type", "s3")
    overrides = store_overrides or {}

    if store_type == "s3":
        from runlet.artifact_store.stores.s3 import S3ArtifactStore, S3Config

        bucket = overrides.get("bucket") or store_raw.get("bucket", "")
        prefix = overrides.get("prefix") or store_raw.get("prefix", "pipelines/")
        region = store_raw["region"]
        endpoint_url = store_raw.get("endpoint_url")

        store_config = S3Config(
            bucket=bucket, region=region, prefix=prefix, endpoint_url=endpoint_url
        )
        upload_config = S3Config(
            bucket=bucket, region=region, prefix="", endpoint_url=endpoint_url
        )
        return S3ArtifactStore(store_config), S3ArtifactStore(upload_config), prefix

    if store_type == "filesystem":
        fs_store = FilesystemStore.from_config(store_raw)
        return fs_store, fs_store, fs_store.prefix

    raise ValueError(f"Unknown artifact store type: {store_type!r}")


__all__ = [
    "STORE_REGISTRY",
    "ArtifactStore",
    "ArtifactStoreDownloadError",
    "ArtifactStoreError",
    "ArtifactStoreUploadError",
    "FilesystemConfig",
    "FilesystemStore",
    "build_runtime_stores",
    "build_store",
    "register_store",
]


def __getattr__(name: str) -> object:
    if name in ("S3ArtifactStore", "S3Config"):
        from runlet.artifact_store.stores.s3 import S3ArtifactStore, S3Config

        return S3ArtifactStore if name == "S3ArtifactStore" else S3Config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
