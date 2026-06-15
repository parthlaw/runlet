# Schema

## Metastore

The metastore owns two tables.

### Run table

One row per run. Records the overall lifecycle of a pipeline execution: when it started, its current or final status, any error, and a snapshot of the outputs of all completed steps at run completion.

Key constraints:
- `run_id` is the primary key and is immutable once created.
- Status transitions are one-directional: a run moves from running → success/failed/cancelled and never backwards.

### Step table

One row per step attempt. If a step is retried, each attempt produces a separate row. The combination of `run_id`, `step_name`, and `attempt` is unique.

Key constraints:
- Attempt numbers are monotonically increasing per `(run_id, step_name)`.
- A step's final outcome is determined by the row with the highest attempt number.
- Skipped steps are recorded as a single row with status `SKIPPED` (no retry).

### Resume semantics

When a run is resumed:
- Steps whose final attempt has status `SUCCESS` or `SKIPPED` are not re-executed.
- Steps whose final attempt has status `FAILED` or `RUNNING` (indicating an in-progress or crashed state) are re-executed from attempt 1, preserving prior attempt history.
- The `run_id` is unchanged across a resume; the run record is updated in place.

## Artifact Store

The artifact store holds data payloads referenced by URI from step output dicts. It is not a relational store — there are no tables.

### Blob storage

Blobs are content-addressed and immutable. A blob's identity is its content hash. Once written, a blob is never modified. The same content written twice produces the same blob.

Blob layout within the store's prefix: `{prefix}blobs/{hash[:2]}/{hash[2:4]}/{hash}`

This two-level directory sharding is an implementation detail of the storage layout, not a contract — do not construct blob paths manually.

### Pointers

A pointer is a mutable reference to a blob, stored at a stable key derived from `(run_id, step_name, filename)`. Pointers allow a step to update what a given key refers to (e.g. on retry) without changing the URI held in the output dict.

### URI ownership

URIs stored in step output dicts are owned by the step that produced them. The runner does not interpret or modify URIs — it passes them through to downstream steps via the read-only context.
