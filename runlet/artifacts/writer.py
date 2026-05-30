"""Artifact writer — drains a step generator into a pure JSONL file."""

from __future__ import annotations

from typing import Any, ClassVar

from runlet.artifacts.base import BaseArtifact
from runlet.artifacts.io import open_artifact_write
from runlet.artifacts.serializer import ArtifactSerializer


class EmptyArtifact(BaseArtifact):
    """Placeholder used when a step yields no records."""

    SCHEMA_NAME: ClassVar[str] = "EmptyArtifact"
    SCHEMA_VERSION: ClassVar[int] = 1


def write_step_artifacts(
    *,
    step_instance: Any,
    context: Any,
    step_name: str,
    run_id: str,
    tmp_final_path: str,
) -> tuple[type[BaseArtifact], int]:
    """
    Drain *step_instance.execute(context)* into *tmp_final_path* as pure JSONL.

    Records are buffered in memory so we can return the artifact class and count.
    Returns the artifact class and the number of records written.
    """
    artifact_cls: type[BaseArtifact] | None = None
    records: list[BaseArtifact] = []

    for item in step_instance.execute(context):
        if not isinstance(item, BaseArtifact):
            raise TypeError(
                f"Step '{step_name}' must yield BaseArtifact instances, "
                f"got {type(item).__name__}."
            )
        if artifact_cls is None:
            artifact_cls = type(item)
        elif type(item) is not artifact_cls:
            raise TypeError(
                f"Step '{step_name}' yielded mixed artifact types: "
                f"{artifact_cls.__name__} and {type(item).__name__}."
            )
        records.append(item)

    if artifact_cls is None:
        artifact_cls = EmptyArtifact

    with open_artifact_write(tmp_final_path) as out:
        for item in records:
            out.write(ArtifactSerializer.dump_record(item) + "\n")

    return artifact_cls, len(records)
