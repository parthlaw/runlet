"""End-to-end runner tests using FilesystemStore."""
from __future__ import annotations

from typing import Any

import pytest

from runlet import BaseStep
from runlet.orchestrator.config import PipelineConfig
from runlet.orchestrator.config.runner import ExecutorConfig, RunnerConfig
from runlet.orchestrator.context.step_context import StepContext
from runlet.orchestrator.execution.runner import WorkflowRunner
from runlet.orchestrator.graph.dag import DAG


class ProducerStep(BaseStep):
    def execute(self, context: StepContext) -> dict[str, Any]:
        return {"values": [0, 1, 2], "count": 3}


class ConsumerStep(BaseStep):
    def execute(self, context: StepContext) -> dict[str, Any]:
        upstream = context.get_output("producer")
        total = sum(upstream["values"])
        return {"total": total}


class FailingStep(BaseStep):
    def execute(self, context: StepContext) -> dict[str, Any]:
        raise RuntimeError("intentional failure")


def _build_pipeline_config(store_dir: str, steps_cfg: list) -> dict:
    return {
        "pipeline": {"name": "e2e-test"},
        "store": {"type": "filesystem", "base_dir": store_dir, "prefix": ""},
        "steps": steps_cfg,
    }


@pytest.fixture
def store_dir(tmp_path):
    return str(tmp_path)


def test_two_step_pipeline_success(store_dir, monkeypatch):
    # Patch dynamic import so runner can find our test steps
    import importlib
    original_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == "test_steps":
            import types
            m = types.ModuleType("test_steps")
            m.ProducerStep = ProducerStep
            m.ConsumerStep = ConsumerStep
            return m
        return original_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    raw = _build_pipeline_config(store_dir, [
        {"name": "producer", "module": "test_steps", "class": "ProducerStep", "depends_on": []},
        {
            "name": "consumer", "module": "test_steps", "class": "ConsumerStep",
            "depends_on": ["producer"],
        },
    ])
    cfg = PipelineConfig.from_dict(raw)
    dag = DAG(cfg)
    runner = WorkflowRunner(dag, RunnerConfig())
    result = runner.run("run001")

    assert result.success
    assert result.steps_executed == ["producer", "consumer"]
    assert result.steps_skipped == []
    assert result.failed_step is None


def test_resume_skips_completed_steps(store_dir, tmp_path, monkeypatch):
    import importlib
    original_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == "test_steps":
            import types
            m = types.ModuleType("test_steps")
            m.ProducerStep = ProducerStep
            m.ConsumerStep = ConsumerStep
            return m
        return original_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    from runlet.metastore.stores.sqlite import SqliteConfig, SqliteMetastore

    # Use a file-backed SQLite DB so the data persists after the first runner closes
    # its connection.
    db_path = str(tmp_path / "meta.db")

    raw = _build_pipeline_config(store_dir, [
        {"name": "producer", "module": "test_steps", "class": "ProducerStep", "depends_on": []},
        {
            "name": "consumer", "module": "test_steps", "class": "ConsumerStep",
            "depends_on": ["producer"],
        },
    ])
    cfg = PipelineConfig.from_dict(raw)
    dag = DAG(cfg)

    # First run — populates metastore; runner closes the connection when done.
    runner = WorkflowRunner(
        dag, RunnerConfig(), metastore=SqliteMetastore(SqliteConfig(db_path=db_path))
    )
    result1 = runner.run("run002")
    assert result1.success

    # Resume run — opens a fresh connection to the same file and reads prior step records.
    runner2 = WorkflowRunner(
        dag, RunnerConfig(resume=True), metastore=SqliteMetastore(SqliteConfig(db_path=db_path))
    )
    result2 = runner2.run("run002")
    assert result2.steps_skipped == ["producer", "consumer"]
    assert result2.steps_executed == []


def test_downstream_reads_upstream_output(store_dir, monkeypatch):
    """ConsumerStep must be able to read ProducerStep's output dict."""
    received: list[dict] = []

    class CapturingConsumer(BaseStep):
        def execute(self, context: StepContext) -> dict[str, Any]:
            out = context.get_output("producer")
            received.append(out)
            return {"captured": True}

    import importlib
    original = importlib.import_module

    def fake(name, *args, **kwargs):
        if name == "test_steps":
            import types
            m = types.ModuleType("test_steps")
            m.ProducerStep = ProducerStep
            m.CapturingConsumer = CapturingConsumer
            return m
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake)

    raw = _build_pipeline_config(store_dir, [
        {"name": "producer", "module": "test_steps", "class": "ProducerStep", "depends_on": []},
        {
            "name": "consumer", "module": "test_steps", "class": "CapturingConsumer",
            "depends_on": ["producer"],
        },
    ])
    cfg = PipelineConfig.from_dict(raw)
    dag = DAG(cfg)
    runner = WorkflowRunner(dag, RunnerConfig())
    result = runner.run("run004")

    assert result.success
    assert received == [{"values": [0, 1, 2], "count": 3}]


