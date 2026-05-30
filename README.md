# runlet

DAG pipeline orchestration engine with memory-efficient JSONL streaming, pluggable artifact storage, and optional agentic LLM steps.

## Features

- **DAG-based orchestration** — define steps and dependencies, run them in topological order
- **JSONL artifact streaming** — step outputs are versioned, schema-annotated JSONL streams; large datasets never fully load into memory
- **Typed artifacts** — Pydantic-backed artifact records with automatic schema evolution
- **Pluggable artifact stores** — filesystem (default), S3; register custom backends
- **Pluggable metastore** — persist run state and step history to PostgreSQL, CockroachDB, or a no-op store
- **LLM step support** — built-in `LLMProxy` wraps OpenAI + Instructor for structured agentic steps
- **Web UI** — FastAPI-powered dashboard for monitoring pipeline runs
- **CLI** — `runlet` command for running and inspecting pipelines

## Install

```bash
# Core (filesystem artifacts, no-op metastore)
pip install "runlet @ git+https://github.com/parthlaw/runlet.git"

# With S3 artifact storage
pip install "runlet[s3] @ git+https://github.com/parthlaw/runlet.git"

# With LLM step support
pip install "runlet[llm] @ git+https://github.com/parthlaw/runlet.git"

# With PostgreSQL metastore
pip install "runlet[postgres] @ git+https://github.com/parthlaw/runlet.git"

# With web UI
pip install "runlet[ui] @ git+https://github.com/parthlaw/runlet.git"

# Everything
pip install "runlet[s3,llm,postgres,ui] @ git+https://github.com/parthlaw/runlet.git"
```

## Quickstart

```python
from runlet import build_runner

runner = build_runner("config/pipeline.json")
result = runner.run(run_id="run-001")
```

## Define steps

```python
from pydantic import BaseModel
from runlet import artifact, BaseStep, PipelineContext

@artifact(version=1)
class ExtractRecord(BaseModel):
    page: int
    text: str

class ExtractStep(BaseStep):
    def execute(self, context: PipelineContext):
        yield ExtractRecord(page=1, text="hello")

class SummarizeStep(BaseStep):
    def execute(self, context: PipelineContext):
        for record in context.iter_artifacts("extract", ExtractRecord):
            ...
```

## Configure a pipeline

```json
{
  "steps": [
    { "name": "extract", "class": "myapp.steps.ExtractStep" },
    { "name": "summarize", "class": "myapp.steps.SummarizeStep", "depends_on": ["extract"] }
  ]
}
```

## CLI

```bash
runlet run config/pipeline.json --run-id run-001
runlet status run-001
```

## License

MIT
