# Domain Model

## Pipeline

A named, versioned definition of a workflow: a set of steps with declared dependency relationships. A pipeline definition is static — it does not change between runs. The same pipeline definition can produce many runs.

## Run

A single execution of a pipeline. A run is identified by a unique `run_id` (generated or provided by the caller). A run has a lifecycle: it starts, each of its steps executes in dependency order, and it ends in success, failure, or cancellation. The outcome and intermediate step outputs of a run are the persistent record of what happened.

## Step

A unit of computation within a pipeline. A step declares which upstream steps it depends on. Its inputs are the output dicts of those upstream steps, accessed via a read-only context at execution time. Its output is a JSON-serializable dict. Steps are stateless: no shared mutable state between steps is permitted.

## Artifact

Data too large to hold in a step's output dict is written to an artifact store and referenced by URI in the output dict. An artifact is the content at that URI. Artifacts are the mechanism for passing large datasets (files, JSONL streams, binary blobs) between steps without serializing them into the metadata layer.

## RunState

The in-memory, mutable snapshot of a run's current execution state. It tracks the status of each step (pending, running, succeeded, failed, skipped) and the output dict of each completed step. `RunState` is ephemeral — it exists only for the lifetime of the process executing the run. If the process exits, `RunState` is lost; the durable record is in the Metastore.

## Metastore

The durable record of run and step lifecycle. The metastore records when a run started, when each step ran and what its outcome was, and when the run completed. It survives process restart. On resume, `RunState` is reconstructed from the metastore before execution begins. The metastore is optional: if not configured, lifecycle events are discarded (no resume is possible).

## RetryPolicy

A per-step configuration that governs how many times a failed step is retried before it is marked permanently failed. Each attempt is a separate event in the metastore. Retries use exponential backoff with jitter. A step's retry history is preserved across resume.

## Condition

A rule attached to a step that is evaluated against the output of an upstream step before the step executes. If the condition is not satisfied, the step is skipped. Skipping cascades: all steps that depend on a skipped step are also skipped, unless they have other non-skipped dependencies that satisfy their dependency requirements.

## Terminology Notes

- **"Output"** always refers to the JSON-serializable dict a step returns — not any side effects.
- **"Artifact"** refers specifically to data stored externally and referenced by URI in an output dict — not the output dict itself.
- **"Metastore"** and **"artifact store"** are distinct: the metastore records lifecycle metadata; the artifact store holds data payloads.
- **"Resume"** means continuing an existing run (same `run_id`) from where it left off — not re-running from scratch.
