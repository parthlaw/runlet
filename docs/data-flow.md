# Orchestrator Component Data Flow

This diagram shows how the six subsystems inside `runlet/orchestrator/` interact during a pipeline run — what each component owns, what data it produces, and who consumes it.

---

## Component Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CALLER (Pipeline / CLI)                         │
│                     build_runner(config_path)  /  pipe.run(run_id)      │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │  config file (JSON) or decorator steps
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  CONFIG                                                                 │
│  config/models.py   →  PipelineConfig, StepConfig, ConditionConfig      │
│  config/runner.py   →  ExecutorConfig, RunnerConfig, RunResult          │
│                                                                         │
│  Parses and validates raw JSON into typed, immutable dataclasses.       │
│  Owns: pipeline name, step list, depends_on, conditions, retry,         │
│        executor choice, metastore config, artifact store config.        │
└──────────┬─────────────────────────────────────────────────────────────┘
           │  PipelineConfig
           │
           ├──────────────────────────────┐
           ▼                              ▼
┌──────────────────────┐      ┌──────────────────────────────────────────┐
│  GRAPH               │      │  REGISTRY                                │
│  graph/dag.py        │      │  registry/registry.py                    │
│                      │      │                                          │
│  Consumes:           │      │  Consumes:                               │
│    PipelineConfig    │      │    PipelineConfig (ConfigStepRegistry)   │
│                      │      │    or pre-built instances (Prebuilt-)    │
│  Produces:           │      │                                          │
│    DAG               │      │  Produces:                               │
│    · topological     │      │    BaseStep instance on get(name)        │
│      order           │      │                                          │
│    · in-degree map   │      │  Role: resolves a step name → a          │
│    · ancestor /      │      │  ready-to-execute step object.           │
│      descendant sets │      │  Called once per step per execution.     │
└──────────┬───────────┘      └───────────────────┬──────────────────────┘
           │  DAG                                  │  BaseStep
           │                                       │
           └──────────────┬────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  EXECUTION                                                              │
│                                                                         │
│  execution/runner.py  ←────────────────────── RunnerConfig              │
│    WorkflowRunner                                                       │
│    · owns the run lifecycle (start / success / failed / cancelled)      │
│    · builds STATE, CONTEXT, and the executor                            │
│    · drives the outer loop; delegates step dispatch to executor         │
│                                                                         │
│  execution/executor.py                                                  │
│    SequentialExecutor / ThreadedExecutor / build_executor               │
│    · consumes DAG (in-degree map, dependents_of)                        │
│    · consumes RunState (read — to check completion)                     │
│    · dispatches step names to StepRunner in topological order           │
│                                                                         │
│  execution/step_runner.py   ←─── RetryPolicy (execution/retry.py)      │
│    StepRunner (callable)                                                │
│    · called by executor with a step name                                │
│    · reads StepStatus from STATE to detect resume-skip                  │
│    · reads ConditionConfig → calls STATE/condition_evaluator            │
│    · calls REGISTRY.get(name) → BaseStep                               │
│    · builds StepContext view from RunContext for each dispatch          │
│    · calls step.execute(StepContext) → output dict                      │
│    · writes output to CONTEXT via RunContext._register_output           │
│    · writes step status to STATE                                        │
│    · writes lifecycle events to Metastore                               │
│                                                                         │
│  execution/retry.py                                                     │
│    RetryPolicy                                                          │
│    · consumed by StepRunner to decide should_retry and wait delay       │
└───────┬─────────────────────────────────────────────────────────────────┘
        │                     │                      │
        │ reads/writes         │ reads/writes         │ writes lifecycle
        ▼                     ▼                      ▼
┌────────────────┐  ┌──────────────────────┐  ┌─────────────────────────┐
│  STATE         │  │  CONTEXT             │  │  (Metastore — external) │
│                │  │                      │  │                         │
│  state/        │  │  context/            │  │  RunMetastore           │
│  state.py      │  │  run_context.py      │  │  · record_run_started   │
│                │  │  step_context.py     │  │  · record_step_running  │
│  RunState      │  │                      │  │  · record_step_success  │
│  · step status │  │  RunContext          │  │    (persists output)    │
│    map         │  │  (held by runner)    │  │  · record_step_failed   │
│  · run status  │  │  · _register_output()│  │  · record_run_success   │
│                │  │  · restore_outputs() │  │                         │
│  In-memory.    │  │  · list_outputs()    │  │  Durable, survives      │
│  Drives        │  │  · get_output()      │  │  process restart.       │
│  scheduling    │  │  · has_output()      │  │  Used for resume and    │
│  decisions.    │  │                      │  │  observability only.    │
│                │  │  StepContext         │  └─────────────────────────┘
│  state/        │  │  (given to steps)    │
│  condition_    │  │  · get_output()      │
│  evaluator.py  │  │  · has_output()      │
│                │  │  · list_outputs()    │
│  evaluate_     │  │  · artifact_store    │
│  condition()   │  │  · metadata          │
│  · reads       │  │  · llm               │
│    upstream    │  │  · is_cancelled()    │
│    output via  │  │                      │
│    context.    │  │  Data boundary:      │
│    get_output()│  │  RunContext is held  │
└────────────────┘  │  by the runner only. │
                    │  Steps receive a     │
                    │  StepContext view —  │
                    │  no write methods,   │
                    │  structurally        │
                    │  enforced.           │
                    └──────────────────────┘
