# runlet

DAG pipeline orchestration engine. Steps return JSON; run state and outputs are persisted in SQL via a pluggable metastore. Optional artifact storage for large data passed between steps.

## Features

- **DAG-based orchestration** — define steps with dependencies; executed in topological order with optional parallel execution
- **JSON step outputs** — steps return plain `dict`s, stored directly in the metastore; no serialization ceremony
- **SQL metastore** — run status and step outputs persisted in SQLite, PostgreSQL, or CockroachDB; no-op by default
- **Resume support** — re-run a pipeline run ID and completed steps are skipped automatically
- **Retry with backoff** — per-step retry policy with exponential backoff and jitter
- **Conditional execution** — skip steps based on upstream output values
- **Pluggable artifact stores** — filesystem or S3 for passing large files/blobs between steps (optional)
- **JSONL streaming helpers** — memory-efficient large dataset handoff via URI references (optional)
- **LLM step support** — `LLMProxy` wraps OpenAI + Instructor for structured agentic steps (optional)
- **Web UI** — FastAPI dashboard for monitoring runs (optional)

## Install

```bash
# Core (no-op metastore, no artifact store)
pip install "runlet @ git+https://github.com/parthlaw/runlet.git"

# With SQLite metastore (stdlib, no extra deps)
pip install "runlet @ git+https://github.com/parthlaw/runlet.git"

# With PostgreSQL metastore
pip install "runlet[postgres] @ git+https://github.com/parthlaw/runlet.git"

# With S3 artifact storage
pip install "runlet[s3] @ git+https://github.com/parthlaw/runlet.git"

# With LLM step support
pip install "runlet[llm] @ git+https://github.com/parthlaw/runlet.git"

# With web UI
pip install "runlet[ui] @ git+https://github.com/parthlaw/runlet.git"

# Everything
pip install "runlet[s3,llm,postgres,ui] @ git+https://github.com/parthlaw/runlet.git"
```

## Quickstart

### Decorator DSL

```python
from runlet import Pipeline

pipe = Pipeline("my-pipeline")

@pipe.step("extract")
def extract(context):
    return {"count": 42, "status": "ok"}

@pipe.step("transform", depends_on=["extract"])
def transform(context):
    upstream = context.get_output("extract")
    return {"result": upstream["count"] * 2}

result = pipe.run("run-001")
print(result.success)   # True
print(result.outputs)   # {"extract": {...}, "transform": {...}}
```

### JSON config

```python
from runlet import build_runner

runner = build_runner("pipeline.json")
result = runner.run("run-001")
```

## Define steps

Steps subclass `BaseStep` and return a JSON-serializable `dict`. State and outputs are managed entirely by the metastore — steps do not yield, write files, or interact with storage directly unless they need to pass large data.

```python
from runlet import BaseStep, RuntimeContext

class ExtractStep(BaseStep):
    def execute(self, context: RuntimeContext) -> dict:
        return {"count": 42, "status": "ok"}

class TransformStep(BaseStep):
    def execute(self, context: RuntimeContext) -> dict:
        upstream = context.get_output("extract")  # dict from prior step
        return {"result": upstream["count"] * 2}
```

### Context API

| Property / Method | Description |
|---|---|
| `context.run_id` | Unique ID for this pipeline run |
| `context.pipeline_name` | Pipeline name |
| `context.metadata` | Read-only dict of metadata passed at run time |
| `context.get_output(step_name)` | Output dict from a completed upstream step |
| `context.has_output(step_name)` | Check if a step has completed |
| `context.store` | Artifact store (only present when configured) |
| `context.llm` | LLM proxy (only present when configured) |

### Optional lifecycle hooks

```python
class MyStep(BaseStep):
    def validate_config(self) -> None:
        self.require_config("api_key")  # raises ValueError if missing

    def execute(self, context: RuntimeContext) -> dict:
        ...

    def teardown(self, context: RuntimeContext, success: bool) -> None:
        ...  # cleanup regardless of outcome
```

## Configure a pipeline

```json
{
  "pipeline": {
    "name": "my-pipeline"
  },
  "runner": {
    "metastore": {
      "type": "sqlite",
      "db_path": "pipeline.db"
    }
  },
  "steps": [
    {
      "name": "extract",
      "module": "myapp.steps",
      "class": "ExtractStep"
    },
    {
      "name": "transform",
      "module": "myapp.steps",
      "class": "TransformStep",
      "depends_on": ["extract"],
      "config": {
        "multiplier": 3
      }
    }
  ]
}
```

### Step options

| Field | Description |
|---|---|
| `name` | Unique step identifier |
| `module` | Python module path |
| `class` | Class name within the module |
| `depends_on` | List of step names that must complete first |
| `config` | Dict passed to `self.config` inside the step |
| `retry` | Retry policy (see below) |
| `condition` | Skip condition based on upstream output (see below) |

### Retry policy

