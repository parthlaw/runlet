"""Tests for StepRegistry, ConfigStepRegistry, PrebuiltStepRegistry, and Pipeline DSL."""

from __future__ import annotations

import pytest

from runlet import Pipeline
from runlet.orchestrator.errors import ConfigValidationError
from runlet.orchestrator.registry.registry import (
    ConfigStepRegistry,
    PrebuiltStepRegistry,
    StepRegistry,
)
from runlet.steps.base import BaseStep
from runlet.steps.loader import StepImportError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ConstantStep(BaseStep):
    """Always returns {"value": config["value"]}."""

    def execute(self, context):
        return {"value": self.config.get("value", 0)}


def _make_prebuilt(names: list[str]) -> PrebuiltStepRegistry:
    instances = {n: _ConstantStep(name=n, config={"value": i}) for i, n in enumerate(names)}
    return PrebuiltStepRegistry(instances)


# ---------------------------------------------------------------------------
# StepRegistry is abstract
# ---------------------------------------------------------------------------

def test_step_registry_is_abstract():
    with pytest.raises(TypeError):
        StepRegistry()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# PrebuiltStepRegistry
# ---------------------------------------------------------------------------

def test_prebuilt_get_returns_instance():
    reg = _make_prebuilt(["extract", "transform"])
    inst = reg.get("extract")
    assert isinstance(inst, BaseStep)
    assert inst.name == "extract"


def test_prebuilt_get_unknown_raises():
    reg = _make_prebuilt(["extract"])
    with pytest.raises(StepImportError, match="No step registered for name 'missing'"):
        reg.get("missing")


def test_prebuilt_validate_passes_when_complete():
    reg = _make_prebuilt(["a", "b"])
    reg.validate(["a", "b"])  # should not raise


def test_prebuilt_validate_raises_on_missing():
    reg = _make_prebuilt(["a"])
    with pytest.raises(ConfigValidationError, match=r"Steps \['b'\]"):
        reg.validate(["a", "b"])


def test_prebuilt_stores_copy_of_instances():
    instances = {"x": _ConstantStep(name="x", config={})}
    reg = PrebuiltStepRegistry(instances)
    # Mutating the original dict doesn't affect the registry
    instances["y"] = _ConstantStep(name="y", config={})
    with pytest.raises(StepImportError):
        reg.get("y")


# ---------------------------------------------------------------------------
# ConfigStepRegistry
# ---------------------------------------------------------------------------

def test_config_registry_get_loads_valid_step(tmp_path):
    """ConfigStepRegistry.get() dynamically imports and instantiates the class."""
    from runlet.artifact_store import build_store_config
    from runlet.orchestrator.config.models import PipelineConfig, StepConfig

    step_cfg = StepConfig(
        name="const",
        module="tests.test_registry",
        class_name="_ConstantStep",
        config={"value": 99},
    )
    pipeline_cfg = PipelineConfig(
        name="test",
        run_id_prefix="run",
        steps=(step_cfg,),
        store=build_store_config({"type": "filesystem", "base_dir": str(tmp_path)}),
    )
    reg = ConfigStepRegistry(pipeline_cfg)
    inst = reg.get("const")
    assert isinstance(inst, _ConstantStep)
    assert inst.config["value"] == 99


def test_config_registry_get_raises_on_bad_module(tmp_path):
    from runlet.artifact_store import build_store_config
    from runlet.orchestrator.config.models import PipelineConfig, StepConfig

    step_cfg = StepConfig(
        name="bad",
        module="nonexistent.module.xyz",
        class_name="SomeClass",
    )
    pipeline_cfg = PipelineConfig(
        name="test",
        run_id_prefix="run",
        steps=(step_cfg,),
        store=build_store_config({"type": "filesystem", "base_dir": str(tmp_path)}),
    )
    reg = ConfigStepRegistry(pipeline_cfg)
    with pytest.raises(StepImportError):
        reg.get("bad")