def test_failing_step_returns_failed_result(store_dir, monkeypatch):
    import importlib
    original_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == "test_steps":
            import types
            m = types.ModuleType("test_steps")
            m.ProducerStep = ProducerStep
            m.FailingStep = FailingStep
            return m
        return original_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    raw = _build_pipeline_config(store_dir, [
        {"name": "producer", "module": "test_steps", "class": "ProducerStep", "depends_on": []},
        {
            "name": "failing", "module": "test_steps", "class": "FailingStep",
            "depends_on": ["producer"],
        },
    ])
    cfg = PipelineConfig.from_dict(raw)
    dag = DAG(cfg)
    runner = WorkflowRunner(dag, RunnerConfig())
    result = runner.run("run003")

    assert not result.success
    assert result.failed_step == "failing"
    assert "producer" in result.steps_executed


def test_pipeline_decorator_resume(store_dir, tmp_path):
    """Pipeline.run(resume=True) skips steps already recorded in the metastore."""
    from runlet import Pipeline
    from runlet.metastore.stores.sqlite import SqliteConfig, SqliteMetastore

    db_path = str(tmp_path / "meta.db")

    pipe = Pipeline(
        "decorator-resume-test",
        store={"type": "filesystem", "base_dir": store_dir},
    )

    executions: list[str] = []

    @pipe.step("step_a")
    def step_a(context):
        executions.append("step_a")
        return {"value": 1}

    @pipe.step("step_b", depends_on=["step_a"])
    def step_b(context):
        executions.append("step_b")
        return {"value": 2}

    # First run — both steps execute and are recorded in the metastore.
    result1 = pipe.run(
        "dec-run001",
        metastore=SqliteMetastore(SqliteConfig(db_path=db_path)),
    )
    assert result1.success
    assert executions == ["step_a", "step_b"]

    executions.clear()

    # Resume run — both steps are already in the metastore as SUCCESS, so skipped.
    result2 = pipe.run(
        "dec-run001",
        resume=True,
        metastore=SqliteMetastore(SqliteConfig(db_path=db_path)),
    )
    assert result2.success
    assert result2.steps_skipped == ["step_a", "step_b"]
    assert result2.steps_executed == []
    assert executions == []


# ---------------------------------------------------------------------------
# Executor selection via RunnerConfig
# ---------------------------------------------------------------------------

class ProducerForExecutorTest(BaseStep):
    def execute(self, context: StepContext) -> dict[str, Any]:
        return {"value": 1}


class ConsumerForExecutorTest(BaseStep):
    def execute(self, context: StepContext) -> dict[str, Any]:
        return {"received": context.get_output("producer")["value"]}


def _patch_executor_test_steps(monkeypatch) -> None:
    import importlib
    import types
    orig = importlib.import_module

    def fake(name, *a, **kw):
        if name == "executor_test_steps":
            m = types.ModuleType("executor_test_steps")
            m.ProducerForExecutorTest = ProducerForExecutorTest
            m.ConsumerForExecutorTest = ConsumerForExecutorTest
            return m
        return orig(name, *a, **kw)

    monkeypatch.setattr(importlib, "import_module", fake)


def _executor_test_raw(store_dir: str) -> dict:
    return {
        "pipeline": {"name": "executor-selection-e2e"},
        "store": {"type": "filesystem", "base_dir": store_dir, "prefix": ""},
        "steps": [
            {"name": "producer", "module": "executor_test_steps",
             "class": "ProducerForExecutorTest", "depends_on": []},
            {"name": "consumer", "module": "executor_test_steps",
             "class": "ConsumerForExecutorTest", "depends_on": ["producer"]},
        ],
    }


def test_sequential_executor_via_config(store_dir, monkeypatch):
    """RunnerConfig with executor type=sequential runs the pipeline successfully."""
    _patch_executor_test_steps(monkeypatch)
    cfg = PipelineConfig.from_dict(_executor_test_raw(store_dir))
    dag = DAG(cfg)
    runner = WorkflowRunner(dag, RunnerConfig(executor=ExecutorConfig(type="sequential")))
    result = runner.run("seq-exec-run")

    assert result.success
    assert result.steps_executed == ["producer", "consumer"]


def test_threaded_executor_via_config(store_dir, monkeypatch):
    """RunnerConfig with executor type=threaded runs the pipeline successfully."""
    _patch_executor_test_steps(monkeypatch)
    cfg = PipelineConfig.from_dict(_executor_test_raw(store_dir))
    dag = DAG(cfg)
    runner = WorkflowRunner(
        dag, RunnerConfig(executor=ExecutorConfig(type="threaded", max_workers=2))
    )
    result = runner.run("threaded-exec-run")

    assert result.success
    assert result.steps_executed == ["producer", "consumer"]


def test_executor_selected_from_pipeline_json(store_dir, monkeypatch):
    """Executor block in the pipeline JSON runner section is respected."""
    _patch_executor_test_steps(monkeypatch)
    raw = _executor_test_raw(store_dir)
    raw["runner"] = {"executor": {"type": "sequential"}}
    cfg = PipelineConfig.from_dict(raw)
    dag = DAG(cfg)
    runner = WorkflowRunner(dag)
    result = runner.run("json-exec-run")

    assert result.success
    assert cfg.runner.executor.type == "sequential"
