# Deep Technical Review — `pipeline-runner`

This is a candid, no-shallow-praise review of `pipeline-runner` as it stands today (roughly ~50 KB of Python across orchestrator, artifact store, artifacts, and steps subpackages, zero tests). The scoring and recommendations assume the stated ambition (multi-tenant, distributed, Kubernetes-native, mission-critical) — not the current scope.

---

## 0. TL;DR

`pipeline-runner` is a **single-process, sequential, in-memory DAG executor** with a small JSONL artifact layer and a typed-record decorator. The factoring of `dag.py` / `state.py` / `artifact_store` is reasonable for an MVP; the rest of the system has correctness, durability, and abstraction problems that would prevent it from being trusted with production workloads even at small scale, let alone evolving into a Dagster/Temporal/Argo competitor.

The most damaging issues are:

1. **`RunState._flush` rewrites the entire state file on every transition** — a quadratic-cost, racy "append" that is fundamentally incompatible with S3, multiple writers, or runs of any length.
2. **The orchestrator is leaking domain logic** (PDF prefetch hardcoded into `SequentialRunner.run`, `/tmp` paths, `source_key`/`bucket` semantics baked into `_build_runtime_stores`) — this is not a general-purpose orchestration core, it is a single-tenant PDF pipeline runner pretending to be one.
3. **No worker abstraction, no queue, no scheduler, no lease, no cancellation, no timeouts, no retries.** Everything in the "Execution Semantics" portion of the prompt is unimplemented — README/`__init__` claim "parallel execution / retries / async / distributed workers" but none of those exist in code.
4. **The `@artifact` decorator silently rebuilds the user's class via `make_dataclass`, dropping methods, properties, and `__post_init__`.** This is a footgun that will burn the first serious user.
5. **Step outputs are written under a key derived only from `(run_id, step_name, "output")` — no content addressing, no input hash, no immutability.** Re-running a step overwrites; resume after partial success is unsafe for non-deterministic steps.
6. **Zero tests, no CI, no type-checker config, no linter config.** For a system designed to "evolve over years," this is the single biggest sustainability risk.

Overall architectural score (against the stated production ambition): **3.5 / 10**. Against "small internal batch-processing tool": **6 / 10** — the JSONL artifact layout, schema header, and DAG/state separation are reasonable foundations to keep.

---

## 1. Execution Semantics

### 1.1 What actually exists

- Topological execution via Kahn's algorithm in `pipeline_runner/orchestrator/dag.py` with deterministic tie-breaking by `min(queue)`.
- A `SequentialRunner.run()` loop in `pipeline_runner/orchestrator/runner.py` that iterates steps one at a time and calls `step_instance.execute(context)`.
- Skip propagation (`_has_skipped_dependency`) and a tiny condition mini-DSL (`==`/`!=`/`>`/`<`/`>=`/`<=` against the first record of an upstream step).
- Resume semantics: on `resume=True`, `RunState.load_existing` replays the state JSONL and skips any step currently in `SUCCESS` or `SKIPPED`.

### 1.2 What is missing or broken

| Capability | Status | Severity |
|---|---|---|
| Parallel step execution | **Not implemented** — `SequentialRunner` runs one step at a time despite the README/`__all__` advertising parallelism | Critical (false advertising) |
| Retries | **Not implemented** — a single exception fails the step and the whole run | Critical |
| Timeouts / deadlines | **Not implemented** — a step can hang the runner forever | Critical |
| Cancellation propagation | **Not implemented** — no signal handling, no cooperative cancellation, no `asyncio` integration | Critical |
| Backpressure | **Not implemented** — `_write_step_artifacts` drains the entire generator into a local file synchronously | Important |
| Fan-out / fan-in | **Structurally supported** in the DAG, **not executed in parallel** | Important |
| Concurrency limits per step / per run | **Not implemented** | Important |
| Exactly-once / at-least-once choice | **Implicitly "best effort once"** — overwrites under same key on retry; no idempotency token | Critical |
| Distributed workers | **Not implemented** despite README claim | Critical |
| Heartbeats / leases | **Not implemented** — two runners on the same `run_id` will trample state silently | Critical |

### 1.3 Concrete correctness problems

**A. The orchestrator can lose data on crash without anyone noticing.**

`SequentialRunner.run` performs roughly:

1. `_write_step_artifacts` → drains generator to a local temp file
2. `context.upload_from_file` → uploads to artifact store
3. `state.mark_step_success(...)` → durably records success

If the process dies between (2) and (3), the artifact exists in the store but `RunState` shows `RUNNING`. On `resume=True`:

```python
for step_name in self._dag.topological_order:
    if state.is_step_complete(step_name):
        logger.info("[%s] Already complete — skipping.", step_name)
        steps_skipped.append(step_name)
        continue
```

`is_step_complete` returns false for `RUNNING`, so the step is re-executed and silently overwrites the previous output under the same key. For non-deterministic steps (any step touching network, time, random, mutable upstream) this means **silent divergence between the on-disk artifact and the previously-observed-by-downstream artifact** if the prior run had already streamed the artifact to a downstream step. Classic write-after-read consistency hole.

Fix direction: write a *commit* record AFTER successful upload but BEFORE `mark_step_success`. Or write artifacts to a content-addressed location and let `mark_step_success` flip a pointer. Or two-phase commit: upload to a `…/_tmp/` key, write `SUCCESS` with the pointer, atomically rename.

**B. There is no atomicity boundary around the state file.**

```python
def _flush(self, records: list[dict[str, Any]]) -> None:
    existing: list[dict[str, Any]] = []
    if self.store.exists(self.store_uri):
        existing = self.store.download_jsonl(uri=self.store_uri)

    merged = existing + records
    self.store.upload_jsonl(records=merged, key=self.store_key)
```

This is a **read-modify-write under no lock against an object store**. The failure modes:

- **Quadratic IO.** A run with `N` total state transitions does `O(N²)` JSON parsing and full-object uploads. By transition 50 the state file is downloaded and re-uploaded 50 times. On S3 each round-trip is 30–150 ms; 50 transitions ≈ ~2 s wasted in state IO alone, more for large pipelines.
- **Lost updates.** Two writers (e.g. an accidental double-`run` or a retry after assumed crash) will each read the same prefix and write conflicting suffixes; the later write wins entirely, erasing the other's history. There is no precondition/etag/version check.
- **Torn writes.** A reader can observe a partially-uploaded state file under some store implementations (S3 itself is atomic per PUT, but `FilesystemStore.upload_jsonl` writes via `open(path, "wb")` directly, which is NOT atomic — see §10.B).

