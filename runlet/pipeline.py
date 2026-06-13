"""Pipeline — decorator DSL for defining pipeline steps as plain functions."""

from __future__ import annotations

from typing import Any, Callable

from runlet.artifact_store import build_store_config
from runlet.orchestrator.config.models import PipelineConfig, StepConfig
from runlet.orchestrator.dag import DAG
from runlet.orchestrator.models import RunnerConfig, RunResult
from runlet.orchestrator.registry import PrebuiltStepRegistry
from runlet.orchestrator.runner import SequentialRunner
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
    ) -> Callable:
        """
        Decorate a function as a pipeline step.

        The function must accept a single ``context`` argument
        (RuntimeContext) and return a JSON-serializable dict.
        """
        def decorator(fn: Callable) -> Callable:
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
        return PipelineConfig(
            name=self._name,
            run_id_prefix=self._run_id_prefix,
            steps=tuple(self._step_cfgs),
            store=build_store_config(self._store_raw),
            runner=RunnerConfig.from_dict(self._runner_raw),
        )

    def run(
        self,
        run_id: str,
        *,
        initial_metadata: dict[str, Any] | None = None,
        metastore: Any | None = None,
    ) -> RunResult:
        """Build the DAG, create a PrebuiltStepRegistry, and execute the run."""
        pipeline_cfg = self._build_config()
        registry = PrebuiltStepRegistry(self._instances)
        dag = DAG(pipeline_cfg)
        runner = SequentialRunner(
            dag=dag,
            step_registry=registry,
            initial_metadata=initial_metadata,
            metastore=metastore,
        )
        return runner.run(run_id)


def _make_function_step(fn: Callable, name: str, config: dict[str, Any]) -> BaseStep:
    """Wrap a plain function as a BaseStep subclass."""
    class _FunctionStep(BaseStep):
        def execute(self, context: Any) -> dict[str, Any]:
            return fn(context)

    _FunctionStep.__name__ = name
    _FunctionStep.__qualname__ = name
    return _FunctionStep(name=name, config=config)
