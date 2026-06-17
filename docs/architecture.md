# Architecture

## Execution Paths

There are two ways to define a pipeline, both of which converge on the same execution engine:

- **Decorator DSL**: A pipeline is defined in Python by decorating functions with a step decorator. The decorator registers each function as a step with its dependency declarations, producing a registry of pre-built step instances.
- **JSON config**: A pipeline is defined in a JSON file. Step classes are loaded dynamically by module path at runtime, producing a registry of on-demand step instances.

Both paths produce a step registry and a pipeline config, which are the only inputs the runner requires. The runner is unaware of which path produced them.

## Component Boundaries

```
CLI / Python API
      │
      ▼
    Runner
      │
      ├──► DAG               (dependency resolution, topological ordering, cycle detection)
      ├──► Step Registry     (step instantiation — DSL or config-driven)
      ├──► Executor          (step scheduling — SequentialExecutor or ThreadedExecutor, selected via ExecutorConfig in runner config)
      ├──► RunState          (in-memory mutable execution snapshot)
      ├──► Artifact Store    (large data handoff between steps — filesystem or S3)
      └──► Run Metastore     (durable lifecycle recording — SQLite, PostgreSQL, CockroachDB, or no-op)
```

`ArtifactStore` and `RunMetastore` are injected into the runner; neither is coupled to the other. Either can be replaced independently.

The executor is selected from `RunnerConfig.executor` (an `ExecutorConfig` with a `type` field). The default is `SequentialExecutor`, which runs steps one at a time in the caller's thread. `ThreadedExecutor` dispatches steps to a bounded thread pool and allows parallel execution of independent steps.

## Dual Persistence Model

Two separate persistence layers serve distinct purposes:

| Layer | Lifetime | Purpose |
|---|---|---|
| `RunState` | In-process, for the duration of a run | Tracks step statuses in memory; drives scheduling decisions |
| `RunMetastore` | Durable, survives process restart | Records run and step lifecycle for observability, resume, and audit |

`RunState` is the authoritative source for in-flight scheduling. `RunMetastore` is the authoritative source for resume: when a run is resumed, `RunState` is reconstructed from metastore records before execution begins.

## Context Split

The runner holds a `RunContext` — a write-capable context that owns the step output registry, artifact stores, metadata, and the cancellation event. Steps receive a `StepContext` — a read-only view built from `RunContext` immediately before each step is dispatched. `StepContext` exposes only read operations (`get_output`, `has_output`, `artifact_store`, `metadata`, `llm`, `is_cancelled`) and has no write methods. This prevents a step from writing to another step's output slot or advancing the run's state directly — only the runner may do so.

## Pluggable Registry Pattern

Both `ArtifactStore` and `RunMetastore` use a named registry. Implementations register themselves under a string key. The runner resolves the correct implementation at startup from the pipeline config. Custom implementations can be registered before the runner is built.

## Optional Dependency Loading

Optional integrations (S3, PostgreSQL, CockroachDB, LLM) are not imported at package load time. They are loaded on first access via the public package API. This ensures that a user who does not install optional extras does not encounter import errors.

## Frontend

The web dashboard is a separate React application that builds independently. Its build output is embedded into the Python package as static files, served by the optional FastAPI server. There is no separate deployment; the dashboard is a self-contained part of the `runlet` package when the `ui` extra is installed.
