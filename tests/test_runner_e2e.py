"""End-to-end runner tests using FilesystemStore."""
from __future__ import annotations

from typing import Any

import pytest

from runlet import BaseStep, FilesystemStore
from runlet.orchestrator.config import PipelineConfig
from runlet.orchestrator.context import PipelineContext
from runlet.orchestrator.dag import DAG
from runlet.orchestrator.models import RunnerConfig
from runlet.orchestrator.runner import SequentialRunner


class ProducerStep(BaseStep):
    def execute(self, context: PipelineContext) -> dict[str, Any]:
        return {"values": [0, 1, 2], "count": 3}


class ConsumerStep(BaseStep):
    def execute(self, context: PipelineContext) -> dict[str, Any]:
        upstream = context.get_output("producer")
        total = sum(upstream["values"])
        return {"total": total}


class FailingStep(BaseStep):
    def execute(self, context: PipelineContext) -> dict[str, Any]:
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
    runner = SequentialRunner(dag, RunnerConfig())
    result = runner.run("run001")

    assert result.success
    assert result.steps_executed == ["producer", "consumer"]
    assert result.steps_skipped == []
    assert result.failed_step is None


def test_resume_skips_completed_steps(store_dir, monkeypatch):
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

    # First run
    runner = SequentialRunner(dag, RunnerConfig())
    result1 = runner.run("run002")
    assert result1.success

    # Resume run
    runner2 = SequentialRunner(dag, RunnerConfig(resume=True))
    result2 = runner2.run("run002")
    assert result2.steps_skipped == ["producer", "consumer"]
    assert result2.steps_executed == []


def test_downstream_reads_upstream_output(store_dir, monkeypatch):
    """ConsumerStep must be able to read ProducerStep's output dict."""
    received: list[dict] = []

    class CapturingConsumer(BaseStep):
        def execute(self, context: PipelineContext) -> dict[str, Any]:
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
    runner = SequentialRunner(dag, RunnerConfig())
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
    runner = SequentialRunner(dag, RunnerConfig())
    result = runner.run("run003")

    assert not result.success
    assert result.failed_step == "failing"
    assert "producer" in result.steps_executed
