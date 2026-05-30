"""Orchestrator exception hierarchy."""


class DAGError(ValueError):
    """Base class for DAG construction and validation errors."""


class ConfigValidationError(DAGError):
    """Raised when the JSON config is structurally invalid."""


class CyclicDependencyError(DAGError):
    """Raised when the step dependency graph contains a cycle."""


class ConditionEvaluationError(RuntimeError):
    """Raised when a step condition cannot be evaluated."""


class PipelineExecutionError(RuntimeError):
    """Raised when a step fails and the runner cannot continue."""


class StateNotFoundError(RuntimeError):
    """Raised when attempting to resume a run with no existing state file."""
