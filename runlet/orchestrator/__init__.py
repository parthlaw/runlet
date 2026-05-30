"""
orchestrator — DAG pipeline execution engine.

Public surface
--------------
    from runlet.orchestrator.config import PipelineConfig
    from runlet.orchestrator.dag import DAG
    from runlet.orchestrator.models import RunnerConfig, RunResult
    from runlet.orchestrator.runner import SequentialRunner, build_runner
    from runlet.orchestrator.context import PipelineContext
    from runlet.orchestrator.state import RunState, StepStatus, RunStatus
    from runlet.orchestrator.errors import (
        ConfigValidationError, CyclicDependencyError, ConditionEvaluationError
    )

For typical usage, :func:`runlet.orchestrator.runner.build_runner` is all you need:

    runner = build_runner("config/pipeline.json")
    result = runner.run(run_id="run-001")
"""