def test_config_registry_get_fresh_instance_each_call(tmp_path):
    """ConfigStepRegistry creates a new instance per call (preserves original behavior)."""
    from runlet.artifact_store import build_store_config
    from runlet.orchestrator.config.models import PipelineConfig, StepConfig

    step_cfg = StepConfig(
        name="const",
        module="tests.test_registry",
        class_name="_ConstantStep",
    )
    pipeline_cfg = PipelineConfig(
        name="test",
        run_id_prefix="run",
        steps=(step_cfg,),
        store=build_store_config({"type": "filesystem", "base_dir": str(tmp_path)}),
    )
    reg = ConfigStepRegistry(pipeline_cfg)
    inst1 = reg.get("const")
    inst2 = reg.get("const")
    assert inst1 is not inst2


# ---------------------------------------------------------------------------
# Pipeline DSL — integration
# ---------------------------------------------------------------------------

def test_pipeline_single_step(tmp_path):
    pipe = Pipeline(
        "test-pipeline",
        store={"type": "filesystem", "base_dir": str(tmp_path)},
    )

    @pipe.step("only")
    def only(context):
        return {"done": True}

    result = pipe.run("run-single")
    assert result.success
    assert result.steps_executed == ["only"]
    assert result.steps_skipped == []


def test_pipeline_depends_on_order(tmp_path):
    pipe = Pipeline(
        "order-pipeline",
        store={"type": "filesystem", "base_dir": str(tmp_path)},
    )
    execution_order = []

    @pipe.step("a")
    def step_a(context):
        execution_order.append("a")
        return {"from": "a"}

    @pipe.step("b", depends_on=["a"])
    def step_b(context):
        execution_order.append("b")
        return {"from": "b"}

    @pipe.step("c", depends_on=["b"])
    def step_c(context):
        execution_order.append("c")
        return {"from": "c"}

    result = pipe.run("run-order")
    assert result.success
    assert execution_order == ["a", "b", "c"]


def test_pipeline_output_propagation(tmp_path):
    pipe = Pipeline(
        "prop-pipeline",
        store={"type": "filesystem", "base_dir": str(tmp_path)},
    )

    @pipe.step("producer")
    def producer(context):
        return {"value": 7}

    @pipe.step("consumer", depends_on=["producer"])
    def consumer(context):
        upstream = context.get_output("producer")
        return {"doubled": upstream["value"] * 2}

    result = pipe.run("run-prop")
    assert result.success
    assert result.steps_executed == ["producer", "consumer"]


def test_pipeline_missing_step_raises_at_run(tmp_path):
    """If a depends_on references a step not decorated, DAG construction fails."""
    from runlet.orchestrator.errors import ConfigValidationError

    pipe = Pipeline(
        "broken-pipeline",
        store={"type": "filesystem", "base_dir": str(tmp_path)},
    )

    @pipe.step("child", depends_on=["ghost"])
    def child(context):
        return {}

    with pytest.raises(ConfigValidationError):
        pipe.run("run-broken")


def test_pipeline_decorator_returns_original_function(tmp_path):
    """@pipe.step must return the original function unchanged."""
    pipe = Pipeline("fn-pipeline", store={"type": "filesystem", "base_dir": str(tmp_path)})

    @pipe.step("fn")
    def my_fn(context):
        return {}

    # The decorator must not replace the function
    assert callable(my_fn)
    assert my_fn.__name__ == "my_fn"


def test_pipeline_validate_catches_incomplete_registry(tmp_path):
    """WorkflowRunner.validate() fires for PrebuiltStepRegistry on __init__."""
    from runlet.artifact_store import build_store_config
    from runlet.orchestrator.config.models import PipelineConfig, StepConfig
    from runlet.orchestrator.execution.runner import WorkflowRunner
    from runlet.orchestrator.graph.dag import DAG

    step_cfg = StepConfig(
        name="missing",
        module="__runlet_decorator__",
        class_name="__runlet_decorator__",
    )
    pipeline_cfg = PipelineConfig(
        name="test",
        run_id_prefix="run",
        steps=(step_cfg,),
        store=build_store_config({"type": "filesystem", "base_dir": str(tmp_path)}),
    )
    dag = DAG(pipeline_cfg)
    empty_registry = PrebuiltStepRegistry({})

    with pytest.raises(ConfigValidationError, match=r"Steps \['missing'\]"):
        WorkflowRunner(dag=dag, step_registry=empty_registry)
