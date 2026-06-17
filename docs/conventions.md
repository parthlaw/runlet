# Conventions

## Adding a Custom Step

A step is a class that inherits from the base step abstraction and implements a single method that accepts a read-only runtime context and returns a JSON-serializable dict. The method must not modify any shared state outside the context.

Config accessors provided by the base class should be used to read step-specific configuration rather than accessing the raw config dict directly.

Optional lifecycle methods (`validate_config`, `teardown`) may be overridden when needed.

## Registering a Custom Artifact Store

An artifact store is a class that inherits from the artifact store abstraction and implements its upload/download/existence/deletion contract. It is registered under a string key before the runner is built. The pipeline config references the store by that key.

Custom stores must handle their own URI scheme and must guarantee that a URI produced by `upload_json` or `upload_file` is resolvable by the corresponding `download_*` method on the same or a differently-constructed instance pointing to the same backing storage.

## Registering a Custom Metastore

A metastore is a class that inherits from the run metastore abstraction and implements the run and step lifecycle recording contract. It is registered under a string key before the runner is built.

Custom metastores must be thread-safe: the runner may call metastore methods concurrently from multiple step-execution threads.

## Step Output Contract

Every step must return a JSON-serializable dict. Returning `None`, a non-dict, or a dict containing non-JSON-serializable values will cause a runtime error. If a step produces large data (files, arrays, binary payloads), the data must be written to the artifact store and only its URI placed in the output dict.

## Large Data Convention

Steps that produce data too large to hold in memory or in a JSON dict write it to the artifact store via the context's store reference and place the resulting URI in the output dict. Downstream steps retrieve the data by reading that URI from the upstream step's output and calling the corresponding download method.

## Optional Dependencies

Optional integrations are gated behind install extras. A step or store that requires an optional dependency must document which extra to install. The package does not import optional dependencies at load time — they are resolved on first use. Import errors for optional dependencies will surface at runtime, not at package import time.

## Selecting an Executor

Two executors are built in:

| Type | Behaviour | Config key |
|---|---|---|
| `SequentialExecutor` | Runs steps one at a time in the caller's thread. No thread pool. Default. | `"sequential"` |
| `ThreadedExecutor` | Dispatches independent steps to a bounded thread pool for parallel execution. | `"threaded"` |

The executor is configured in the `runner` block of the pipeline JSON config:

```json
"runner": {
  "executor": {
    "type": "threaded",
    "max_workers": 4
  }
}
```

If the `executor` block is omitted the runner defaults to `SequentialExecutor`.

`max_workers` is only meaningful for `"threaded"`; it is ignored by `"sequential"`.

## Custom Executors

When the built-in executors do not meet your scheduling requirements, subclass
`BaseExecutor` and pass an instance directly to `WorkflowRunner` or
`build_runner`. The pipeline config's `executor` block is ignored when a
custom instance is provided.

```python
from runlet import BaseExecutor, build_runner

class MyExecutor(BaseExecutor):
    def execute_batch(self, ready_pool, run_step, on_complete):
        ...

runner = build_runner("pipeline.json", executor=MyExecutor())
runner.run("my-run-id")
```

### What runlet handles for you

