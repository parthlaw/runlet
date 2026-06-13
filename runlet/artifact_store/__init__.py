"""
artifact_store — pluggable artifact persistence for pipeline runs.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from runlet.artifact_store.store import (
    ArtifactStore,
    ArtifactStoreDownloadError,
    ArtifactStoreError,
    ArtifactStoreUploadError,
    StoreConfig,
    StoreType,
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


def build_store_config(data: dict[str, Any]) -> StoreConfig:
    """Parse a raw ``store`` config dict into a typed :class:`StoreConfig`."""
    store_type = StoreType(data.get("type", StoreType.FILESYSTEM.value))
    if store_type == StoreType.S3:
        from runlet.artifact_store.stores.s3 import S3Config

        return S3Config.from_dict(data)
    if store_type == StoreType.FILESYSTEM:
        return FilesystemConfig.from_dict(data)
    raise ValueError(f"Unhandled store type {store_type!r}")


def build_store(config: StoreConfig) -> ArtifactStore:
    """Construct an :class:`ArtifactStore` from a typed :class:`StoreConfig`."""
    if isinstance(config, FilesystemConfig):
        return FilesystemStore(base_dir=config.base_dir, prefix=config.prefix)
    from runlet.artifact_store.stores.s3 import S3ArtifactStore, S3Config

    if isinstance(config, S3Config):
        return S3ArtifactStore(config)
    raise ValueError(f"Unknown store config: {type(config).__name__!r}")


def build_runtime_stores(
    store: StoreConfig,
    initial_metadata: dict[str, Any],
) -> tuple[ArtifactStore, ArtifactStore, str]:
    """
    Build pipeline-internal and user-facing artifact stores for a run.

    Returns (store, upload_store, store_prefix).

    ``store`` is scoped to pipeline artifacts (step data, run state).
    ``upload_store`` is unscoped for reading source files and writing final results.
    """
    from runlet.artifact_store.stores.s3 import S3ArtifactStore, S3Config

    if isinstance(store, S3Config):
        bucket: str = initial_metadata.get("bucket", store.bucket)
        source_key: str = initial_metadata.get("source_key", "")
        prefix = f"{source_key}/steps/" if source_key else store.prefix
        store_cfg = dataclasses.replace(store, bucket=bucket, prefix=prefix)
        upload_cfg = dataclasses.replace(store, bucket=bucket, prefix="")
        return S3ArtifactStore(store_cfg), S3ArtifactStore(upload_cfg), prefix

    if isinstance(store, FilesystemConfig):
        fs_store = FilesystemStore(base_dir=store.base_dir, prefix=store.prefix)
        return fs_store, fs_store, store.prefix

    raise ValueError(f"Unknown store config: {type(store).__name__!r}")


__all__ = [
    "STORE_REGISTRY",
    "ArtifactStore",
    "ArtifactStoreDownloadError",
    "ArtifactStoreError",
    "ArtifactStoreUploadError",
    "FilesystemConfig",
    "FilesystemStore",
    "StoreConfig",
    "StoreType",
    "build_runtime_stores",
    "build_store",
    "build_store_config",
    "register_store",
]


def __getattr__(name: str) -> object:
    if name in ("S3ArtifactStore", "S3Config"):
        from runlet.artifact_store.stores.s3 import S3ArtifactStore, S3Config

        return S3ArtifactStore if name == "S3ArtifactStore" else S3Config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
