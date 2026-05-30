# pipeline-runner

DAG pipeline orchestration engine with memory-efficient JSONL streaming and pluggable artifact storage (S3 by default).

## Install

```bash
# S3 support (default production backend)
pip install -e "/path/to/pipeline-runner[s3]"

# Filesystem-only (no boto3)
pip install -e /path/to/pipeline-runner
```

## Usage

```python
from pipeline_runner import build_runner

runner = build_runner("config/pipeline.json", initial_metadata={"source_key": "...", "bucket": "..."})
result = runner.run(run_id="run-001")
```

## Typed artifacts

```python
from dataclasses import dataclass
from pipeline_runner import artifact, BaseStep, PipelineContext

@artifact(version=1)
@dataclass
class ExtractRecord:
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

Each step output is a JSONL file: line 1 is a schema header; following lines are typed records.

## Public API

- `build_runner`, `SequentialRunner`, `RunnerConfig`, `RunResult`
- `DAG`, `PipelineConfig`
- `PipelineContext` — `iter_artifacts(step, RecordType)`
- `artifact`, `BaseArtifact`, `ArtifactSerializer`
- `ArtifactStore`, `S3ArtifactStore`, `S3Config`, `FilesystemStore`, `build_store`
- `RunState`, `RunStatus`, `StepStatus`
- `BaseStep`