```json
"retry": {
  "max_attempts": 3,
  "backoff_base": 2.0,
  "jitter_range": 0.1
}
```

### Conditional execution

```json
"condition": {
  "step": "extract",
  "field": "status",
  "op": "==",
  "value": "ok"
}
```

Supported operators: `==`, `!=`, `>`, `<`, `>=`, `<=`. Use dot notation for nested fields (`"field": "meta.count"`). If the condition is false the step is marked `SKIPPED` and downstream dependents are also skipped.

## Metastore

The metastore persists run and step lifecycle state (status, outputs, errors, durations) in SQL. It is the single source of truth for pipeline state — there is no separate state file.

Configure in `runner.metastore`:

```json
{ "type": "noop" }
```
```json
{ "type": "sqlite", "db_path": "/var/data/pipeline.db" }
```
```json
{ "type": "postgres", "dsn": "postgresql://user:pass@localhost/runlet" }
```
```json
{ "type": "cockroachdb", "dsn": "postgresql://user:pass@crdb-host:26257/db?sslmode=require" }
```

`noop` is the default — all writes are silent no-ops and reads return empty results. Use `sqlite` for local development or single-process deployments with no external dependencies.

### Resume

Pass `resume=True` to `build_runner()` (or set `"resume": true` in `runner` config) to skip already-completed steps when re-running a `run_id`:

```python
runner = build_runner("pipeline.json", resume=True)
result = runner.run("run-001")  # completed steps are skipped
```

### Programmatic access

```python
from runlet import build_metastore, build_metastore_config

cfg = build_metastore_config({"type": "sqlite", "db_path": "pipeline.db"})
ms = build_metastore(cfg)
ms.init_schema()

run = ms.get_run("run-001")
steps = ms.list_steps("run-001")
```

## Large data between steps

Step outputs are stored in SQL and should remain small (JSON summaries, counts, URIs). For large datasets, write to the artifact store and put the URI in the output dict:

```python
from runlet.utils.streaming import write_jsonl, iter_jsonl
from pydantic import BaseModel

class Record(BaseModel):
    id: int
    value: str

class ProducerStep(BaseStep):
    def execute(self, context: RuntimeContext) -> dict:
        records = (Record(id=i, value=f"row-{i}") for i in range(100_000))
        uri = write_jsonl(records, context.store, f"{context.run_id}/producer/data.jsonl")
        return {"data_uri": uri, "count": 100_000}

class ConsumerStep(BaseStep):
    def execute(self, context: RuntimeContext) -> dict:
        upstream = context.get_output("producer")
        for record in iter_jsonl(upstream["data_uri"], context.store, Record):
            process(record)
        return {"processed": upstream["count"]}
```

JSONL helpers require an artifact store to be configured.

## Artifact store

Required only when steps pass large files or use `write_jsonl`/`iter_jsonl`. Configure in the top-level `store` key:

```json
{ "type": "filesystem", "base_dir": "/var/artifacts", "prefix": "runs/" }
```

```json
{
  "type": "s3",
  "bucket": "my-bucket",
  "region": "us-east-1",
  "prefix": "pipelines/"
}
```

S3-compatible endpoints (LocalStack, MinIO) are supported via `"endpoint_url"`.

### Custom store

```python
from runlet.artifact_store import ArtifactStore, register_store

class MyStore(ArtifactStore):
    ...

register_store("mystore", MyStore)
```

## LLM steps

When `llm` is configured, steps can call `context.llm.complete()` for structured LLM output via [Instructor](https://github.com/jxnl/instructor):

```json
{
  "llm": {
    "model": "gpt-4o-mini",
    "api_key_env": "OPENAI_API_KEY"
  }
}
```

```python
from pydantic import BaseModel

class Sentiment(BaseModel):
    label: str
    score: float

class AnalyzeStep(BaseStep):
    def execute(self, context: RuntimeContext) -> dict:
        result = context.llm.complete(
            messages=[{"role": "user", "content": "Analyze: great product!"}],
            response_model=Sentiment,
        )
        return {"label": result.label, "score": result.score}
```

Requires `pip install runlet[llm]`.

## Web UI

```bash
runlet serve --config pipeline.json --host 0.0.0.0 --port 8000

# Multiple pipeline configs
runlet serve --config pipeline-a.json --config pipeline-b.json
```

Requires `pip install runlet[ui]`.

## Pass metadata at run time

```python
runner = build_runner(
    "pipeline.json",
    initial_metadata={"user_id": 42, "source": "s3://bucket/input.csv"},
)
result = runner.run("run-001")
```

Steps read metadata via `context.metadata["user_id"]`. Metadata is immutable during a run.

## Inspect results

```python
result = runner.run("run-001")

result.success          # bool
result.status           # "SUCCESS" | "FAILED" | "CANCELLED"
result.outputs          # {step_name: output_dict, ...}
result.steps_executed   # ["extract", "transform"]
result.steps_skipped    # ["notify"]
result.error            # error message if failed, else None
```