This is the **single biggest design flaw**. The JSONL-on-blob-store paradigm only works if writes are genuinely append-only (which neither S3 nor an unsynchronized local write actually are). Either:

- Move state to a transactional store (SQLite local; Postgres for distributed; DynamoDB conditional writes for S3-compatible).
- Or use S3 object versioning + ETags + `If-Match` conditional PUT.
- Or write each transition as its own `…/_state/{seq}.json` object and reconstruct on read.

The third option is the cheapest delta from current code and is the natural shape for event sourcing.

**C. Condition evaluation downloads the upstream artifact for every conditional step, every run.**

`read_first_record` downloads the *entire* upstream JSONL file just to read one record. If you have a 5 GB upstream artifact and three conditional downstream steps, you pay 15 GB of egress to evaluate three booleans. There is no caching, no range request, no header-only fetch. For artifact stores that support range GET (S3 does), reading the header + one line is trivially achievable.

**D. The "first record" condition contract is dangerously implicit.**

It uses *the first record* of an upstream JSONL — meaning step authors are silently obligated to put the right scalar there. There is no schema enforcement, no name guarantee, no contract surface, and the docstring doesn't make clear that the rest of the file is ignored. This will cause subtle bugs ("why is my condition seeing stale data?") that are hard to debug. Compare to Dagster's `DynamicOutput` or Temporal's `ContinueAsNew` — both surface this kind of branch as a first-class object.

**E. Hidden cross-cutting domain leak.**

`SequentialRunner.run` contains hardcoded PDF prefetch logic:

- Hardcoded `/tmp/` (security and correctness — read-only root containers, tmpfs limits, predictable path collisions, world-readable in many environments).
- Predictable path with no PID or random suffix — `tempfile.NamedTemporaryFile` exists for a reason. With two concurrent runs sharing a run_id (resume case), one wipes the other's PDF mid-stream.
- Domain coupling: the orchestrator core knows what a PDF is, what `source_key`/`bucket`/`pages`/`max_pages` mean, and assumes S3 URIs (`f"s3://{bucket}/{source_key}"`). This is irreconcilable with the stated philosophy of "minimal vendor lock-in" and "composable infrastructure."
- Bypasses the artifact-store abstraction — calls `context.upload_store.download_file` with a raw `s3://` URI rather than going through `build_key`/`uri_to_key`.
- Mutates `context.metadata` mid-run. The metadata dict is supposed to be lightweight, but the runner uses it as an implicit message bus between the bootstrap and steps. Hidden coupling.

Fix direction: this entire block must be a step (or, more honestly, a "prelude" abstraction explicitly modeled in the DAG). Nothing about PDFs, buckets, or `source_key` should be visible to `SequentialRunner.run`.

**F. `logging.basicConfig` in `__init__`.**

A library that calls `basicConfig` from a constructor will:

- Reconfigure handlers in user processes that already set up logging.
- No-op silently if `basicConfig` has been called already (so the constructor option is also a lie in production processes).
- Make multi-tenant embedding awkward (two pipelines with different `log_level` fight each other).

Library convention: never touch the root logger. Provide a `setup_logging()` helper for CLIs.

**G. `logging.basicConfig` is called every time a runner is constructed.**

Same issue, compounded — N runners ⇒ N reconfigure attempts. The Python stdlib silently drops all but the first; the `log_level` config field is effectively a lie after the first instantiation.

**H. `RunResult.metadata` is `context.metadata.copy()` — a shallow copy.**

Anything mutable inside (lists, dicts) is shared with the live context. If a caller mutates the returned result, they mutate live state. Minor but a maintainability landmine.

### 1.4 Idempotency / replayability

The system has **no real idempotency story**:

- Step keys: `{prefix}{run_id}/{step_name}/output.jsonl` — driven entirely by names, no input fingerprint, no content hash.
- Resume + re-run silently overwrites prior step output at the same key.
- No record of "what inputs produced this artifact" beyond the schema header (which captures `run_id`, `step`, `output_name`, `written_at`, `record_count`, but no input artifact URIs or hashes).
- No "this run is logically identical to that previous run" detection.

For any serious orchestration platform, the artifact key needs to be a content-addressed function of `(pipeline_version_hash, step_logic_hash, upstream_artifact_hashes, step_config_hash)`. Then `resume`, `retry`, and `replay` all become trivial: the same inputs hit the same key and skip; different inputs produce a new artifact and downstream steps cascade.

This is the **biggest single architectural change** that will determine whether this evolves into a Dagster-class system or stays a toy DAG runner.

---

## 2. Artifact System Design

### 2.1 The JSONL-with-header format

Each artifact is a single `.jsonl` (optionally gzipped) file with one header line followed by records, written by `_write_step_artifacts`.

**Strengths:**

- Self-describing — header carries schema name + version. Good.
- Append-shaped on disk (one record per line). Good for streaming reads.
- Compatible with `gzip`, `bzcat`, `jq`, `wc -l` — operational friendliness is real. Good.

**Weaknesses, in order of severity:**

