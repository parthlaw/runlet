# AGENTS.md

## Scope

`runlet` is a DAG-based pipeline orchestration engine for executing data-processing workflows within a single process. It owns the execution lifecycle of a pipeline run: dependency resolution, step scheduling, retry, conditional skipping, artifact handoff, and durable lifecycle recording. It does not own scheduling or triggering of pipeline runs (cron, events, or multi-pipeline orchestration), and it does not coordinate execution across machines or processes.

## Documentation

| Document | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Component boundaries, execution paths, persistence model, and pluggable extension points |
| [docs/domain-model.md](docs/domain-model.md) | Definitions of Pipeline, Run, Step, Artifact, RunState, Metastore, and their relationships |
| [docs/schema.md](docs/schema.md) | Metastore table constraints, resume semantics, and artifact store blob immutability model |
| [docs/conventions.md](docs/conventions.md) | How to extend runlet: adding steps, artifact stores, and metastores |

## Agent Guidance

Before making changes:

1. Determine which subsystem owns the change.
2. Read the documentation referenced for that subsystem.
3. Do not assume undocumented business rules.
4. If required information is missing from the referenced documents, ask the user.

## Documentation Ownership

AGENTS.md provides navigation only.

Knowledge belongs in the referenced documents.

Do not duplicate information from referenced documents here.
