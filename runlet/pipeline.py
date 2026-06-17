"""Pipeline — decorator DSL for defining pipeline steps as plain functions."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any, cast

from runlet.artifact_store import build_store_config
from runlet.orchestrator.config.models import PipelineConfig, StepConfig
from runlet.orchestrator.config.runner import RunnerConfig, RunResult
from runlet.orchestrator.errors import ConfigValidationError
from runlet.orchestrator.execution.runner import WorkflowRunner
from runlet.orchestrator.graph.dag import DAG
from runlet.orchestrator.registry.registry import PrebuiltStepRegistry
from runlet.steps.base import BaseStep


class Pipeline:
    """
    Decorator-based pipeline builder.

    Define steps as plain functions decorated with @pipe.step(). Call
    pipe.run(run_id) to execute the pipeline through the same engine
    used by the JSON/class path.

    Example::

        from runlet import Pipeline

        pipe = Pipeline(
            "my-pipeline",
            store={"type": "filesystem", "base_dir": "/tmp/artifacts"},
        )

        @pipe.step("extract")
        def extract(context):
            return {"count": 42, "status": "ok"}

        @pipe.step("transform", depends_on=["extract"])
        def transform(context):
            upstream = context.get_output("extract")
            return {"result": upstream["count"] * 2}

        result = pipe.run("run-001")
    """

    def __init__(
        self,
        name: str,
        *,
        store: dict[str, Any],
        run_id_prefix: str = "run",
        runner: dict[str, Any] | None = None,
    ) -> None:
        self._name = name
        self._store_raw = store
        self._run_id_prefix = run_id_prefix
        self._runner_raw: dict[str, Any] = runner or {}
        self._instances: dict[str, BaseStep] = {}
        self._step_cfgs: list[StepConfig] = []

    def step(
        self,
        name: str,
        *,
        depends_on: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        """
        Decorate a function as a pipeline step.

        The function must accept a single ``context`` argument
        (RuntimeContext) and return a JSON-serializable dict.
        """
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            if name in self._instances:
                raise ValueError(
                    f"Duplicate step name '{name}'. "
                    "Each step in a pipeline must have a unique name."
                )
            instance = _make_function_step(fn, name=name, config=config or {})
            self._instances[name] = instance
            self._step_cfgs.append(
                StepConfig(
                    name=name,
                    module="__runlet_decorator__",
                    class_name="__runlet_decorator__",
                    depends_on=tuple(depends_on or []),
                    config=config or {},
                )
            )
            return fn
        return decorator

    def _build_config(self) -> PipelineConfig:
        """Construct the PipelineConfig from the current set of decorated steps."""
        steps = tuple(self._step_cfgs)
        if not steps:
            raise ConfigValidationError(
                "Pipeline must define at least one step. "
                "Use @pipe.step() to register steps before calling run()."
            )
        return PipelineConfig(
            name=self._name,
            run_id_prefix=self._run_id_prefix,
            steps=steps,
            store=build_store_config(self._store_raw),
            runner=RunnerConfig.from_dict(self._runner_raw),
        )

    def run(
        self,
        run_id: str,
        *,
        resume: bool = False,
        initial_metadata: dict[str, Any] | None = None,
        metastore: Any | None = None,
    ) -> RunResult:
        """Build the DAG, create a PrebuiltStepRegistry, and execute the run.

        ``resume=True`` skips steps already recorded as complete in the metastore.
        A persistent metastore must be supplied (or configured via the ``runner``
        dict) for resume to work — with NoopMetastore the run always starts fresh.
        """
        pipeline_cfg = self._build_config()
        runner_cfg = (
            dataclasses.replace(pipeline_cfg.runner, resume=True)
            if resume
            else pipeline_cfg.runner
        )
        registry = PrebuiltStepRegistry(self._instances)
        dag = DAG(pipeline_cfg)
        runner = WorkflowRunner(
            dag=dag,
            runner_config=runner_cfg,
            step_registry=registry,
            initial_metadata=initial_metadata,
            metastore=metastore,
        )
        return runner.run(run_id)


def _make_function_step(fn: Callable[..., Any], name: str, config: dict[str, Any]) -> BaseStep:
    """Wrap a plain function as a BaseStep subclass."""
    class _FunctionStep(BaseStep):
        def execute(self, context: Any) -> dict[str, Any]:
            return cast(dict[str, Any], fn(context))

    _FunctionStep.__name__ = name
    _FunctionStep.__qualname__ = name
    return _FunctionStep(name=name, config=config)
