from runlet.artifact_store.stores.filesystem import (
    FilesystemConfig,
    FilesystemStore,
)

__all__ = [
    "FilesystemConfig",
    "FilesystemStore",
    "S3ArtifactStore",
    "S3Config",
]


def __getattr__(name: str) -> object:
    if name in ("S3ArtifactStore", "S3Config"):
        from runlet.artifact_store.stores.s3 import S3ArtifactStore, S3Config

        return S3ArtifactStore if name == "S3ArtifactStore" else S3Config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
