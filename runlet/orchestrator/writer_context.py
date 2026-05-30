"""
WriterContext — extends RuntimeContext with write operations for the runner.

Steps receive RuntimeContext (read-only). The runner holds WriterContext and
calls set_path/restore_paths after each step completes.
"""

from __future__ import annotations

import logging
from typing import Any

from runlet.artifact_store import ArtifactStore
from runlet.artifacts.ref import ArtifactRef
from runlet.artifacts.registry import ArtifactRegistry
from runlet.orchestrator.runtime_context import RuntimeContext

logger = logging.getLogger(__name__)


class WriterContext(RuntimeContext):
    """
    Full context held by the runner — adds path registration and metadata writes.

    Steps only see RuntimeContext so they cannot accidentally call set_path or
    modify the path registry.
    """

    @property
    def metadata(self) -> dict[str, Any]:
        return self._metadata

    def set_path(self, step_name: str, output_name: str, ref: ArtifactRef) -> None:
        """Register an artifact ref produced by *step_name* under *output_name*."""
        with self._paths_lock:
            if step_name not in self._paths:
                self._paths[step_name] = {}
            self._paths[step_name][output_name] = ref
        logger.debug("Context: registered %s/%s → %s", step_name, output_name, ref.uri)

    def restore_paths(self, paths: dict[str, dict[str, Any]]) -> None:
        """
        Restore a previously serialised path registry.

        Accepts either ArtifactRef objects, dicts (from deserialized state),
        or plain URI strings (backward compat with old state files).
        """
        for step_name, outputs in paths.items():
            for output_name, val in outputs.items():
                if isinstance(val, ArtifactRef):
                    ref = val
                elif isinstance(val, dict):
                    ref = ArtifactRef.from_dict(val)
                else:
                    ref = ArtifactRef(uri=str(val), schema_name="", schema_version=0)
                self.set_path(step_name=step_name, output_name=output_name, ref=ref)
        logger.info("Context restored: %d step(s) with registered paths", len(paths))


def build_context(
    run_id: str,
    pipeline_name: str,
    store: ArtifactStore,
    upload_store: ArtifactStore,
    metadata: dict[str, Any] | None = None,
    artifact_registry: ArtifactRegistry | None = None,
    llm: Any | None = None,
) -> WriterContext:
    """Construct a WriterContext. Intended for use by the runner."""
    return WriterContext(
        run_id=run_id,
        pipeline_name=pipeline_name,
        store=store,
        upload_store=upload_store,
        metadata=metadata or {},
        artifact_registry=artifact_registry,
        llm=llm,
    )