- **Dependency resolution** — which steps are ready to run (Kahn's algorithm)
- **Cancellation** — checking the cancel signal between dispatch cycles
- **Exception propagation** — exceptions from `run_step` surface to the runner

### What you implement: `execute_batch`

```python
def execute_batch(
    self,
    ready_pool: list[str],      # live, mutable — see contract below
    run_step: Callable[[str], None],
    on_complete: Callable[[str], None],
) -> None:
```

`execute_batch` is called whenever steps become available to run. It must
drain `ready_pool` completely before returning.

#### The `ready_pool` contract

`ready_pool` is the **same list object** the base class maintains internally.
It is not a snapshot. When you call `on_complete(step_name)`, the base class
immediately appends any newly-unlocked dependent steps to it. Your dispatch
loop sees those additions on the next iteration.

This is what enables correct priority scheduling: `min(ready_pool, ...)` at
the top of each loop iteration always reflects the current state of the DAG,
not a fixed snapshot taken at the moment `execute_batch` was called.

#### `on_complete` must always be called

Call `on_complete(step_name)` after every step — including steps where you
chose not to call `run_step` (e.g. a dry-run executor). The callback is how
runlet learns a step has finished and unlocks its dependents. Skipping it
silently stalls all downstream steps.

#### Do not use a `for` loop over `ready_pool`

A `for` loop captures the list contents at the moment iteration begins. Steps
appended to `ready_pool` by `on_complete` during the loop body are invisible
to the iterator and will never run.

```python
# WRONG — misses steps unlocked mid-loop
for step in ready_pool:
    run_step(step)
    on_complete(step)

# CORRECT — sees newly-ready steps on every iteration
while ready_pool:
    step = ready_pool.pop(0)
    run_step(step)
    on_complete(step)
```

#### Thread safety for parallel executors

`ready_pool` is a plain `list` — it is not thread-safe. If your executor
dispatches steps from multiple threads, guard all reads and pops with a lock:

```python
lock = threading.Lock()

def dispatch_one():
    with lock:
        if not ready_pool:
            return
        step = ready_pool.pop(0)
    run_step(step)
    with lock:
        on_complete(step)  # on_complete appends to ready_pool — lock required
```

#### Do not swallow exceptions from `run_step`

`run_step` raises when a step fails. Let the exception propagate. Catching
and suppressing it prevents runlet from recording the failure and cancelling
the run correctly.

### Examples

**Sequential with custom ordering:**

```python
class AlphaExecutor(BaseExecutor):
    """Runs steps in strict alphabetical order, regardless of DAG topology."""

    def execute_batch(self, ready_pool, run_step, on_complete):
        while ready_pool:
            step = min(ready_pool)       # alphabetically first
            ready_pool.remove(step)
            run_step(step)
            on_complete(step)            # may append new steps to ready_pool
```

**Priority-based scheduling:**

```python
PRIORITY = {"validate": 0, "transform": 1, "load": 2}

class PriorityExecutor(BaseExecutor):
    """Runs the highest-priority ready step first, re-evaluating after each completion."""

    def execute_batch(self, ready_pool, run_step, on_complete):
        while ready_pool:
            step = min(ready_pool, key=lambda s: PRIORITY.get(s, 99))
            ready_pool.remove(step)
            run_step(step)
            on_complete(step)   # newly-unlocked steps enter ready_pool immediately
```

**Parallel with bounded concurrency:**

```python
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

class BoundedParallelExecutor(BaseExecutor):
    def __init__(self, max_concurrent: int = 4) -> None:
        self._max_concurrent = max_concurrent

    def execute_batch(self, ready_pool, run_step, on_complete):
        lock = threading.Lock()
        in_flight: dict[str, object] = {}

        with ThreadPoolExecutor(max_workers=self._max_concurrent) as pool:
            while True:
                with lock:
                    # Fill available slots
                    while ready_pool and len(in_flight) < self._max_concurrent:
                        step = ready_pool.pop(0)
                        future = pool.submit(run_step, step)
                        in_flight[step] = future

                    if not in_flight:
                        break  # nothing running and nothing ready — done

                futures = list(in_flight.values())
                done, _ = wait(futures, return_when=FIRST_COMPLETED)

                for future in done:
                    with lock:
                        step = next(k for k, v in in_flight.items() if v is future)
                        del in_flight[step]
                    future.result()         # re-raises on step failure
                    with lock:
                        on_complete(step)   # unlocks dependents into ready_pool
```

**Dry-run (print execution plan without running steps):**

```python
class DryRunExecutor(BaseExecutor):
    def execute_batch(self, ready_pool, run_step, on_complete):
        while ready_pool:
            step = ready_pool.pop(0)
            print(f"[dry-run] would execute: {step}")
            on_complete(step)   # do NOT call run_step — still must call on_complete
```

## Extending the Registry

Both the artifact store registry and the metastore registry accept new entries at any point before the runner is built. Registration is global within a process. There is no unregister operation — registrations persist for the lifetime of the process.
