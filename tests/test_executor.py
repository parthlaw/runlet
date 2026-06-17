"""Unit tests for SequentialExecutor, ThreadedExecutor, ExecutorConfig, and build_executor."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from runlet.orchestrator.config.models import PipelineConfig
from runlet.orchestrator.config.runner import ExecutorConfig
from runlet.orchestrator.execution.executor import (
    Executor,
    SequentialExecutor,
    ThreadedExecutor,
    build_executor,
)
from runlet.orchestrator.graph.dag import DAG
from runlet.orchestrator.state.state import RunState


# ---------------------------------------------------------------------------
# Helpers — build a minimal DAG from a step list
# ---------------------------------------------------------------------------

def _make_dag(steps: list[dict]) -> DAG:
    raw = {
        "pipeline": {"name": "executor-test"},
        "store": {"type": "filesystem", "base_dir": "/tmp", "prefix": ""},
        "steps": steps,
    }
    return DAG(PipelineConfig.from_dict(raw))


def _make_state(dag: DAG) -> RunState:
    return RunState(run_id="r1", pipeline_name=dag.config.name)


def _cancel() -> threading.Event:
    return threading.Event()


# ---------------------------------------------------------------------------
# ExecutorConfig validation
# ---------------------------------------------------------------------------

class TestExecutorConfig:
    def test_sequential_type_valid(self):
        cfg = ExecutorConfig(type="sequential")
        assert cfg.type == "sequential"
        assert cfg.max_workers == 1

    def test_threaded_type_valid(self):
        cfg = ExecutorConfig(type="threaded", max_workers=4)
        assert cfg.type == "threaded"
        assert cfg.max_workers == 4

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="must be 'sequential' or 'threaded'"):
            ExecutorConfig(type="process")

    def test_zero_max_workers_raises(self):
        with pytest.raises(ValueError, match="max_workers must be >= 1"):
            ExecutorConfig(type="threaded", max_workers=0)

    def test_negative_max_workers_raises(self):
        with pytest.raises(ValueError, match="max_workers must be >= 1"):
            ExecutorConfig(type="threaded", max_workers=-1)


# ---------------------------------------------------------------------------
# build_executor factory
# ---------------------------------------------------------------------------

class TestBuildExecutor:
    def test_sequential_returns_sequential_executor(self):
        ex = build_executor(ExecutorConfig(type="sequential"))
        assert isinstance(ex, SequentialExecutor)

    def test_threaded_returns_threaded_executor(self):
        ex = build_executor(ExecutorConfig(type="threaded", max_workers=2))
        assert isinstance(ex, ThreadedExecutor)

    def test_executor_protocol_satisfied(self):
        for ex in (SequentialExecutor(), ThreadedExecutor()):
            assert isinstance(ex, Executor)


# ---------------------------------------------------------------------------
# SequentialExecutor behaviour
# ---------------------------------------------------------------------------

class TestSequentialExecutor:
    def test_single_step_executes(self):
        dag = _make_dag([{"name": "a", "module": "m", "class": "C"}])
        state = _make_state(dag)
        executed: list[str] = []

        SequentialExecutor().run(dag, state, executed.append, _cancel())

        assert executed == ["a"]

    def test_linear_chain_executes_in_order(self):
        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C", "depends_on": ["a"]},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["b"]},
        ])
        state = _make_state(dag)
        executed: list[str] = []

        SequentialExecutor().run(dag, state, executed.append, _cancel())

        assert executed == ["a", "b", "c"]

    def test_fan_out_both_branches_run(self):
        dag = _make_dag([
            {"name": "root", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C", "depends_on": ["root"]},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["root"]},
        ])
        state = _make_state(dag)
        executed: list[str] = []

        SequentialExecutor().run(dag, state, executed.append, _cancel())

        assert executed[0] == "root"
        assert set(executed[1:]) == {"b", "c"}

    def test_fan_in_runs_after_both_parents(self):
        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C"},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["a", "b"]},
        ])
        state = _make_state(dag)
        executed: list[str] = []

        SequentialExecutor().run(dag, state, executed.append, _cancel())

        assert set(executed[:2]) == {"a", "b"}
        assert executed[2] == "c"

    def test_cancel_event_stops_execution(self):
        cancel = _cancel()
        cancel.set()

        dag = _make_dag([{"name": "a", "module": "m", "class": "C"}])
        state = _make_state(dag)
        executed: list[str] = []

        SequentialExecutor().run(dag, state, executed.append, cancel)

        assert executed == []

    def test_exception_from_execute_fn_propagates(self):
        dag = _make_dag([{"name": "a", "module": "m", "class": "C"}])
        state = _make_state(dag)

        def explode(name: str) -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            SequentialExecutor().run(dag, state, explode, _cancel())

    def test_exception_stops_further_steps(self):
        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C", "depends_on": ["a"]},
        ])
        state = _make_state(dag)
        executed: list[str] = []

        def execute_fn(name: str) -> None:
            executed.append(name)
            if name == "a":
                raise RuntimeError("a failed")

        with pytest.raises(RuntimeError):
            SequentialExecutor().run(dag, state, execute_fn, _cancel())

        assert executed == ["a"]   # b must not run


# ---------------------------------------------------------------------------
# RunnerConfig executor parsing
# ---------------------------------------------------------------------------

class TestRunnerConfigExecutorParsing:

    def test_default_is_sequential(self):
        from runlet.orchestrator.config.runner import RunnerConfig
        cfg = RunnerConfig.from_dict({})
        assert cfg.executor.type == "sequential"

    def test_explicit_sequential_block(self):
        from runlet.orchestrator.config.runner import RunnerConfig
        cfg = RunnerConfig.from_dict({"executor": {"type": "sequential"}})
        assert cfg.executor.type == "sequential"

    def test_explicit_threaded_block(self):
        from runlet.orchestrator.config.runner import RunnerConfig
        cfg = RunnerConfig.from_dict({"executor": {"type": "threaded", "max_workers": 3}})
        assert cfg.executor.type == "threaded"
        assert cfg.executor.max_workers == 3
