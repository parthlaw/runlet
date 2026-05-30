"""
RuntimeContext — read-only view of pipeline state passed to step execute().

Steps can read artifact paths and stream upstream records, but cannot write
to the context. Write operations live in WriterContext (held by the runner).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterator, Mapping
from typing import Any, TypeVar

from runlet.artifact_store import ArtifactStore
from runlet.artifacts import ArtifactSerializer, BaseArtifact
from runlet.artifacts.errors import SchemaError
from runlet.artifacts.ref import ArtifactRef
from runlet.artifacts.registry import ArtifactRegistry
from runlet.artifacts.registry import registry as _global_artifact_registry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseArtifact)


class RuntimeContext:
    """
    Read-only context passed to every step during execution.

    Exposes upstream artifact paths, metadata, streaming helpers, and an
    optional LLM proxy (context.llm) for steps that need LLM calls.
    """

    def __init__(
        self,
        *,
        run_id: str,
        pipeline_name: str,
        store: ArtifactStore,
        upload_store: ArtifactStore,
        metadata: dict[str, Any],
        artifact_registry: ArtifactRegistry | None = None,
        llm: Any | None = None,
    ) -> None:
        self.run_id = run_id
        self.pipeline_name = pipeline_name
        self.store = store
        self.upload_store = upload_store
        self._metadata: dict[str, Any] = metadata
        self.artifact_registry: ArtifactRegistry = artifact_registry or _global_artifact_registry
        self._paths: dict[str, dict[str, ArtifactRef]] = {}
        self._paths_lock = threading.RLock()
        self._llm = llm

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self._metadata

    @property
    def llm(self) -> Any:
        """
        Return the configured LLMProxy for this pipeline.

        Raises RuntimeError if no 'llm' block was defined in pipeline.json.
        """
        if self._llm is None:
            raise RuntimeError(
                "No LLM is configured for this pipeline. "
                "Add an 'llm' block to pipeline.json."
            )
        return self._llm

    def get_path(self, step_name: str, output_name: str = "output") -> ArtifactRef:
        """
        Retrieve the ArtifactRef for a specific step output.

        Raises KeyError if no path has been registered for (step_name, output_name).
        """
        with self._paths_lock:
            try:
                return self._paths[step_name][output_name]
            except KeyError:
                raise KeyError(
                    f"No artifact registered for step='{step_name}', output='{output_name}'. "
                    f"Registered paths: {self.list_paths()}"
                ) from None

    def has_path(self, step_name: str, output_name: str = "output") -> bool:
        with self._paths_lock:
            return output_name in self._paths.get(step_name, {})

    def list_paths(self) -> dict[str, dict[str, ArtifactRef]]:
        with self._paths_lock:
            return {step: dict(outputs) for step, outputs in self._paths.items()}

    def read_first_record(
        self,
        step_name: str,
        output_name: str = "output",
    ) -> dict[str, Any]:
        """
        Return the first data record from a step's JSONL artifact as a plain dict.

        Uses a Range GET (first 4 KB) for non-compressed artifacts, avoiding a
        full file download.
        """
        ref = self.get_path(step_name, output_name)

        if not ref.is_compressed:
            logger.debug("Reading first record (range): %s/%s → %s", step_name, output_name, ref.uri)
            try:
                chunk = self.store.download_bytes_range(ref.uri, 0, 4096)
                lines = chunk.decode("utf-8").splitlines()
                if not lines:
                    raise ValueError(
                        f"Artifact for step '{step_name}' output '{output_name}' is empty."
                    )
                for line in lines:
                    line = line.strip()
                    if line:
                        try:
                            parsed = json.loads(line)
                        except json.JSONDecodeError:
                            break  # record cut off by 4 KB window; fall through to full download
                        if not isinstance(parsed, dict):
                            raise ValueError(
                                f"First record for step '{step_name}' must be a JSON object."
                            )
                        return parsed
            except NotImplementedError:
                pass

        return self._read_first_record_full(step_name, output_name, ref)

    def _read_first_record_full(
        self, step_name: str, output_name: str, ref: ArtifactRef
    ) -> dict[str, Any]:
        from runlet.artifacts.io import open_artifact_read

        suffix = ".jsonl.gz" if ref.is_compressed else ".jsonl"
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"{self.run_id}_{step_name}_{output_name}_cond{suffix}",
        )
        self.store.download_file(ref.uri, tmp_path)
        logger.debug("Reading first record (full): %s/%s → %s", step_name, output_name, tmp_path)
        try:
            with open_artifact_read(tmp_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        parsed = json.loads(line)
                        if not isinstance(parsed, dict):
                            raise ValueError(
                                f"First record for step '{step_name}' must be a JSON object."
                            )
                        return parsed
                raise ValueError(
                    f"Artifact for step '{step_name}' output '{output_name}' has no data records."
                )
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)

    def iter_artifacts(
        self,
        step_name: str,
        artifact_cls: type[T],
        output_name: str = "output",
        *,
        strict: bool = True,
    ) -> Iterator[T]:
        """
        Stream typed records from an upstream step's JSONL artifact.

        Parameters
        ----------
        strict:
            If True (default) raise SchemaError on a schema name mismatch.
            Pass False to log a warning and continue.
        """
        from runlet.artifacts.io import open_artifact_read

        ref = self.get_path(step_name, output_name)
        written_version = ref.schema_version

        if ref.schema_name and ref.schema_name != artifact_cls.SCHEMA_NAME:
            msg = (
                f"Schema mismatch for step {step_name!r}: "
                f"expected {artifact_cls.SCHEMA_NAME!r} but artifact has "
                f"{ref.schema_name!r}"
            )
            if strict:
                raise SchemaError(msg)
            logger.warning(msg)

        suffix = ".jsonl.gz" if ref.is_compressed else ".jsonl"
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"{self.run_id}_{step_name}_{output_name}_dl{suffix}",
        )

        self.store.download_file(ref.uri, tmp_path)
        logger.debug("Streaming typed artifact: %s/%s → %s", step_name, output_name, tmp_path)

        try:
            with open_artifact_read(tmp_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        record = ArtifactSerializer.load_record(
                            line,
                            artifact_cls,
                            written_version,
                        )
                        yield record  # type: ignore[misc]
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)

    def to_dict(self) -> dict[str, Any]:
        with self._paths_lock:
            paths_serialized = {
                step: {out: ref.to_dict() for out, ref in outputs.items()}
                for step, outputs in self._paths.items()
            }
        return {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "paths": paths_serialized,
            "metadata": dict(self._metadata),
        }
