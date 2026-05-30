"""Artifact layer exceptions."""


class ArtifactError(RuntimeError):
    """Base class for artifact errors."""


class UnknownArtifactError(ArtifactError):
    """Raised when a schema name/version is not registered."""

    def __init__(self, schema_name: str, version: int) -> None:
        super().__init__(
            f"Unknown artifact schema {schema_name!r} version {version}."
        )


class SchemaVersionMismatchError(ArtifactError):
    """Raised when the written schema version does not match the expected version."""

    def __init__(
        self,
        schema_name: str,
        written_version: int,
        expected_version: int,
    ) -> None:
        super().__init__(
            f"Schema version mismatch for {schema_name!r}: "
            f"artifact was written with v{written_version} but "
            f"the registered class is v{expected_version}. "
            "Write a data migration script to convert existing artifacts."
        )


class SchemaError(ArtifactError):
    """Raised when a JSONL artifact's schema does not match the requested class."""
