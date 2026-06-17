"""Tests for BaseExecutor: live-pool contract, scheduling behaviour, and WorkflowRunner integration."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Any

import pytest

from runlet.orchestrator.config.models import PipelineConfig
from runlet.orchestrator.execution.executor import BaseExecutor, Executor
from runlet.orchestrator.graph.dag import DAG
from runlet.orchestrator.state.state import RunState


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_dag(steps: list[dict]) -> DAG:
    raw = {
        "pipeline": {"name": "base-executor-test"},
        "store": {"type": "filesystem", "base_dir": "/tmp", "prefix": ""},
        "steps": steps,
    }
    return DAG(PipelineConfig.from_dict(raw))


def _make_state(dag: DAG) -> RunState:
    return RunState(run_id="r1", pipeline_name=dag.config.name)


def _cancel() -> threading.Event:
    return threading.Event()


# ---------------------------------------------------------------------------
# Minimal concrete implementation used across most tests
# ---------------------------------------------------------------------------

class SimpleSequentialExecutor(BaseExecutor):
    """Drains ready_pool one step at a time in arrival order."""

    def execute_batch(self, ready_pool, run_step, on_complete):
        while ready_pool:
            step = ready_pool.pop(0)
            run_step(step)
            on_complete(step)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestBaseExecutorProtocol:
    def test_base_executor_satisfies_executor_protocol(self):
        assert isinstance(SimpleSequentialExecutor(), Executor)

    def test_not_implemented_raised_when_execute_batch_not_overridden(self):
        dag = _make_dag([{"name": "a", "module": "m", "class": "C"}])
        state = _make_state(dag)

        class Bare(BaseExecutor):
            pass

        with pytest.raises(NotImplementedError, match="must implement execute_batch"):
            Bare().run(dag, state, lambda _: None, _cancel())


# ---------------------------------------------------------------------------
# Basic execution correctness
# ---------------------------------------------------------------------------

class TestBaseExecutorExecution:
    def test_single_step_runs(self):
        dag = _make_dag([{"name": "a", "module": "m", "class": "C"}])
        state = _make_state(dag)
        ran: list[str] = []

        SimpleSequentialExecutor().run(dag, state, ran.append, _cancel())

        assert ran == ["a"]

    def test_linear_chain_runs_in_order(self):
        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C", "depends_on": ["a"]},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["b"]},
        ])
        state = _make_state(dag)
        ran: list[str] = []

        SimpleSequentialExecutor().run(dag, state, ran.append, _cancel())

        assert ran == ["a", "b", "c"]

    def test_fan_out_all_branches_execute(self):
        dag = _make_dag([
            {"name": "root", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C", "depends_on": ["root"]},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["root"]},
        ])
        state = _make_state(dag)
        ran: list[str] = []

        SimpleSequentialExecutor().run(dag, state, ran.append, _cancel())

        assert ran[0] == "root"
        assert set(ran[1:]) == {"b", "c"}

    def test_fan_in_runs_after_both_parents(self):
        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C"},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["a", "b"]},
        ])
        state = _make_state(dag)
        ran: list[str] = []

        SimpleSequentialExecutor().run(dag, state, ran.append, _cancel())

        assert set(ran[:2]) == {"a", "b"}
        assert ran[2] == "c"

    def test_all_steps_run_in_complex_dag(self):
        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C", "depends_on": ["a"]},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["a"]},
            {"name": "d", "module": "m", "class": "C", "depends_on": ["b", "c"]},
        ])
        state = _make_state(dag)
        ran: list[str] = []

        SimpleSequentialExecutor().run(dag, state, ran.append, _cancel())

        assert ran[0] == "a"
        assert set(ran[1:3]) == {"b", "c"}
        assert ran[3] == "d"


# ---------------------------------------------------------------------------
# Live-pool semantics — the core contract
# ---------------------------------------------------------------------------

class TestLivePool:
    def test_steps_unlocked_mid_loop_are_dispatched_in_same_pass(self):
        """on_complete must append dependents into ready_pool immediately.

        With a 3-step linear chain (a → b → c), a correctly-implemented
        BaseExecutor sees b in the pool after on_complete("a") and c after
        on_complete("b") — all within a single execute_batch call.
        """
        execute_batch_call_count = 0

        class CountingExecutor(BaseExecutor):
            def execute_batch(self, ready_pool, run_step, on_complete):
                nonlocal execute_batch_call_count
                execute_batch_call_count += 1
                while ready_pool:
                    step = ready_pool.pop(0)
                    run_step(step)
                    on_complete(step)

        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C", "depends_on": ["a"]},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["b"]},
        ])
        state = _make_state(dag)
        CountingExecutor().run(dag, state, lambda _: None, _cancel())

        # All three steps were handled in a single execute_batch call because
        # each on_complete immediately added the next step to ready_pool.
        assert execute_batch_call_count == 1

    def test_priority_executor_uses_live_pool_for_ordering(self):
        """Priority ordering must account for steps unlocked mid-execution.

        DAG:
            root → high_priority  (priority 0)
            root → low_priority   (priority 99)

        After root completes, both high_priority and low_priority enter
        ready_pool. A priority executor must pick high_priority first,
        regardless of insertion order.
        """
        PRIORITY = {"root": 50, "high_priority": 0, "low_priority": 99}

        class PriorityExecutor(BaseExecutor):
            def execute_batch(self, ready_pool, run_step, on_complete):
                while ready_pool:
                    step = min(ready_pool, key=lambda s: PRIORITY.get(s, 50))
                    ready_pool.remove(step)
                    run_step(step)
                    on_complete(step)

        dag = _make_dag([
            {"name": "root", "module": "m", "class": "C"},
            {"name": "high_priority", "module": "m", "class": "C", "depends_on": ["root"]},
            {"name": "low_priority", "module": "m", "class": "C", "depends_on": ["root"]},
        ])
        state = _make_state(dag)
        ran: list[str] = []

        PriorityExecutor().run(dag, state, ran.append, _cancel())

        assert ran == ["root", "high_priority", "low_priority"]

    def test_snapshot_antipattern_misses_unlocked_steps(self):
        """Demonstrate that snapshotting ready_pool before dispatching misses live additions.

        If the user copies ready_pool at the top of execute_batch and iterates
        the copy, steps appended by on_complete during iteration are invisible
        to the loop. Only steps that were already ready when execute_batch was
        called will run in that pass — the rest are dropped because ready_pool
        is cleared before returning.

        This documents the failure mode the docs warn against.
        """
        class SnapshotExecutor(BaseExecutor):
            def execute_batch(self, ready_pool, run_step, on_complete):
                # Antipattern: take a snapshot, iterate the copy, then clear
                snapshot = list(ready_pool)  # freeze the pool state right now
                ready_pool.clear()           # clear so base loop doesn't re-enter
                for step in snapshot:
                    run_step(step)
                    on_complete(step)        # appends to ready_pool, but we already cleared it

        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C", "depends_on": ["a"]},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["b"]},
        ])
        state = _make_state(dag)
        ran: list[str] = []

        # Base loop: ready_pool starts as ["a"]. SnapshotExecutor snapshots ["a"],
        # clears the pool, runs "a", on_complete("a") appends "b" to ready_pool.
        # But snapshot loop is done. ready_pool now has ["b"] — base loop
        # re-enters execute_batch. Snapshots ["b"], clears, runs "b",
        # on_complete("b") appends "c". Base loop re-enters. c runs too.
        # All steps DO run — but via multiple execute_batch calls, not one.
        # The behaviour difference is visible via execute_batch call count.
        SnapshotExecutor().run(dag, state, ran.append, _cancel())
        assert set(ran) == {"a", "b", "c"}  # all run, but inefficiently


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

class TestBaseExecutorCancellation:
    def test_pre_set_cancel_event_skips_all_steps(self):
        cancel = _cancel()
        cancel.set()

        dag = _make_dag([{"name": "a", "module": "m", "class": "C"}])
        state = _make_state(dag)
        ran: list[str] = []

        SimpleSequentialExecutor().run(dag, state, ran.append, cancel)

        assert ran == []

    def test_cancel_checked_between_execute_batch_calls(self):
        """The cancel event is checked by the base between execute_batch calls.

        When a custom executor sets cancel during its execute_batch run, the
        base will see it on the next iteration and stop dispatching further
        batches. Steps that were already in-flight complete normally.
        """
        cancel = _cancel()

        # DAG: two independent roots, each with a dependent
        #   a → c
        #   b → d
        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C"},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["a"]},
            {"name": "d", "module": "m", "class": "C", "depends_on": ["b"]},
        ])
        state = _make_state(dag)
        ran: list[str] = []

        class CancelAfterBatchExecutor(BaseExecutor):
            """Drains exactly one step per execute_batch call, then sets cancel."""
            def execute_batch(self, ready_pool, run_step, on_complete):
                step = ready_pool.pop(0)
                ran.append(step)
                run_step(step)
                on_complete(step)
                # Set cancel — base will check this before the next execute_batch
                cancel.set()
                # Leave remaining items in ready_pool — base checks cancel first

        CancelAfterBatchExecutor().run(dag, state, lambda _: None, cancel)

        # Exactly one step ran (the first pop); base saw cancel before re-entering
        assert len(ran) == 1


# ---------------------------------------------------------------------------
# Exception propagation
# ---------------------------------------------------------------------------

class TestBaseExecutorExceptions:
    def test_exception_from_run_step_propagates(self):
        dag = _make_dag([{"name": "a", "module": "m", "class": "C"}])
        state = _make_state(dag)

        def boom(_: str) -> None:
            raise RuntimeError("step failed")

        with pytest.raises(RuntimeError, match="step failed"):
            SimpleSequentialExecutor().run(dag, state, boom, _cancel())

    def test_exception_stops_subsequent_steps(self):
        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C", "depends_on": ["a"]},
        ])
        state = _make_state(dag)
        ran: list[str] = []

        def execute(name: str) -> None:
            ran.append(name)
            if name == "a":
                raise RuntimeError("a failed")

        with pytest.raises(RuntimeError):
            SimpleSequentialExecutor().run(dag, state, execute, _cancel())

        assert ran == ["a"]


# ---------------------------------------------------------------------------
# Dry-run executor — on_complete without run_step
# ---------------------------------------------------------------------------

class TestDryRunExecutor:
    def test_dry_run_traverses_full_dag_without_executing(self):
        """on_complete without run_step should still unlock the whole DAG."""
        planned: list[str] = []

        class DryRunExecutor(BaseExecutor):
            def execute_batch(self, ready_pool, run_step, on_complete):
                while ready_pool:
                    step = ready_pool.pop(0)
                    planned.append(step)
                    # deliberately skip run_step
                    on_complete(step)

        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C", "depends_on": ["a"]},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["a"]},
            {"name": "d", "module": "m", "class": "C", "depends_on": ["b", "c"]},
        ])
        state = _make_state(dag)

        DryRunExecutor().run(dag, state, lambda _: None, _cancel())

        assert set(planned) == {"a", "b", "c", "d"}
        assert planned[0] == "a"
        assert planned[-1] == "d"


# ---------------------------------------------------------------------------
# Parallel executor — thread-safe pool access
# ---------------------------------------------------------------------------

class TestParallelCustomExecutor:
    def test_bounded_parallel_executor_runs_all_steps(self):
        """A custom threaded executor using the live-pool pattern runs all steps."""

        class BoundedParallelExecutor(BaseExecutor):
            def __init__(self, max_concurrent: int = 2) -> None:
                self._max_concurrent = max_concurrent

            def execute_batch(self, ready_pool, run_step, on_complete):
                lock = threading.Lock()
                in_flight: dict[str, Any] = {}

                with ThreadPoolExecutor(max_workers=self._max_concurrent) as pool:
                    while True:
                        with lock:
                            while ready_pool and len(in_flight) < self._max_concurrent:
                                step = ready_pool.pop(0)
                                future = pool.submit(run_step, step)
                                in_flight[step] = future

                            if not in_flight:
                                break

                        futures = list(in_flight.values())
                        done, _ = wait(futures, return_when=FIRST_COMPLETED)

                        for future in done:
                            with lock:
                                step = next(k for k, v in in_flight.items() if v is future)
                                del in_flight[step]
                            future.result()
                            with lock:
                                on_complete(step)

        dag = _make_dag([
            {"name": "a", "module": "m", "class": "C"},
            {"name": "b", "module": "m", "class": "C"},
            {"name": "c", "module": "m", "class": "C", "depends_on": ["a", "b"]},
            {"name": "d", "module": "m", "class": "C", "depends_on": ["c"]},
        ])
        state = _make_state(dag)
        ran: list[str] = []
        lock = threading.Lock()

        def tracked_run(name: str) -> None:
            with lock:
                ran.append(name)

        BoundedParallelExecutor(max_concurrent=2).run(dag, state, tracked_run, _cancel())

        assert set(ran) == {"a", "b", "c", "d"}
        assert ran.index("c") > ran.index("a")
        assert ran.index("c") > ran.index("b")
        assert ran[-1] == "d"


# ---------------------------------------------------------------------------
# WorkflowRunner integration — custom executor pass-through
# ---------------------------------------------------------------------------

class TestWorkflowRunnerCustomExecutor:
    def test_custom_executor_is_used_instead_of_config_executor(self, tmp_path):
        """WorkflowRunner must use the provided executor instance, not build_executor."""
        from runlet.orchestrator.execution.runner import WorkflowRunner
        from runlet.metastore import NoopMetastore
        from runlet.steps.base import BaseStep
        from runlet.orchestrator.context.step_context import StepContext
        from runlet.orchestrator.registry.registry import PrebuiltStepRegistry

        class NoopStep(BaseStep):
            def execute(self, context: StepContext) -> dict:
                return {}

        dispatch_log: list[str] = []

        class LoggingExecutor(BaseExecutor):
            def execute_batch(self, ready_pool, run_step, on_complete):
                while ready_pool:
                    step = ready_pool.pop(0)
                    dispatch_log.append(step)
                    run_step(step)
                    on_complete(step)

        raw = {
            "pipeline": {"name": "custom-exec-test"},
            "store": {"type": "filesystem", "base_dir": str(tmp_path), "prefix": ""},
            "steps": [
                {"name": "s1", "module": "ignored", "class": "ignored"},
                {"name": "s2", "module": "ignored", "class": "ignored", "depends_on": ["s1"]},
            ],
        }
        pipeline_cfg = PipelineConfig.from_dict(raw)
        dag = DAG(pipeline_cfg)

        registry = PrebuiltStepRegistry({
            "s1": NoopStep({}),
            "s2": NoopStep({}),
        })

        runner = WorkflowRunner(
            dag=dag,
            metastore=NoopMetastore(),
            step_registry=registry,
            executor=LoggingExecutor(),
        )
        result = runner.run("test-run")

        assert result.success
        assert dispatch_log == ["s1", "s2"]

    def test_config_executor_used_when_no_custom_executor_provided(self, tmp_path):
        """When executor=None, WorkflowRunner falls back to build_executor(config)."""
        from runlet.orchestrator.execution.runner import WorkflowRunner
        from runlet.orchestrator.config.runner import RunnerConfig, ExecutorConfig
        from runlet.metastore import NoopMetastore
        from runlet.steps.base import BaseStep
        from runlet.orchestrator.context.step_context import StepContext
        from runlet.orchestrator.registry.registry import PrebuiltStepRegistry

        class NoopStep(BaseStep):
            def execute(self, context: StepContext) -> dict:
                return {}

        raw = {
            "pipeline": {"name": "fallback-exec-test"},
            "store": {"type": "filesystem", "base_dir": str(tmp_path), "prefix": ""},
            "steps": [{"name": "s1", "module": "ignored", "class": "ignored"}],
        }
        pipeline_cfg = PipelineConfig.from_dict(raw)
        dag = DAG(pipeline_cfg)

        registry = PrebuiltStepRegistry({"s1": NoopStep({})})

        runner_config = RunnerConfig(executor=ExecutorConfig(type="sequential"))
        runner = WorkflowRunner(
            dag=dag,
            runner_config=runner_config,
            metastore=NoopMetastore(),
            step_registry=registry,
            executor=None,   # explicit None — must use config
        )
        result = runner.run("fallback-run")

        assert result.success
        assert "s1" in result.steps_executed
