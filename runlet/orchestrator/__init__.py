"""
orchestrator — DAG pipeline execution engine.

Public surface
--------------
    from runlet.orchestrator.config.models import PipelineConfig
    from runlet.orchestrator.config.runner import ExecutorConfig, RunnerConfig, RunResult
    from runlet.orchestrator.graph.dag import DAG
    from runlet.orchestrator.execution.runner import WorkflowRunner, build_runner
    from runlet.orchestrator.context.run_context import RunContext, build_context
    from runlet.orchestrator.context.step_context import StepContext
    from runlet.orchestrator.state.state import RunState, StepStatus, RunStatus
    from runlet.orchestrator.errors import (
        ConfigValidationError, CyclicDependencyError, ConditionEvaluationError
    )

For typical usage, :func:`runlet.orchestrator.execution.runner.build_runner` is all you need:

    runner = build_runner("config/pipeline.json")
    result = runner.run(run_id="run-001")
"""
