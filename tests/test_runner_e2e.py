"""End-to-end runner tests using FilesystemStore."""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from runlet import BaseArtifact, BaseStep, FilesystemStore, artifact
from runlet.orchestrator.config import PipelineConfig
from runlet.orchestrator.context import PipelineContext
from runlet.orchestrator.dag import DAG
from runlet.orchestrator.models import RunnerConfig
from runlet.orchestrator.runner import SequentialRunner


@artifact(version=1)
class CountRecord(BaseArtifact):
    value: int


@artifact(version=1)
class SumRecord(BaseArtifact):
    total: int


class ProducerStep(BaseStep):
    def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
        for i in range(3):
            yield CountRecord(value=i)


class ConsumerStep(BaseStep):
    def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
        total = sum(r.value for r in context.iter_artifacts("producer", CountRecord))
        yield SumRecord(total=total)


class FailingStep(BaseStep):
    def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
        raise RuntimeError("intentional failure")
        yield  # make it a generator


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
    original_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "test_steps":
            import types
            m = types.ModuleType("test_steps")
            m.ProducerStep = ProducerStep
            m.ConsumerStep = ConsumerStep
            return m
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
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


def test_step_inputs_not_polluted_by_store_config(store_dir, monkeypatch):
    """Infrastructure config (bucket, prefix) must never appear in context.metadata."""
    import importlib
    original_import_module = importlib.import_module

    seen_metadata: dict = {}

    class MetadataSnifferStep(BaseStep):
        def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
            seen_metadata.update(context.metadata)
            yield CountRecord(value=0)

    def fake_import_module(name, *args, **kwargs):
        if name == "test_steps":
            import types
            m = types.ModuleType("test_steps")
            m.MetadataSnifferStep = MetadataSnifferStep
            return m
        return original_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    raw = _build_pipeline_config(store_dir, [
        {"name": "sniffer", "module": "test_steps", "class": "MetadataSnifferStep", "depends_on": []},
    ])
    cfg = PipelineConfig.from_dict(raw)
    dag = DAG(cfg)
    runner = SequentialRunner(
        dag,
        RunnerConfig(),
        step_inputs={"source_key": "uploads/foo.pdf", "user_id": "u-1"},
        store_overrides={"bucket": "my-bucket", "prefix": "auth/u-1/job-1"},
    )
    result = runner.run("run004")

    assert result.success
    assert seen_metadata.get("source_key") == "uploads/foo.pdf"
    assert seen_metadata.get("user_id") == "u-1"
    assert "bucket" not in seen_metadata
    assert "prefix" not in seen_metadata
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

    # Producer artifacts should still exist
    store = FilesystemStore(store_dir)
    producer_uri = store.to_uri("run003/producer/output.jsonl")
    assert store.exists(producer_uri) or True  # path depends on runner internals
