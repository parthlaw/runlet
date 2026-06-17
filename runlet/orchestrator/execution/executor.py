"""Executor abstractions, implementations, and factory for DAG step scheduling."""

from __future__ import annotations

import concurrent.futures
import threading
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from runlet.orchestrator.config.runner import ExecutorConfig
from runlet.orchestrator.graph.dag import DAG
from runlet.orchestrator.state.state import RunState

__all__ = [
    "BaseExecutor",
    "Executor",
    "ExecutorConfig",
    "SequentialExecutor",
    "ThreadedExecutor",
    "build_executor",
]


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Executor(Protocol):
    """Structural protocol satisfied by all executor implementations."""

    def run(
        self,
        dag: DAG,
        state: RunState,
        execute_fn: Callable[[str], None],
        cancel_event: threading.Event,
    ) -> None:
        ...


# ---------------------------------------------------------------------------
# Base class for custom executors
# ---------------------------------------------------------------------------

class BaseExecutor:
    """Base class for custom executor implementations.

    Subclass this and implement :meth:`execute_batch`. Runlet handles
    dependency resolution, cancellation checking, and exception propagation.
    You handle how ready steps are dispatched.

    The ``ready_pool`` passed to :meth:`execute_batch` is a **live, mutable
    list** shared with the base class. Calling ``on_complete(step_name)``
    appends newly-unlocked steps to it immediately, so subsequent iterations
    of your dispatch loop see up-to-date scheduling candidates.

    Example — minimal sequential custom executor::

        class MyExecutor(BaseExecutor):
            def execute_batch(self, ready_pool, run_step, on_complete):
                while ready_pool:
                    step = ready_pool.pop(0)
                    run_step(step)
                    on_complete(step)

    Example — priority-aware executor::

        PRIORITY = {"validate": 0, "transform": 1, "upload": 2}

        class PriorityExecutor(BaseExecutor):
            def execute_batch(self, ready_pool, run_step, on_complete):
                while ready_pool:
                    step = min(ready_pool, key=lambda s: PRIORITY.get(s, 99))
                    ready_pool.remove(step)
                    run_step(step)
                    on_complete(step)   # may append new steps to ready_pool
    """

    def execute_batch(
        self,
        ready_pool: list[str],
        run_step: Callable[[str], None],
        on_complete: Callable[[str], None],
    ) -> None:
        """Dispatch all steps in *ready_pool* to completion.

        Parameters
        ----------
        ready_pool:
            **Live, mutable list** of step names whose dependencies have all
            completed. This is the same list object the base class maintains
            internally — mutations are visible immediately.

            Your implementation must drain this list completely before
            returning (i.e. keep looping until ``ready_pool`` is empty).
            Steps that are still in the list when you return will never run.

        run_step:
            Execute a step by name. Raises on step failure — let exceptions
            propagate; do not swallow them.

        on_complete:
            Call ``on_complete(step_name)`` after each step finishes
            (even in a dry-run where you skip ``run_step``). The base class
            uses this callback to unlock dependent steps and append them to
            ``ready_pool``. Skipping this call will silently stall all
            downstream steps.

        .. warning::

            Do **not** iterate ``ready_pool`` with a ``for`` loop. A ``for``
            loop snapshots the list at the start of the iteration, so steps
            appended by ``on_complete`` will be missed.

            Correct::

                while ready_pool:
                    step = ready_pool.pop(0)
                    run_step(step)
                    on_complete(step)

            Incorrect::

                for step in ready_pool:   # snapshot — misses newly ready steps
                    run_step(step)
                    on_complete(step)

        .. note::

            For parallel custom executors that access ``ready_pool`` from
            multiple threads, guard ``pop`` calls with a lock. ``ready_pool``
            is a plain :class:`list` and is not thread-safe.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement execute_batch()"
        )

    # Internal — satisfies the Executor protocol. Do not override.
    def run(
        self,
        dag: DAG,
        state: RunState,
        execute_fn: Callable[[str], None],
        cancel_event: threading.Event,
    ) -> None:
        in_degree = dag.compute_in_degrees()
        ready_pool: list[str] = sorted(
            n for n, d in in_degree.items() if d == 0
        )

        def on_complete(step_name: str) -> None:
            for dep in dag.dependents_of(step_name):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    ready_pool.append(dep)

        while ready_pool:
            if cancel_event.is_set():
                break
            self.execute_batch(ready_pool, execute_fn, on_complete)


# ---------------------------------------------------------------------------
# Built-in implementations
# ---------------------------------------------------------------------------

class SequentialExecutor:
    """
    Executes DAG steps one at a time in topological order.

    No thread pool is used. Each step runs synchronously in the caller's
    thread. Exceptions from ``execute_fn`` propagate immediately.
    """

    def run(
        self,
        dag: DAG,
        state: RunState,
        execute_fn: Callable[[str], None],
        cancel_event: threading.Event,
    ) -> None:
        in_degree = dag.compute_in_degrees()
        ready: list[str] = sorted(n for n, d in in_degree.items() if d == 0)

        while ready:
            if cancel_event.is_set():
                break
            step_name = ready.pop(0)
            execute_fn(step_name)  # raises on failure — propagates to runner
            for dependent in dag.dependents_of(step_name):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)
            ready.sort()


class ThreadedExecutor:
    """
    Executes DAG steps in a bounded thread pool using Kahn's algorithm.

    Steps are dispatched to the pool as soon as their in-degree reaches zero
    (all dependencies done). With max_workers=1 this is equivalent to
    sequential execution.
    """

    def __init__(self, max_workers: int = 1) -> None:
        self._max_workers = max(1, max_workers)

    def run(
        self,
        dag: DAG,
        state: RunState,
        execute_fn: Callable[[str], None],
        cancel_event: threading.Event,
    ) -> None:
        in_degree = dag.compute_in_degrees()
        ready: list[str] = sorted(n for n, d in in_degree.items() if d == 0)
        in_flight: dict[str, concurrent.futures.Future[None]] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            while ready or in_flight:
                if cancel_event.is_set():
                    break

                for step_name in sorted(ready):
                    in_flight[step_name] = pool.submit(execute_fn, step_name)
                ready.clear()

                done, _ = concurrent.futures.wait(
                    list(in_flight.values()),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                    timeout=1.0,
                )

                for future in done:
                    step_name = next(k for k, v in in_flight.items() if v is future)
                    del in_flight[step_name]

                    exc = future.exception()
                    if exc:
                        cancel_event.set()
                        raise exc

                    for dependent in dag.dependents_of(step_name):
                        in_degree[dependent] -= 1
                        if in_degree[dependent] == 0:
                            ready.append(dependent)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_executor(config: ExecutorConfig) -> Executor:
    """Construct and return the executor specified by *config*."""
    if config.type == "sequential":
        return SequentialExecutor()
    if config.type == "threaded":
        return ThreadedExecutor(max_workers=config.max_workers)
    raise ValueError(f"Unknown executor type: {config.type!r}")  # pragma: no cover
