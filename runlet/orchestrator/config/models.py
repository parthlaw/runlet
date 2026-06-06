"""Pipeline configuration data model — dataclasses and parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runlet.artifact_store import StoreConfig, build_store_config
from runlet.llm.config import LLMConfig
from runlet.orchestrator.errors import ConfigValidationError
from runlet.orchestrator.models import RunnerConfig

ALLOWED_CONDITION_OPS = frozenset({"==", "!=", ">", "<", ">=", "<="})


@dataclass(frozen=True)
class ConditionConfig:
    """
    Condition evaluated against the first record of an upstream step's output.

    Attributes
    ----------
    step:
        Upstream step name whose output is read (must be in ``depends_on``).
    field:
        Dot-notation path into the first record (e.g. ``"result.status"``).
    op:
        Comparison operator: ``==``, ``!=``, ``>``, ``<``, ``>=``, ``<=``.
    value:
        Expected value to compare against (JSON scalar).
    """

    step: str
    field: str
    op: str
    value: Any

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConditionConfig:
        for key in ("step", "field", "op", "value"):
            if key not in data:
                raise ConfigValidationError(
                    f"Condition config missing required field '{key}': {data}"
                )
        field_path = data["field"]
        if not isinstance(field_path, str) or not field_path.strip():
            raise ConfigValidationError(
                f"Condition field must be a non-empty string: {data!r}"
            )
        op = data["op"]
        if op not in ALLOWED_CONDITION_OPS:
            raise ConfigValidationError(
                f"Condition op must be one of {sorted(ALLOWED_CONDITION_OPS)}, "
                f"got {op!r}."
            )
        return cls(step=data["step"], field=field_path, op=op, value=data["value"])


@dataclass(frozen=True)
class StepConfig:
    """
    Immutable configuration for a single DAG step.

    Attributes
    ----------
    name:
        Unique step identifier within the pipeline.
    module:
        Python dotted-path to the module containing the step class.
    class_name:
        Name of the class inside *module*.
    depends_on:
        Ordered tuple of step names this step must wait for.
    config:
        Arbitrary step-level config forwarded to the step at instantiation.
    condition:
        Optional condition; step runs only when the condition evaluates True.
    """

    name: str
    module: str
    class_name: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    config: dict[str, Any] = field(default_factory=dict)
    condition: ConditionConfig | None = None
    retry: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepConfig:
        for key in ("name", "module", "class"):
            if key not in data:
                raise ConfigValidationError(
                    f"Step config missing required field '{key}': {data}"
                )
        depends_on = tuple(data.get("depends_on", []))
        condition = None
        if data.get("condition") is not None:
            condition = ConditionConfig.from_dict(data["condition"])
            if condition.step not in depends_on:
                raise ConfigValidationError(
                    f"Step '{data['name']}' condition references step "
                    f"'{condition.step}' which is not in depends_on "
                    f"{list(depends_on)}."
                )
        return cls(
            name=data["name"],
            module=data["module"],
            class_name=data["class"],
            depends_on=depends_on,
            config=data.get("config", {}),
            condition=condition,
            retry=data.get("retry", {}),
        )


@dataclass(frozen=True)
class PipelineConfig:
    """
    Immutable, validated pipeline configuration.

    Attributes
    ----------
    name:
        Human-readable pipeline name.
    run_id_prefix:
        Short string prepended to auto-generated run IDs.
    steps:
        Ordered tuple of :class:`StepConfig` objects.
    store:
        Typed artifact store configuration.
    raw:
        Full raw dict for any extension points.
    """

    name: str
    run_id_prefix: str
    steps: tuple[StepConfig, ...]
    store: StoreConfig
    runner: RunnerConfig = field(default_factory=RunnerConfig, compare=False)
    raw: dict[str, Any] = field(default_factory=dict, compare=False)
    llm: LLMConfig | None = field(default=None, compare=False)

    @classmethod
    def from_file(cls, path: Path | str) -> PipelineConfig:
        """Load and validate a pipeline JSON config from disk."""
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Pipeline config not found: {config_path}")
        with config_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return cls._parse(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PipelineConfig:
        """Construct a PipelineConfig from an already-parsed dict."""
        return cls._parse(raw)

    @classmethod
    def _parse(cls, raw: dict[str, Any]) -> PipelineConfig:
        _validate_top_level_keys(raw)
        pipeline_block = raw["pipeline"]
        steps = tuple(StepConfig.from_dict(s) for s in raw.get("steps", []))
        if not steps:
            raise ConfigValidationError(
                "Pipeline config must define at least one step."
            )
        _validate_step_names_unique(steps)
        return cls(
            name=pipeline_block["name"],
            run_id_prefix=pipeline_block.get("run_id_prefix", "run"),
            steps=steps,
            store=build_store_config(raw["store"]),
            runner=RunnerConfig.from_dict(raw.get("runner", {})),
            raw=raw,
            llm=LLMConfig.from_dict(raw["llm"]) if raw.get("llm") else None,
        )

    def get_step(self, name: str) -> StepConfig:
        """Return the StepConfig for *name*. Raises ``KeyError`` if missing."""
        for step in self.steps:
            if step.name == name:
                return step
        raise KeyError(f"No step named '{name}' in pipeline '{self.name}'")

    @property
    def step_names(self) -> list[str]:
        return [s.name for s in self.steps]


# ---------------------------------------------------------------------------
# Private validation helpers
# ---------------------------------------------------------------------------

def _validate_top_level_keys(raw: dict[str, Any]) -> None:
    required = ("pipeline", "store", "steps")
    missing = [k for k in required if k not in raw]
    if missing:
        raise ConfigValidationError(
            f"Pipeline config missing top-level key(s): {missing}"
        )
    if "name" not in raw["pipeline"]:
        raise ConfigValidationError(
            "pipeline.name is required in the pipeline config."
        )


def _validate_step_names_unique(steps: tuple[StepConfig, ...]) -> None:
    seen: set[str] = set()
    for step in steps:
        if step.name in seen:
            raise ConfigValidationError(
                f"Duplicate step name '{step.name}' detected. "
                "Each step name must be unique within a pipeline."
            )
        seen.add(step.name)
