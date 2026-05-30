"""ThreadedExecutor — bounded parallel DAG execution."""

from __future__ import annotations

import concurrent.futures
import threading
from collections.abc import Callable

from runlet.orchestrator.dag import DAG
from runlet.orchestrator.state import RunState


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
