"""StepRegistry — the single abstraction between the runner and step instantiation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, cast

from runlet.orchestrator.errors import ConfigValidationError
from runlet.steps.base import BaseStep
from runlet.steps.loader import StepImportError, load_step

if TYPE_CHECKING:
    from runlet.orchestrator.config.models import PipelineConfig, StepConfig


class StepRegistry(ABC):
    """
    Resolves a step name to a ready-to-execute BaseStep instance.

    The runner calls get() once per step execution. Concrete subclasses
    decide how instances are built — dynamically imported or pre-built.
    """

    @abstractmethod
    def get(self, name: str) -> BaseStep:
        """Return the step instance for *name*. Raise StepImportError if not found."""
        ...

    def validate(self, step_names: list[str]) -> None:  # noqa: B027
        """
        Called by WorkflowRunner.__init__ to assert all DAG steps are resolvable.
        Default is a no-op; subclasses override to fail-fast on missing steps.
        """


class ConfigStepRegistry(StepRegistry):
    """
    JSON/class-based path.

    Wraps load_step(), preserving current behavior: a fresh instance is
    created each time get() is called (once per execution / retry attempt).
    """

    def __init__(self, pipeline_cfg: PipelineConfig) -> None:
        self._step_cfgs: dict[str, StepConfig] = {
            s.name: s for s in pipeline_cfg.steps
        }

    def get(self, name: str) -> BaseStep:
        try:
            step_cfg = self._step_cfgs[name]
        except KeyError:
            raise StepImportError(f"No StepConfig found for step '{name}'.") from None
        return cast(BaseStep, load_step(step_cfg))

    # validate() is intentionally a no-op: import errors surface lazily at
    # execution time, matching current behavior.


class PrebuiltStepRegistry(StepRegistry):
    """
    Decorator path.

    Holds pre-instantiated BaseStep objects keyed by step name. Created
    by Pipeline.run() after all @pipe.step() decorators have been applied.
    """

    def __init__(self, instances: dict[str, BaseStep]) -> None:
        self._instances: dict[str, BaseStep] = dict(instances)

    def get(self, name: str) -> BaseStep:
        try:
            template = self._instances[name]
        except KeyError:
            raise StepImportError(
                f"No step registered for name '{name}'. "
                "Ensure every pipeline step is decorated with @pipe.step()."
            ) from None
        # Fresh instance per call to match ConfigStepRegistry semantics —
        # execute() may mutate self and retries must start clean.
        return type(template)(name=template.name, config=dict(template.config))

    def validate(self, step_names: list[str]) -> None:
        missing = [n for n in step_names if n not in self._instances]
        if missing:
            raise ConfigValidationError(
                f"Steps {missing} are declared in the pipeline but have no registered "
                "instance. Every step must be decorated with @pipe.step() when using "
                "the decorator path."
            )
