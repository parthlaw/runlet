"""DAG — pipeline graph topology: ordering, cycle detection, and graph traversal."""

from __future__ import annotations

import logging
from collections import deque

from runlet.orchestrator.config.models import PipelineConfig
from runlet.orchestrator.errors import ConfigValidationError, CyclicDependencyError

logger = logging.getLogger(__name__)


class DAG:
    """
    Directed Acyclic Graph built from a :class:`PipelineConfig`.

    Responsibilities:
        - Validate that all ``depends_on`` references point to existing steps.
        - Detect cycles and raise
          :class:`~runlet.orchestrator.errors.CyclicDependencyError`.
        - Produce a deterministic topological execution order via Kahn's algorithm.
        - Provide ancestor/descendant queries for downstream skipping logic.
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._config = config
        self._adjacency: dict[str, list[str]] = {}
        self._in_degree: dict[str, int] = {}
        self._topo_order: list[str] = []
        self._build()

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @property
    def topological_order(self) -> list[str]:
        """Step names in valid execution order (each step after all its dependencies)."""
        return list(self._topo_order)

    def dependencies_of(self, step_name: str) -> tuple[str, ...]:
        """Return the direct dependencies of *step_name*."""
        return self._config.get_step(step_name).depends_on

    def dependents_of(self, step_name: str) -> list[str]:
        """Return steps that directly depend on *step_name*."""
        return list(self._adjacency.get(step_name, []))

    def compute_in_degrees(self) -> dict[str, int]:
        """Return a mutable copy of the initial in-degree map (for executor scheduling)."""
        return dict(self._in_degree)

    def ancestors_of(self, step_name: str) -> set[str]:
        """Return all transitive ancestors (dependencies) of *step_name*."""
        visited: set[str] = set()
        queue = deque(self.dependencies_of(step_name))
        while queue:
            current = queue.popleft()
            if current not in visited:
                visited.add(current)
                queue.extend(self.dependencies_of(current))
        return visited

    def descendants_of(self, step_name: str) -> set[str]:
        """Return all transitive descendants (dependents) of *step_name*."""
        visited: set[str] = set()
        queue = deque(self.dependents_of(step_name))
        while queue:
            current = queue.popleft()
            if current not in visited:
                visited.add(current)
                queue.extend(self.dependents_of(current))
        return visited

    def _build(self) -> None:
        step_names = set(self._config.step_names)

        for step in self._config.steps:
            self._adjacency[step.name] = []
            self._in_degree[step.name] = len(step.depends_on)
            for dep in step.depends_on:
                if dep not in step_names:
                    raise ConfigValidationError(
                        f"Step '{step.name}' depends on unknown step '{dep}'."
                    )

        for step in self._config.steps:
            for dep in step.depends_on:
                self._adjacency[dep].append(step.name)

        self._topo_order = self._kahn()
        logger.info(
            "DAG built for pipeline '%s'. Execution order: %s",
            self._config.name,
            " → ".join(self._topo_order),
        )

    def _kahn(self) -> list[str]:
        in_degree = dict(self._in_degree)
        queue: deque[str] = deque(
            name for name, degree in in_degree.items() if degree == 0
        )
        order: list[str] = []

        while queue:
            next_step = min(queue)
            queue.remove(next_step)
            order.append(next_step)
            for dependent in sorted(self._adjacency[next_step]):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(self._config.steps):
            remaining = [n for n in in_degree if n not in order]
            raise CyclicDependencyError(
                f"Cycle detected in pipeline '{self._config.name}'. "
                f"Involved steps: {remaining}"
            )

        return order