```

---

## Data Flow: Single Run Lifecycle

```
build_runner(path)
│
├─ PipelineConfig.from_file(path)          ← CONFIG parses JSON
│
├─ DAG(pipeline_cfg)                       ← GRAPH validates deps, detects cycles,
│                                            computes topological order
│
└─ WorkflowRunner(dag, runner_cfg, ...)
   │
   runner.run(run_id)
   │
   ├─ build_context(...)                   ← CONTEXT creates RunContext
   │    ArtifactStore injected into context
   │
   ├─ RunState(run_id, pipeline_name)      ← STATE initialised (or restored from
   │    [or restore_from_records()]          metastore on resume=True)
   │    context.restore_outputs(...)       ← outputs restored from metastore records
   │                                         directly into RunContext
   │
   ├─ build_executor(runner_cfg.executor)  ← EXECUTION picks Sequential or Threaded
   │
   ├─ StepRunner(pipeline_cfg, state,      ← EXECUTION creates callable
   │             run_context, ...)
   │
   └─ executor.run(dag, state, step_runner, cancel_event)
      │
      │  [for each step in topological order]
      │
      └─ step_runner(step_name)
         │
         ├─ STATE.is_step_complete?        resume skip → done
         │
         ├─ build StepContext(run_context) ← read-only view built per dispatch
         │
         ├─ STATE.step_status(deps)?       dependency skip → STATE.mark_skipped
         │                                                   Metastore.record_skipped
         │
         ├─ condition_evaluator(step_context, condition)?
         │    reads step_context.get_output(upstream_step)
         │    condition skip → STATE.mark_skipped
         │
         ├─ REGISTRY.get(step_name)        → BaseStep instance
         │
         ├─ [retry loop]
         │    STATE.mark_step_running()
         │    Metastore.record_step_running()
         │    │
         │    step.execute(StepContext) → output dict
         │    │
         │    ├─ success:
         │    │    Metastore.record_step_success(output)  ← output persisted to DB
         │    │    RunContext._register_output(step_name, output)  ← in-memory
         │    │    STATE.mark_step_success()              ← status only
         │    │
         │    └─ failure (retries exhausted):
         │         STATE.mark_step_failed(error)
         │         Metastore.record_step_failed()
         │         raise → executor cancels remaining steps
         │
         └─ step.teardown(StepContext, success)
   │
   ├─ [all steps done]
   │    STATE.mark_run_success()
   │    Metastore.record_run_success(context.list_outputs())
   │
   └─ return RunResult(...)               ← built from STATE + RunContext
```

---

## Ownership Summary

| Component | What it owns | Consumed by |
|---|---|---|
| **config** | Validated, typed config objects (`ExecutorConfig` lives here) | graph, execution, registry, state |
| **graph** | DAG topology, topological order, in-degree map | execution/executor |
| **registry** | Step name → BaseStep resolution | execution/step_runner |
| **state** | In-memory step/run status map | execution/step_runner, execution/executor |
| **context** | Step output registry and per-run data (`RunContext` held by runner; `StepContext` view given to steps) | execution/step_runner (writes via RunContext), steps (reads via StepContext) |
| **execution** | Run lifecycle, scheduling, retry, step dispatch, metastore writes | orchestrates all of the above |

---

## Key Boundaries

**Config is read-only after parse.** `PipelineConfig`, `StepConfig`, `RunnerConfig`, `ExecutorConfig` are frozen dataclasses. No component mutates them after construction.

**STATE vs Metastore.** `RunState` drives in-flight scheduling (fast, in-memory, status only). `RunMetastore` drives resume and observability (durable, survives restart, stores outputs). They are parallel writes — neither reads from the other during execution. On resume, outputs are restored from metastore records directly into `RunContext`; statuses are restored into `RunState`.

**Context split.** `RunContext` is held by the runner and never passed to steps. Steps receive a `StepContext` built from `RunContext` immediately before each dispatch. `StepContext` exposes only read methods (`get_output`, `has_output`, `list_outputs`, `artifact_store`, `metadata`, `llm`, `is_cancelled`) — no write methods exist on it. Output registration (`_register_output`) is called by `StepRunner` after `execute()` returns, not by the step itself.

**Single output source of truth.** Step outputs are owned by `RunContext`. `RunState` tracks statuses only. The DB (`record_step_success`) is the durable record; `RunContext` is the in-memory mirror for downstream step access.

**Registry is stateless.** Each `get(name)` call returns a fresh step instance. This ensures retries start clean with no leftover instance state.

**Executor knows nothing about steps.** It only calls `execute_fn(step_name)` and reads in-degree from the DAG. All step logic — skip, retry, output, metastore — lives in `StepRunner`.