**A. The header-prepend pass is a 2x write amplification.** The current implementation writes the data twice — once to `tmp_data_path`, once to `tmp_final_path` (with header). For multi-gigabyte artifacts this doubles local IO. Fix: open `tmp_final_path` first, write a *placeholder header* (fixed-width, padded), stream records into the same file, then seek(0) and overwrite the header. Or, drop the per-file `record_count` from the header (it's denormalized state anyway — you can recompute it).

**B. `record_count` in the header is denormalized state.** It can disagree with the actual line count if the file is truncated, manually edited, or partially uploaded. Truth source ambiguity.

**C. JSONL is not the right serialization for typed data at scale.**

- Per-record JSON encoding/decoding is CPU-bound and ~5-20x slower than msgpack and ~50-200x slower than columnar formats.
- No schema enforcement at the record level — the header says "schema=ExtractRecord, v=1" but a corrupted line will silently produce a wrong-shaped dict that `cls(**raw)` may or may not reject (it depends on whether extra/missing fields are present; `dataclass.__init__` is unforgiving on missing required fields and unforgiving on extras).
- No columnar projection for selective reads (no "give me just the `page` column").
- No compression-aware random access (gzip is not seekable).

For data-engineering workloads, Parquet (per-step output) + JSONL (for state and small artifacts) is the canonical pairing — and Parquet keeps your schema enforcement honest. For event-sourcing / actor-like workloads, Avro/Protobuf with a schema registry is the right tool. JSONL is fine for "small structured logs" and bad for "10M records per step."

Recommendation: keep JSONL as the default, but make `ArtifactStore.upload_records` polymorphic — let the artifact class declare its preferred encoding (`SCHEMA_ENCODING = "parquet"` or `"jsonl"` or `"msgpack"`). The header line still lives, just as the first row of metadata in whatever format you choose.

**D. The `@artifact` decorator is a destructive rewrite.**

The decorator silently discards everything on the user's class except dataclass fields — instance methods, properties, `__post_init__`, custom `__repr__`/`__eq__`, classvars, type hooks, validators. A user who writes:

```python
@artifact(version=1)
@dataclass
class ExtractRecord:
    page: int
    text: str

    def word_count(self) -> int:
        return len(self.text.split())
```

… gets back a class where `record.word_count()` raises `AttributeError`. This will silently violate the principle of least astonishment. Fix: don't rebuild the class; just bolt the classvars + base via dynamic class creation that *extends* the original (`type(cls.__name__, (cls, BaseArtifact), {...})`) or attach the metadata directly to the original class and skip subclassing entirely.

**E. Schema version registry has no collision check.**

Two artifacts with the same `SCHEMA_NAME` + `SCHEMA_VERSION` silently overwrite. Fix: raise. Multi-tenant systems will absolutely have name collisions across packages — a system that doesn't fail loudly here will produce data corruption in production.

**F. The upgrade chain is single-hop and forward-only.**

This is a sensible model (chain N→N+1 upgraders), but:

- No support for major-version compatibility breaks (no way to declare "v2 is incompatible with v1; refuse to upgrade").
- No support for downgrade (necessary when an older downstream reader catches up to a newer producer — common in long-running deploys).
- No support for "this field is optional / can be defaulted" without writing an explicit upgrader. Compare to Avro/Protobuf schema evolution which handles add/remove/default for free.
- No structural validation of the upgrader output (it might still be missing required fields).

**G. The dead code in `load_record` is a smell.**

`if raw.get("schema") and raw["schema"] != cls.SCHEMA_NAME: pass` is a leftover; remove it. If you want defense-in-depth schema name checking, do it once outside the loop in `context.iter_artifacts`, not per-record.

**H. The artifact store is keyed by step output name, not artifact identity.**

`build_key(run_id, step_name, "output") = {prefix}{run_id}/{step_name}/output.jsonl`. Re-running a step rewrites this key. There is no way to:

- Compare two runs' versions of the same step's output.
- Roll back a run.
- Pin a downstream step to a specific upstream artifact version.

Content addressing (`{prefix}artifacts/sha256/{ab}/{cd}/{...}.jsonl` + a step→artifact pointer table) solves all three at the cost of one indirection. Strongly recommended before this system goes multi-tenant.

**I. There's no large-artifact handling story.**

- `S3ArtifactStore.upload_jsonl` uses `put_object` with the entire body in memory. Hard limit: 5 GB single PUT, practical limit: whatever your container memory is. Use `upload_fileobj`/`upload_file` with multipart enabled for `_state/run_state.jsonl` ≥ 100 MB.
- `download_jsonl` reads the whole body into a Python string. Memory-heavy.
- `_decode_jsonl` calls `raw.splitlines()` — materializes another full copy.

For artifacts of "real" size (≥ 100 MB), the streaming `upload_file`/`download_file` path is fine, but **the JSONL state file uses `upload_jsonl`/`download_jsonl`** specifically (see `RunState._flush`), which means state IO grows linearly in memory with run length.

---

## 3. State Management

| Concern | Status |
|---|---|
| State is durable | Yes (writes to artifact store) |
| State is atomically updated | **No** (read-merge-write, no precondition) |
| State supports multiple writers | **No** (last writer wins, silently) |
| State recovers from torn writes | **No** (full-file rewrite assumed) |
| State is event-sourced | Partially (JSONL records are event-shaped, but the file is mutated, not appended) |
| State writes scale linearly with run length | **No** — quadratic |
| State is checkpointable mid-step | **No** — a step is either fully done or re-run from scratch |
| State has schema versioning of its own | **No** — replay assumes one shape forever |
| State separates run metadata from step metadata cleanly | Partial (`"type": "run"` vs `"type": "step"` discriminator works, but no schema) |

**Concrete recommendations, ranked:**

1. **Critical**: Replace `RunState._flush` with append-only writes. Either per-transition objects (`{prefix}{run_id}/_state/{seq:010d}.json`) or a single appendable log via a lock-protected local SQLite mirror that periodically uploads.
2. **Critical**: Add a lease/heartbeat to prevent two runners from racing on the same run_id. Even just `{prefix}{run_id}/_state/lease.json` with `{owner, expires_at}` and a CAS check on lease takeover.
3. **Important**: Define the state-record schema as its own typed artifact (eat your own dogfood) and version it. `RunState` v1 → v2 is going to happen.
4. **Important**: Add intra-step checkpointing — for long steps (e.g. one that iterates 1M records), emit progress sub-records to state so resume can pick up at record N rather than restart from 0.
5. **Future**: For real distributed execution, move state to a transactional store (Postgres for general use; DynamoDB if you stay all-S3). Keep the JSONL artifact store for *step output*, but not for the orchestrator's mutable state.

---

## 4. Architecture Review

### 4.1 Module boundaries

Reasonable separations exist:

- `dag.py` — pure config parsing + topology. Clean, testable in isolation.
- `state.py` — run-level state. Reasonably narrow.
- `context.py` — runtime registry of step outputs.
- `artifact_store/` — pluggable persistence.
- `artifacts/` — typed records and serialization.
- `steps/base_step.py` — step contract.

This is the *one part of the codebase that is genuinely well-shaped*. Keep it.

### 4.2 Tight couplings and leaky abstractions

- **`SequentialRunner.run` knows about PDFs, S3 URIs, and `source_key` metadata.** Critical.
- **`_build_runtime_stores` builds TWO `S3ArtifactStore`s with different prefixes, returns both, and embeds the convention that the second one is a "user-facing" store.** This is a domain leak. There should be exactly one `ArtifactStore` abstraction per logical store, and the "upload PDF to a known location" should be its own step. The dual-store design also defeats the artifact store abstraction — `upload_store` is used to bypass `build_key` and write to raw S3 keys.
- **`PipelineContext` knows about gzip, JSONL parsing, header semantics, and registry-based upgrades.** Three concerns. The context should be a thin URI registry; deserialization should be a separate `ArtifactReader` class.
- **`build_runner` reads from `raw.get("runner", {})`** but the documented config schema doesn't mention a `runner` block. Drift between code and docs.
- **`run_id` doubles as both a logical run identifier AND a path component AND a temp-file disambiguator.** This is fine until someone uses a `run_id` with a slash, dot, or `..` in it.

### 4.3 Missing abstractions

To evolve into a real platform, you need at minimum:

- `Worker` — the entity that executes a step (in-process, subprocess, container, K8s pod). Today, "the runner" *is* the worker.
- `Scheduler` — chooses what to execute next. Today, Kahn's order + sequential iteration is hardcoded.
- `Queue` — work to be done. Doesn't exist; trivially needed for any non-sequential execution.
- `Executor` — the binding between scheduler and worker. Doesn't exist.
- `ArtifactRef` — a typed, immutable handle that wraps `(uri, schema_name, schema_version, content_hash)`. Today URIs are bare strings.
- `RunHandle` — what the caller gets back from `runner.submit()` and can `.cancel()`, `.await_completion()`, `.stream_events()` against. Today `runner.run()` is blocking and there's no way to interact mid-flight.
- `Event` — what gets written to state. Today state events are dicts.

Even keeping the system single-process, introducing `Worker`/`Scheduler`/`Queue` as in-process primitives (with the trivial implementations being "the current thread") is the cheapest path to making the system *capable* of distribution without rewrites.

### 4.4 Hidden global state

- `pipeline_runner/artifacts/registry.py` ends with `registry = ArtifactRegistry()`. Module-level singleton.
- `@artifact` registers into that singleton at import time.

Consequences:

- Tests cannot isolate registries.
- Multi-tenant servers cannot have per-tenant artifact namespaces.
- Re-importing modules during hot reload either silently fails (duplicate registration is a no-op overwrite) or behaves oddly.
- A library consuming this can't have its own private artifact types coexisting with another library's.

Fix: make the registry an injectable parameter on `SequentialRunner` (default to the module-level one for convenience). Make `@artifact(..., registry=...)` accept an explicit registry. This is a one-day refactor that pays off forever.

### 4.5 Plugin / extensibility model

- **Steps**: discovered via `importlib.import_module(step_cfg.module)` and `getattr(module, step_cfg.class_name)`. Simple, but it means step instantiation depends on the runner's `sys.path` at runtime. No per-pipeline isolation.
- **Stores**: registered via `if store_type == "s3" / "filesystem"` hardcoded conditionals in `build_store` AND duplicated in `_build_runtime_stores`. Adding a third store (GCS, Azure Blob) requires touching both sites.
- **No plugin discovery mechanism** (no `entry_points`, no `pkg_resources` integration).

Recommendation: define `STORE_REGISTRY: dict[str, type[ArtifactStore]]` at module level; let users register stores; use `entry_points` (PEP 517) for discoverable third-party stores. Same pattern for step modules — a `step_factory` registry that supports lazy loading.

---

## 5. Scalability Review

### 5.1 Hard scaling ceilings as currently written

| Dimension | Current ceiling | Bottleneck |
|---|---|---|
| Steps per pipeline | ~1,000 before state-file IO dominates | `_flush` is O(N²) |
| Records per step | Bounded by local disk size of step machine | `_write_step_artifacts` writes everything to temp before upload |
| Concurrent runs (same pipeline, different run_id) | Effectively 1 per host | Single-process, blocking |
| Concurrent runs (same run_id) | **Unsafe at any number** | No lease |
| Pipeline DAG size | ~10K nodes (Kahn's `min(queue)` is O(N) per pop, so total O(N²)) | `_kahn` uses `min()`+`remove()` instead of a heap |
| State file size | ~100 MB usable | `_flush` round-trips on every transition |

### 5.2 What breaks first at 10× growth

- 10× larger pipelines (~300 steps): state file balloons to ~5–20 MB, every transition is a ~20 MB round-trip to S3. End-to-end execution time becomes state-IO-dominated.
- 10× larger artifacts (~10 GB per step): local disk fills up, no streaming-decoder path means consumer steps OOM on `iter_artifacts` (because `download_file` writes the whole thing to disk first, *that's fine*; but in-memory deserialization of large records is still the user's problem).

### 5.3 What breaks first at 100× growth

- Any attempt at multi-tenancy is impossible — global registry, shared `/tmp`, no quota model, no isolation, no scheduling fairness.
- S3 request rate: 5500 GET per prefix per second is the published soft limit. A pipeline using a single bucket with everything under `pipelines/` will hit this; the bucket needs per-tenant or per-run hashed prefixes (`{hash[:2]}/{run_id}/...`) for high-rate workloads. Today the prefix is whatever the user configures, with no awareness of partitioning.

---

## 6. Reliability + Fault Tolerance

| Capability | Status |
|---|---|
| Worker crash recovery | Resume-on-restart exists but doesn't clean up half-written outputs; non-deterministic steps risk drift |
| Orchestrator failover | Not implemented (single process) |
| Heartbeat design | Not implemented |
| Lease handling | Not implemented |
| Poison task handling | Not implemented (one failure = whole run fails) |
| Retry storms | N/A (no retries) |
| Cascading failures | Mitigated only because everything is sequential — no fan-out to fail in waves |
| Partial infrastructure outage (S3 down) | Single try/except per call, raises `ArtifactStoreUploadError` immediately; no backoff |
| Circuit breakers | Not implemented |
| Durable queues | Not implemented |
| Dedup | Not implemented |
| Recovery protocols | Best effort via `RunState.load_existing`; resume-skips-success only |

The minimal viable reliability layer that I would build first:

1. **Retry policy per step** — declarative in config or via a `RetryPolicy` dataclass on `BaseStep`. `(max_attempts, backoff, jitter, retry_on=[exception_classes])`. Persist attempt count in state.
2. **Lease on the state file** — before writing, take a lease (`{run_id}/_state/lease.json`, `{owner, expires}`), refresh every N seconds via a background thread, drop on graceful shutdown. Use this to detect zombie runs.
3. **Timeouts** — `step.timeout_seconds`. Implement via `signal.alarm` (single-process) or per-task subprocess (more portable).
4. **Bounded concurrency** — pipeline-level `max_parallel_steps`. Replace the sequential `for step_name in topo_order:` loop with a `ThreadPoolExecutor`/`asyncio` driver.
5. **Atomic step-success commit** — write the artifact to a content-addressed location, then write the success state record (containing the address). Crash between → next run re-uploads to the same content address (idempotent) and re-emits success.

Time estimate to "real" reliability: 4–8 weeks of focused work, not counting tests. Multiply by 3–5x if multi-process.

---

## 7. Developer Experience

### 7.1 What works

- `@artifact` decorator is *nice in principle* — typed records as the unit of step output is the right abstraction (similar to Dagster's `Output`/`Out`).
- `BaseStep.execute` returning a generator is clean and matches the JSONL streaming model.
- JSON config file is human-readable and grep-friendly.
- `RunResult` is an immutable summary — good shape.

### 7.2 What's painful or broken

- **No tests, no examples, no quickstart project.** Every user has to figure out the pipeline.json shape from `dag.py` source. The README has one fragment that imports `from pipeline_runner import build_runner, BaseStep, PipelineContext, artifact` — but doesn't show a pipeline.json, a step module, or a full end-to-end example.
- **The decorator destroys methods (§2.2.D).** Footgun.
- **No type stubs for the dynamically-generated step classes.** Tools like `mypy`/`pyright` can't infer that `record.page: int` after `iter_artifacts("extract", ExtractRecord)` because `iter_artifacts` returns `Iterator[T]` but `T` is the *rebuilt* class, which won't have stubbed methods.
- **`BaseStep.teardown` and `BaseStep.validate_config` are declared but never invoked by the runner.** Dead API — extremely confusing for users.
- **No CLI.** Users have to write `runner = build_runner(...); runner.run(...)` in Python. Compare to Prefect/Dagster CLIs.
- **No local-dev artifact viewer.** Listing `_state/run_state.jsonl` and grepping for failures is the only debugging tool.
- **Errors include full tracebacks in the state file (`_format_error`).** Good signal but also a privacy risk in multi-tenant settings — tracebacks routinely leak paths, env vars (in stack-frame locals depending on formatter), or secret-shaped data.
- **`PipelineContext` mixes "URI registry" with "I/O helpers"** — `iter_artifacts`, `read_first_record`, `upload_from_file` all live on the same object that steps pass around. Steps can call `upload_from_file` despite the docstring saying not to. Enforce this via separate `RuntimeContext` (passed to steps) and `WriterContext` (used by runner only).
- **`step_cfg.config` is `dict[str, Any]` — no schema, no validation.** Compare to Pydantic-based step config in Prefect.
- **`PipelineConfig.from_file` only supports JSON.** Most data engineers expect YAML. A 10-line PR.

### 7.3 Static analysis posture

- No `mypy.ini` / `pyrightconfig.json` / `tool.mypy` / `tool.pyright` block. The codebase uses `from __future__ import annotations` and reasonable type hints, but there's no enforcement.
- No `ruff` / `black` / `isort` config.
- No `pre-commit`.

For a system that wants to "evolve over years," this is **the single highest-leverage improvement available**: add `ruff` + `mypy --strict` + a basic CI, fix the resulting warnings, and you've bought yourself 3–5 years of maintainability essentially for free.

---

## 8. Observability

| Capability | Status |
|---|---|
| Structured logging | No (uses `logger.info("…")` with positional args) |
| Trace IDs / correlation | No |
| Metrics | No emission anywhere (no Prometheus, no OTel, no StatsD) |
| Tracing | No OTel/W3C trace context |
| Lineage tracking | Implicit only — `(run_id, step_name)` → URI. No upstream→downstream artifact lineage in state. |
| Audit log | Partial — state JSONL has timestamps and error tracebacks |
| Execution visualization | None — no DAG render, no Gantt, no UI |
| Replay / debug tooling | None |
| Per-step resource accounting | None (no CPU/mem timing beyond wall clock) |

What I would build first:

1. Emit OTel spans from `SequentialRunner.run` (run-level) and around each step's `execute` (step-level), with attributes for `pipeline.name`, `pipeline.run_id`, `step.name`, `step.attempt`, `step.duration_ms`, `step.record_count`, `step.bytes_written`. This gets you Jaeger/Honeycomb/Datadog for free.
2. Emit Prometheus metrics: `pipeline_runs_total{status}`, `pipeline_step_duration_seconds{pipeline,step,status}`, `pipeline_step_records_written_total{pipeline,step}`, `artifact_store_operations_total{op,result}`.
3. Structured logging via `structlog` or stdlib `logging.makeLogRecord` with `extra={}`. Logs that are not JSON are unparseable at scale.
4. Add `lineage_in: list[str]` (upstream artifact URIs) to each `_state/run_state.jsonl` step success record so lineage can be reconstructed from state alone.
5. Generate a static SVG of the DAG (Graphviz output from `DAG._adjacency`). 50 lines of code, huge UX win.

---

## 9. Code Review (specific issues by file)

In addition to issues already cited above, the following deserve explicit mention:

### `pipeline_runner/orchestrator/runner.py`

- L101: `_build_runtime_stores` returns three values; `store_prefix` is only used by `RunState`. Encapsulate this — `StoreBundle` dataclass instead of a tuple.
- L143–289: One enormous `try/except/finally` block ~150 lines deep. Extract `_execute_step(...)` so the outer loop is 20 lines.
- L150: `pipeline_cfg.get_step(step_name)` is O(N) per call (linear search through `self.steps`). Build a dict once.
- L161–188: Condition-evaluation error handling returns *inside* the loop, replicating the same `RunResult(...)` construction four times in this file. Extract a `_fail_run(state, run_id, …) -> RunResult` helper.
- L195: `bool(step_cfg.config.get("compress", False))` — should be schema-validated, not duck-typed. A user passing `"compress": "yes"` gets the truthy `bool("yes") == True` surprise.
- L196–205: Hard-coded `tempfile.gettempdir()` paths with predictable names. Two concurrent runs with the same `run_id` and the same `step_name` collide on `/tmp/{run_id}_{step}_output.jsonl`. Use `tempfile.mkdtemp(prefix=...)` per-step.
- L253–257: The `finally` ignores `OSError` from `os.remove` silently. Fine in this specific case but should at least debug-log so disk leaks are diagnosable.
- L283–288: Same swallowing of `os.remove` errors for the prefetched PDF. Plus `/tmp/{run_id}_source.pdf` already discussed.
- L342–376: `_load_step` catches `Exception` on instantiation and wraps in `StepImportError(ImportError)` — but the exception's stack trace is dropped (you only have the wrapping message + `from exc`, which only shows the original `__cause__` if the user inspects it). For runtime debugging this is fine; for tests it's annoying.
- L488: `_EmptyArtifact` is *not* registered with the registry. Empty outputs will fail to deserialize if any downstream step tries to read them with `iter_artifacts(step_name, _EmptyArtifact)`. Acceptable since there's nothing to deserialize, but the header still claims `schema=EmptyArtifact` v1 — and that schema is unknown to the registry.
- L530–558: The condition mini-DSL is OK but completely undocumented in the README. It exists only in `dag.py`'s docstring.
- L379–428: `_build_runtime_stores` duplicates the entire store-construction logic from `build_store` in `artifact_store/__init__.py`. DRY violation — both will drift.

### `pipeline_runner/orchestrator/dag.py`

- L189: `raw: dict[str, Any] = field(default_factory=dict, compare=False)` on a *frozen* dataclass — `raw` will be reused if multiple `PipelineConfig`s are constructed without explicit `raw` (`default_factory` is called per-instance, so OK actually; but the dict is mutable, defeating `frozen=True` in spirit).
- L142–143: `depends_on: tuple[str, ...] = field(default_factory=tuple)` — tuple is immutable, good.
- L143: `config: dict[str, Any] = field(default_factory=dict)` — dict is mutable on a frozen dataclass. Use `MappingProxyType` or freeze.
- L378–417: Kahn's uses `min(queue)` + `queue.remove(next_step)` which is O(N) per pop. For typical pipelines (< 100 steps) this is irrelevant; for 10k-node DAGs it's noticeable. Use `heapq` instead — same determinism, O(log N) per pop.
- L347: `step_names = set(self._config.step_names)` — `step_names` is a property that builds a list every call; cache once.
- L361–362: `_validate_step_condition(step)` is called during build. Good — fails fast.
- L411: `[n for n in in_degree if n not in order]` is O(N²) — for diagnostic on cycle detection, fine.

### `pipeline_runner/orchestrator/context.py`

- L97–148: `read_first_record` downloads the whole upstream artifact. As mentioned, use a range GET or store the first record as a separate header artifact.
- L154–209: `iter_artifacts` opens a generator that downloads the entire file before yielding. The `try/finally` for `os.remove` only runs when the generator is exhausted, closed, or garbage-collected. A caller doing `next(context.iter_artifacts(...))` and then dropping the iterator leaves the temp file on disk until GC. Convert to a context manager (`with context.read_artifacts("step", Cls) as it: ...`) to make cleanup explicit.
- L188–194: Schema-name mismatch only `logger.warning`s. This is a silent data-corruption risk if a user accidentally renames a step or reuses a class name. Make it raise unless the caller passes `strict=False`.
- L249–266: `restore_paths` mutates `self._paths` via `set_path`, which logs at debug level per entry. For a 1000-step resume, 1000 debug log lines.
- L240: `to_dict` returns `paths` directly but `metadata` by reference. Footgun.

### `pipeline_runner/artifacts/serializer.py`

- L46: `dump_record` calls `artifact.to_record()` then `json.dumps(...)`. No control over float precision, NaN handling (`json` raises ValueError on NaN by default — that's not what most data-science code expects).
- L52: `parse_header` calls `json.loads(line)` then `.get(HEADER_KEY)` — a record line that *happens* to include `_header: true` (because a step author exploring the namespace conflicted with the reserved key) is silently misidentified as a header. Use a sentinel format (e.g. first byte must be `#` or first key must be `_pr_header_v1`) and reject ambiguity.
- L66: Dead `if ...: pass` block.

### `pipeline_runner/artifacts/decorator.py`

- L34–60: Already covered (destructive rewrite).
- L41: `(f.name, f.type, f.default)` — `f.type` is a string when `from __future__ import annotations` is on. `make_dataclass` accepts strings, but downstream consumers (`typing.get_type_hints`, runtime validators) will get string annotations they need to `eval()` in the right module context. Subtle bug for anything that introspects.
- No support for `kw_only`, `slots`, `frozen`. The rebuilt class loses any options the user set on `@dataclass(...)`.

### `pipeline_runner/artifacts/registry.py`

- L53: Module-level `registry = ArtifactRegistry()`. As covered — global state, untestable, multi-tenant-hostile.
- L18–24: Silent overwrite on collision.
- No method to enumerate registered schemas (useful for diagnostics: "what schemas does this process know about?").

### `pipeline_runner/artifact_store/store.py`

The abstract interface is reasonable but missing:

- `list_keys(prefix) -> Iterator[str]` (needed for garbage collection, lineage, debugging).
- `head(uri) -> dict` (size, checksum, last-modified). `exists` is a degenerate `head`.
- `presigned_url(uri, expires_in)` (needed for external integrations).
- `iter_records(uri, decoder) -> Iterator[T]` (true streaming, no full download).
- `upload_records_streaming(iterator, key) -> str` (true streaming write).
- `copy(src_uri, dst_uri)` (intra-store copy, e.g. for content-addressed rewrites).
- Atomicity hint: `upload_jsonl(records, key, *, overwrite=...)`.

### `pipeline_runner/artifact_store/stores/s3.py`

- L55–57: `boto3.client("s3", **kwargs)` in `__init__`. No connection pooling configuration, no `Config` (no retry policy, no max_pool_connections override, no per-request timeouts). Production S3 clients should at minimum set `Config(retries={"max_attempts": 5, "mode": "adaptive"}, max_pool_connections=50, connect_timeout=5, read_timeout=60)`.
- L73–89: `upload_jsonl` uses `put_object` — see §2.2.I (5 GB hard limit).
- L91–103: `download_jsonl` reads entire body to memory.
- L105–115: `exists` checks `Error.Code in ("404", "NoSuchKey")` — actually fine, but `head_object` returns HTTP-style codes ("404") while `get_object` returns AWS error codes ("NoSuchKey"). The mixing is slightly misleading but functionally correct.
- No SSE/KMS, no `RequestPayer`, no `ChecksumAlgorithm`. For "user-owned infrastructure" goal, these are eventual must-haves.
- No `Config(signature_version="s3v4")` — older buckets / non-AWS S3-compatibles need this.

### `pipeline_runner/artifact_store/stores/filesystem.py`

- L68–82: `upload_jsonl` writes via `open(path, "wb")` and a single `fh.write(...)`. **Not atomic** — a reader can observe a partial file. Pattern: write to `path + ".tmp.{pid}"`, then `os.replace(tmp, path)` (POSIX atomic rename).
- L100–122: `upload_file` / `download_file` use `shutil.copy2`. Also not atomic — same fix.
- L124–135: `upload_file_raw` does `os.path.join(self._base_dir, key)`. **If `key` is absolute (`/etc/passwd`), `os.path.join` discards `base_dir`.** Path-traversal vulnerability for any caller that takes user-provided keys. Validate that the resolved path stays under `base_dir` (`os.path.realpath(dest).startswith(os.path.realpath(self._base_dir) + os.sep)`).
- L48: `os.makedirs(self._base_dir, exist_ok=True)` in `__init__`. Side effect at construction time. Fine for dev but surprising in tests that construct then never use the store.

### `pipeline_runner/orchestrator/state.py`

- Already covered the core defect.
- L292: `_replay` doesn't restore `_pending_records`. Looks fine since `_pending_records` is unused (declared but never written to).
- L131: `_pending_records` is unused dead code.
- L240–251: `_flush` does not handle the failure mode where `upload_jsonl` partially writes — there's no rollback, no retry, no idempotency token. A network blip during state flush mid-run causes the next state flush to be based on stale `existing`.

### `pipeline_runner/steps/base_step.py`

- L80–82: `teardown(context, success)` declared but **never called** by the runner. Either remove it or call it in the runner's `finally`.
- L76–78: `validate_config()` declared but **never called**. Same.
- L65: `self.log = logging.getLogger(f"step.{self.name}")` — if two steps in different pipelines share a name, they share a logger. Use the pipeline name as prefix: `logging.getLogger(f"pipeline.{pipeline_name}.step.{name}")`. Requires plumbing pipeline_name into step constructor.

---

## 10. Issue Catalog (classified)

### Critical (must fix before any production use)

1. **`RunState._flush` quadratic, racy state writes.** [§1.3.B, §3]
2. **Step success commit is non-atomic** — artifact upload then state write, no fence, no two-phase commit. [§1.3.A]
3. **Hardcoded PDF / S3 / `/tmp` domain leak in `SequentialRunner.run`** and `_build_runtime_stores`. [§1.3.E, §4.2]
4. **No retry, no timeout, no cancellation** anywhere. [§1.2]
5. **No concurrency control** — two runners on same `run_id` corrupt state silently. [§3]
6. **`@artifact` decorator silently strips user methods/properties.** [§2.2.D]
7. **`logging.basicConfig` in library constructor.** [§1.3.F]
8. **Zero tests, no CI.** [§7.3]

### Important (fix before scaling beyond a single team)

9. **`FilesystemStore` non-atomic writes** (use temp+rename). [§9 / filesystem.py]
10. **`FilesystemStore.upload_file_raw` path-traversal.** [§9 / filesystem.py]
11. **`PipelineContext.iter_artifacts` downloads the entire file** to local disk, no range-read for `read_first_record`. [§1.3.C, §9 / context.py]
12. **`@artifact` decorator silently overwrites on collision.** [§2.2.E]
13. **No content-addressed artifact identity** — re-runs silently overwrite. [§1.4, §2.2.H]
14. **Schema-name mismatch in `iter_artifacts` is only a warning.** [§9 / context.py]
15. **No structured logging / metrics / tracing.** [§8]
16. **Hardcoded store-type if/else in `build_store` and `_build_runtime_stores`** (drift risk). [§4.5]
17. **`step_cfg.config` is unvalidated dict.** [§7.2]
18. **No `mypy` / `ruff` enforcement.** [§7.3]
19. **`BaseStep.teardown` and `validate_config` are dead APIs.** [§9 / base_step.py]
20. **State and context expose mutable refs (shallow copies, `metadata` aliasing).** [§9 / context.py]

### Optional (cleanups that pay off)

21. Replace `_kahn`'s `min(queue)+remove` with `heapq`. [§9 / dag.py]
22. Cache `PipelineConfig.get_step` lookup. [§9 / runner.py]
23. Extract per-step execution into a helper to reduce 150-line `try/except`. [§9 / runner.py]
24. Remove dead code (`if ...: pass` in serializer, `_pending_records` in state). [§9]
25. Support YAML configs. [§7.2]
26. Add a CLI (`python -m pipeline_runner run config/pipeline.json --run-id ...`). [§7.2]
27. Add Graphviz DAG render. [§8]
28. Add `__repr__` to `RunResult` that hides full traceback.

### Future-scale (when distribution becomes real)

29. Pluggable `Scheduler` / `Worker` / `Queue` / `Executor`. [§4.3]
30. Transactional metadata store (Postgres / DynamoDB) replacing JSONL state for run management. [§3]
31. Content-addressed artifact storage with mutable pointer table. [§1.4, §2.2.H]
32. Per-pipeline isolation (artifact registry, store credentials, namespaces). [§4.4]
33. OTel + Prometheus integration with W3C trace context propagation. [§8]
34. K8s operator + CRDs (`Pipeline`, `Run`, `Step`) when distributed execution lands. [§4.3]
35. Lineage graph in state (upstream URIs/hashes per step record). [§8]
36. Per-tenant quotas, fairness, scheduling. [§5.3]

---

## 11. Comparisons (briefly)

| System | Where `pipeline-runner` is honest about being different | Where it should *learn* from them |
|---|---|---|
| **Dagster** | DAG-as-config vs Dagster's Python DAG construction is a fine philosophical choice | Dagster's `IOManager` + `Output(value, metadata=...)` + asset materialization patterns are the right model for typed artifacts; `@artifact` should look more like `@asset` |
| **Temporal** | Temporal is for *long-running* workflows with deterministic replay; this system is much simpler | Temporal's "history is the source of truth" event sourcing is exactly what `RunState` needs to become |
| **Airflow** | Airflow's mutable scheduler-DB tight coupling is what this system should *not* become | Airflow's poor DX is a cautionary tale: this system is currently in the same DX trough |
| **Prefect** | Prefect 2.x dynamic flows are a feature this system explicitly doesn't have | Prefect's task-level retry policies, timeouts, and result persistence config are the minimum viable API surface |
| **Celery** | Celery is task-queue only, not orchestration | Celery's ACK semantics + result backends are the right model for at-least-once execution |
| **Argo Workflows** | Argo is K8s-native — this system has no K8s integration | Argo's artifact lifecycle (`outputs.artifacts` declared per step, garbage-collected by lifecycle) is the model this system needs once content-addressed storage lands |
| **Ray** | Ray's `@remote` model is the *opposite* of this system's static-DAG model | Ray's object store and lineage tracking are good ideas to borrow |
| **Step Functions** | SF's declarative ASL state machine is a similar philosophy to pipeline.json | SF's explicit `Retry`/`Catch` clauses are the right declarative shape for retries; copy that into pipeline.json |

---

## 12. Roadmap toward a production-grade platform

I would sequence work as follows. Each phase should land with tests and CI.

### Phase 0 — Hygiene (1–2 weeks, do this *now*)

- Add `pytest` with at least: DAG parsing/validation tests, Kahn's tie-break determinism, RunState replay correctness, `@artifact` round-trip, FilesystemStore happy + path-traversal tests, S3 store with `moto`, end-to-end small pipeline.
- Add `ruff` + `mypy --strict` + `pre-commit` + GitHub Actions / equivalent CI.
- Remove dead code (`teardown`, `validate_config`, `_pending_records`, `if pass`).
- Remove `logging.basicConfig` from library code.
- Move PDF/S3-specific bootstrap out of `SequentialRunner.run` into a step.
- Fix `FilesystemStore` atomic writes and path-traversal.

### Phase 1 — Correctness foundation (2–3 weeks)

- Make state writes append-only: per-transition objects under `_state/{seq:010d}.json`, reconstruct on resume.
- Add lease/heartbeat to prevent run_id collisions.
- Add retry + timeout policy on `BaseStep` and wire them in.
- Add two-phase step commit (upload to temp key → state success record → optional finalize/rename).
- Fix `@artifact` to extend the user's class rather than rebuild it.

### Phase 2 — Real abstractions (3–6 weeks)

- Introduce `Scheduler` / `Worker` / `Executor` / `Queue` interfaces with in-process default implementations.
- Replace `SequentialRunner` with `Runner(Scheduler, Executor)`. Add a `ThreadedExecutor` with `max_concurrent_steps` config.
- Make `ArtifactStore` content-addressable: `put_blob(bytes_or_path) -> ContentHash`, separate `put_pointer(key, content_hash)`.
- Replace `(run_id, step, output) → uri` with `(run_id, step, output) → ContentHash` + lineage capture.
- Introduce injectable `ArtifactRegistry` (kill the global).

### Phase 3 — Observability + DX (2–4 weeks)

- OTel spans, Prometheus metrics, structured logging.
- CLI (`pipeline-runner run`, `pipeline-runner inspect`, `pipeline-runner replay`).
- DAG visualization (Graphviz/SVG).
- YAML config support.
- Pluggable store registration via entry points.

### Phase 4 — Distribution (multi-month)

- Replace state JSONL with Postgres (or DynamoDB) for the orchestrator's metadata DB. Keep JSONL for step artifacts.
- Split control plane (scheduler) from data plane (workers). Use a real queue (Redis Streams, SQS, NATS, or Kafka).
- Add gRPC/HTTP step worker protocol so workers can run in separate containers/pods.
- Implement Kubernetes operator with `Pipeline`/`Run`/`Step` CRDs and reconciliation loop.
- Multi-tenancy: per-tenant store credentials, per-tenant registries, per-tenant quotas.

---

## 13. Final assessment

### Biggest strengths (genuine, not flattering)

1. **`dag.py` is well-factored.** Pure config parsing, pure topology, no I/O. This is the part you should *keep* unchanged.
2. **JSONL with a typed header line** is a defensible default — operationally simple, debuggable with shell tools, and good enough for most data-engineering use cases.
3. **`@artifact` decorator concept is correct** even though the implementation needs fixing — typed step outputs with versioning is the right abstraction.
4. **The split between `ArtifactStore` (storage) and `PipelineContext` (registry) is conceptually right**, even if the boundaries leak in practice.
5. **`RunState` as a JSONL event log** is a reasonable starting shape; the issue is the *mutation* of the file, not the schema.

### Biggest risks (in order)

1. **The `_flush` design will fail the first time someone runs a 500-step pipeline on S3.** This is not theoretical — it's deterministic at moderate scale.
2. **The PDF/S3 domain leak means the project is two systems pretending to be one.** Whichever direction you pick (general orchestrator OR PDF-processing pipeline), the other half is technical debt.
3. **No tests + no CI means every refactor is a coin flip.** This compounds every other risk.
4. **The "no retries / no timeouts / no parallelism" gap between marketing and code** will burn early users who trust the README.
5. **Global registry + module-level singletons** will block multi-tenancy harder than any other single decision.

### What would break first at scale

In order:

1. State file IO (`_flush`) — at ~500 transitions.
2. Local disk for artifact downloads — at ~10 GB per step.
3. Memory in `download_jsonl` for any large state file — at ~1 GB.
4. The single-process executor — the first time someone wants a fan-out wider than 1.
5. The global registry — the first time someone embeds this in a multi-tenant service.

### What must be redesigned before production

1. State management (transactional, append-only, leased).
2. Step commit protocol (atomic two-phase).
3. Artifact identity (content-addressed, immutable).
4. Execution model (worker abstraction, retries, timeouts, cancellation).
5. Domain separation (the PDF stuff must come out of the core).

### What is unusually well-designed

- `DAG` is genuinely clean: validation, topology, queries, all separated from execution. This is the only file I would not touch architecturally.
- The decision to keep artifacts out of step-to-step memory and pass only URIs in `PipelineContext` is the right call. Steps stay memory-flat — this is the *one* place where the system is genuinely better-designed than naive in-memory DAGs.
- The schema header as the first line of every JSONL is a strong, simple convention. Keep it forever.

### Overall architectural score

- As-is against ambition (multi-tenant, distributed, K8s-native, mission-critical): **3.5 / 10**
- As-is against "small internal batch-processing tool": **6 / 10**
- After Phase 0 + Phase 1: **6 / 10** (production-viable for small workloads)
- After Phase 2: **7.5 / 10** (competitive with Airflow for single-tenant teams)
- After Phase 4: **8.5 / 10** (competitive with Dagster/Prefect for self-hosted multi-tenant deployments)

The gap between current and "real" is large but tractable. The core abstractions are right enough that you can evolve rather than rewrite — provided Phase 0 (tests + CI + dead-code removal) happens before *any* feature work, and Phase 1 (state correctness + commit protocol) happens before any production deploy. The single highest-leverage improvement you can make tomorrow is **add `pytest` + a `moto`-backed S3 integration test + a CI workflow**; everything else gets easier once that's in place.
