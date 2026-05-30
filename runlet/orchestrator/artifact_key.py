"""Pluggable artifact key strategies — groundwork for content-addressed storage (Plan 4)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from runlet.artifact_store import ArtifactStore


class ArtifactKeyStrategy(Protocol):
    """Protocol for deriving the storage key from run/step identity."""

    def build_key(self, run_id: str, step_name: str, output_name: str) -> str:
        ...


class NameBasedKey:
    """Current default: key derived from (run_id, step_name, output_name) via the store."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def build_key(self, run_id: str, step_name: str, output_name: str) -> str:
        return self._store.build_key(run_id=run_id, step_name=step_name, filename=output_name)


class ContentAddressedKey:
    """Future: key derived from content hash of step inputs + logic (Plan 4)."""

    def build_key(self, run_id: str, step_name: str, output_name: str) -> str:
        raise NotImplementedError("Content-addressed keys require Plan 4 hash computation")
