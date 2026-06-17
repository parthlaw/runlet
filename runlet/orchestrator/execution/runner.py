"""WorkflowRunner — executes a pipeline DAG via a pluggable executor."""

from __future__ import annotations

import copy
import dataclasses
import logging
import re
import threading
import traceback
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runlet.metastore.metastore import StepRecord

from runlet.artifact_store import build_runtime_stores
from runlet.orchestrator.config.models import PipelineConfig
from runlet.orchestrator.config.runner import RunnerConfig, RunResult
from runlet.orchestrator.context.run_context import RunContext, build_context
from runlet.orchestrator.execution.executor import Executor, build_executor
from runlet.orchestrator.execution.step_runner import StepRunner
from runlet.orchestrator.graph.dag import DAG
from runlet.orchestrator.registry.registry import ConfigStepRegistry, StepRegistry
from runlet.orchestrator.state.state import RunState

logger = logging.getLogger(__name__)

_SAFE_RUN_ID = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")


def _validate_run_id(run_id: str) -> None:
    if not _SAFE_RUN_ID.match(run_id):
        raise ValueError(
            f"run_id {run_id!r} contains unsafe characters. "
            "Only alphanumeric, hyphen, and underscore are allowed (max 128 chars)."
        )


class WorkflowRunner:
    """Executes a pipeline DAG via a pluggable Executor.

    The executor is selected from :attr:`RunnerConfig.executor`. Defaults to
    :class:`~runlet.orchestrator.execution.executor.SequentialExecutor` (single-threaded,
    no thread pool).

    To supply a custom executor, pass an instance directly via the ``executor``
    parameter. When provided, the ``executor`` block in :class:`RunnerConfig`
    is ignored for executor selection.
    """

    def __init__(
        self,
        dag: DAG,
        runner_config: RunnerConfig | None = None,
        initial_metadata: dict[str, Any] | None = None,
        llm: Any | None = None,
        metastore: Any | None = None,
        step_registry: StepRegistry | None = None,
        executor: Executor | None = None,
    ) -> None:
        self._dag = dag
        self._config = runner_config or dag.config.runner
        self._initial_metadata: dict[str, Any] = initial_metadata or {}
        self._cancel_event = threading.Event()
        self._llm = llm
        self._registry: StepRegistry = step_registry or ConfigStepRegistry(dag.config)
        self._registry.validate(dag.config.step_names)
        self._executor = executor
        if metastore is not None:
            self._metastore = metastore
        else:
            from runlet.metastore import build_metastore

            self._metastore = build_metastore(self._config.metastore)

        # Ensure tables exist; CREATE TABLE IF NOT EXISTS makes this idempotent.
        try:
            self._metastore.init_schema()
        except Exception as exc:
            logger.warning("Metastore init_schema() failed (non-fatal): %s", exc)

    def cancel(self) -> None:
        """Signal the runner to stop dispatching new steps after the current ones complete."""
        self._cancel_event.set()

    def run(self, run_id: str) -> RunResult:
        _validate_run_id(run_id)

        pipeline_cfg = self._dag.config
        context, state = self._build_run_context(run_id, pipeline_cfg)
        _safe_metastore(self._metastore.record_run_started, run_id, pipeline_cfg.name)

        step_runner = StepRunner(
            run_id=run_id,
            pipeline_cfg=pipeline_cfg,
            state=state,
            context=context,
            metastore=self._metastore,
            registry=self._registry,
        )
        executor = (
            self._executor
            if self._executor is not None
            else build_executor(self._config.executor)
        )

        try:
            executor.run(
                dag=self._dag,
                state=state,
                execute_fn=step_runner,
                cancel_event=self._cancel_event,
            )
        except Exception as exc:
            error = (
                step_runner.failure_info.get("error")
                or f"Orchestrator error: {exc}\n{traceback.format_exc()}"
            )
            state.mark_run_failed(error=error)
            _safe_metastore(self._metastore.record_run_failed, run_id, error)
            _safe_metastore(self._metastore.close)
            return self._build_run_result(
                "FAILED", run_id, context, step_runner,
                failed_step=step_runner.failure_info.get("step"),
                error=error,
            )

        if self._cancel_event.is_set():
            state.mark_run_cancelled()
            _safe_metastore(self._metastore.record_run_cancelled, run_id)
            _safe_metastore(self._metastore.close)
            return self._build_run_result("CANCELLED", run_id, context, step_runner)

        state.mark_run_success()
        _safe_metastore(self._metastore.record_run_success, run_id, context.list_outputs())
        _safe_metastore(self._metastore.close)
        logger.info(
            "Pipeline '%s' finished. Executed: %s | Skipped: %s",
            pipeline_cfg.name,
            step_runner.steps_executed,
            step_runner.steps_skipped,
        )
        return self._build_run_result("SUCCESS", run_id, context, step_runner)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_run_context(
        self, run_id: str, pipeline_cfg: PipelineConfig
    ) -> tuple[RunContext, RunState]:
        """Build artifact stores, writer context, and initialize (or restore) RunState."""
        store, upload_store, _ = build_runtime_stores(
            pipeline_cfg.store,
            self._initial_metadata,
        )
        context = build_context(
            run_id=run_id,
            pipeline_name=pipeline_cfg.name,
            store=store,
            upload_store=upload_store,
            metadata=self._initial_metadata.copy(),
            llm=self._llm,
            cancel_event=self._cancel_event,
        )
        state = self._initialise_state(run_id, pipeline_cfg, context)
        return context, state

    def _initialise_state(
        self,
        run_id: str,
        pipeline_cfg: PipelineConfig,
        context: RunContext,
    ) -> RunState:
        if self._config.resume:
            try:
                records = self._metastore.list_steps(run_id)
                if records:
                    state = RunState.restore_from_records(
                        run_id=run_id,
                        pipeline_name=pipeline_cfg.name,
                        records=records,
                    )
                    context.restore_outputs(_outputs_from_records(records))
                    return state
                logger.warning(
                    "resume=True for run '%s' but no prior records found in metastore. "
                    "Starting fresh. Configure a persistent metastore to enable resume.",
                    run_id,
                )
            except Exception as exc:
                logger.warning(
                    "Could not load state for run '%s' from metastore (reason: %s). "
                    "Starting fresh.",
                    run_id,
                    exc,
                )

        return RunState(run_id=run_id, pipeline_name=pipeline_cfg.name)

    def _build_run_result(
        self,
        status: str,
        run_id: str,
        context: RunContext,
        step_runner: StepRunner,
        *,
        failed_step: str | None = None,
        error: str | None = None,
    ) -> RunResult:
        """Construct a RunResult — eliminates the 3x repeated construction in run()."""
        return RunResult(
            run_id=run_id,
            success=(status == "SUCCESS"),
            status=status,
            steps_executed=step_runner.steps_executed,
            steps_skipped=step_runner.steps_skipped,
            failed_step=failed_step,
            error=error,
            metadata=copy.deepcopy(dict(context.metadata)),
            outputs=context.list_outputs(),
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _safe_metastore(fn: Any, *args: Any) -> None:
    """Call a metastore method, logging any failure without raising."""
    try:
        fn(*args)
    except Exception as exc:
        logger.warning("Metastore write failed (non-fatal): %s: %s", fn.__name__, exc)


def _outputs_from_records(records: list[StepRecord]) -> dict[str, dict[str, Any]]:
    """Extract successful step outputs from metastore records.

    Groups by step_name and picks the output from the successful attempt.
    Retry history (attempt=1 FAILED + attempt=2 SUCCESS) is handled correctly:
    only the successful attempt's output is returned.
    """
    by_step: dict[str, list[StepRecord]] = defaultdict(list)
    for rec in records:
        by_step[rec.step_name].append(rec)

    outputs: dict[str, dict[str, Any]] = {}
    for step_name, attempts in by_step.items():
        success = next((r for r in attempts if r.status == "success"), None)
        if success is not None:
            outputs[step_name] = success.output
    return outputs


def build_runner(
    config_path: Path | str,
    resume: bool = False,
    initial_metadata: dict[str, Any] | None = None,
    executor: Executor | None = None,
) -> WorkflowRunner:
    """Factory: load a pipeline JSON config and return a ready-to-run WorkflowRunner.

    Parameters
    ----------
    config_path:
        Path to the pipeline JSON config file.
    resume:
        If True, skip steps already recorded as complete in the metastore.
    initial_metadata:
        Domain/business values accessible via ``context.metadata`` during execution
        (e.g. ``source_key``, ``user_id``).
    executor:
        Optional custom executor instance. When supplied, the ``executor`` block
        in the pipeline config is ignored and this instance is used directly.
        The executor must satisfy the :class:`~runlet.orchestrator.execution.executor.Executor`
        protocol, or be a subclass of
        :class:`~runlet.orchestrator.execution.executor.BaseExecutor`.
    """
    pipeline_cfg = PipelineConfig.from_file(config_path)

    runner_cfg = pipeline_cfg.runner
    if resume:
        runner_cfg = dataclasses.replace(runner_cfg, resume=True)

    llm = None
    if pipeline_cfg.llm is not None:
        from runlet.llm.proxy import LLMProxy

        llm = LLMProxy.from_config(pipeline_cfg.llm)

    dag = DAG(pipeline_cfg)
    return WorkflowRunner(
        dag=dag,
        runner_config=runner_cfg,
        initial_metadata=initial_metadata,
        llm=llm,
        executor=executor,
    )
