"""SequentialRunner — executes a pipeline DAG via a bounded thread pool."""

from __future__ import annotations

import concurrent.futures
import copy
import dataclasses
import json
import logging
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from runlet.artifact_store import ArtifactStore, build_runtime_stores
from runlet.orchestrator.condition_evaluator import evaluate_condition
from runlet.orchestrator.config.models import PipelineConfig, StepConfig
from runlet.orchestrator.dag import DAG
from runlet.orchestrator.errors import ConditionEvaluationError
from runlet.orchestrator.executor import ThreadedExecutor
from runlet.orchestrator.models import RunnerConfig, RunResult
from runlet.orchestrator.retry import DEFAULT_POLICY, RetryPolicy
from runlet.orchestrator.state import RunState, StepStatus
from runlet.orchestrator.writer_context import WriterContext, build_context
from runlet.steps.loader import load_step

logger = logging.getLogger(__name__)

_SAFE_RUN_ID = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")


def _validate_run_id(run_id: str) -> None:
    if not _SAFE_RUN_ID.match(run_id):
        raise ValueError(
            f"run_id {run_id!r} contains unsafe characters. "
            "Only alphanumeric, hyphen, and underscore are allowed (max 128 chars)."
        )


class SequentialRunner:
    """Executes a pipeline DAG via :class:`ThreadedExecutor`.

    Runs sequentially when max_concurrent_steps=1.
    """

    def __init__(
        self,
        dag: DAG,
        runner_config: RunnerConfig | None = None,
        initial_metadata: dict[str, Any] | None = None,
        llm: Any | None = None,
        metastore: Any | None = None,
    ) -> None:
        self._dag = dag
        self._config = runner_config or dag.config.runner
        self._initial_metadata: dict[str, Any] = initial_metadata or {}
        self._cancel_event = threading.Event()
        self._llm = llm
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
        store, upload_store, store_prefix = build_runtime_stores(
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

        state = self._initialise_state(
            run_id=run_id,
            pipeline_cfg=pipeline_cfg,
            store=store,
            store_prefix=store_prefix,
            context=context,
        )
        _safe_metastore(self._metastore.record_run_started, run_id, pipeline_cfg.name)

        steps_executed: list[str] = []
        steps_skipped: list[str] = []
        _tracking_lock = threading.Lock()
        failure_info: dict[str, str] = {}

        def execute_step(step_name: str) -> None:
            if self._cancel_event.is_set():
                return

            step_cfg = pipeline_cfg.get_step(step_name)

            if state.is_step_complete(step_name):
                logger.info("[%s] Already complete — skipping.", step_name)
                with _tracking_lock:
                    steps_skipped.append(step_name)
                return

            if _has_skipped_dependency(step_cfg, state):
                logger.info("[%s] Skipping — dependency was skipped.", step_name)
                state.mark_step_skipped(step_name)
                _safe_metastore(self._metastore.record_step_skipped, run_id, step_name)
                with _tracking_lock:
                    steps_skipped.append(step_name)
                return

            if step_cfg.condition is not None:
                try:
                    if not evaluate_condition(context, step_cfg.condition):
                        logger.info("[%s] Skipping — condition not met.", step_name)
                        state.mark_step_skipped(step_name)
                        _safe_metastore(self._metastore.record_step_skipped, run_id, step_name)
                        with _tracking_lock:
                            steps_skipped.append(step_name)
                        return
                except ConditionEvaluationError as exc:
                    error_msg = _format_error(step_name, exc)
                    state.mark_step_failed(
                        step_name=step_name, error=error_msg, duration_seconds=0.0
                    )
                    _safe_metastore(
                        self._metastore.record_step_failed, run_id, step_name, 1, 0.0, error_msg
                    )
                    with _tracking_lock:
                        if not failure_info:
                            failure_info["step"] = step_name
                            failure_info["error"] = error_msg
                    raise

            try:
                step_instance = load_step(step_cfg)
            except Exception as exc:
                error_msg = _format_error(step_name, exc)
                state.mark_step_failed(step_name=step_name, error=error_msg, duration_seconds=0.0)
                _safe_metastore(
                    self._metastore.record_step_failed, run_id, step_name, 1, 0.0, error_msg
                )
                with _tracking_lock:
                    if not failure_info:
                        failure_info["step"] = step_name
                        failure_info["error"] = error_msg
                raise

            policy = RetryPolicy.from_config(step_cfg.retry) if step_cfg.retry else DEFAULT_POLICY
            attempt = 0
            started_at = time.monotonic()
            success_flag = False

            try:
                while True:
                    attempt += 1
                    state.mark_step_running(step_name, attempt=attempt)
                    _safe_metastore(self._metastore.record_step_running, run_id, step_name, attempt)
                    started_at = time.monotonic()
                    try:
                        output = _execute_with_timeout(
                            step_instance=step_instance,
                            context=context,
                            step_name=step_name,
                            step_cfg=step_cfg,
                        )
                        context.set_output(step_name, output)
                        success_flag = True
                        break
                    except Exception as exc:
                        duration = time.monotonic() - started_at
                        logger.warning(
                            "[%s] Attempt %d/%d failed: %s",
                            step_name, attempt, policy.max_attempts, exc,
                        )
                        if policy.should_retry(attempt, exc):
                            retry_error = _format_error(step_name, exc)
                            state.mark_step_failed(
                                step_name=step_name,
                                error=retry_error,
                                duration_seconds=duration,
                                attempt=attempt,
                            )
                            _safe_metastore(
                                self._metastore.record_step_failed,
                                run_id, step_name, attempt, duration, retry_error,
                            )
                            policy.wait_before_retry(attempt)
                            logger.info("[%s] Retrying (attempt %d)...", step_name, attempt + 1)
                        else:
                            raise

                duration = time.monotonic() - started_at
                step_out = output
                state.mark_step_success(
                    step_name=step_name,
                    output=step_out,
                    duration_seconds=duration,
                    attempt=attempt,
                )
                _safe_metastore(
                    self._metastore.record_step_success,
                    run_id,
                    step_name,
                    attempt,
                    duration,
                    step_out,
                )
                with _tracking_lock:
                    steps_executed.append(step_name)
                logger.debug("[%s] Completed → output keys: %s", step_name, list(step_out))

            except Exception as exc:
                duration = time.monotonic() - started_at
                error_msg = _format_error(step_name, exc)
                state.mark_step_failed(
                    step_name=step_name,
                    error=error_msg,
                    duration_seconds=duration,
                    attempt=attempt,
                )
                _safe_metastore(
                    self._metastore.record_step_failed,
                    run_id, step_name, attempt, duration, error_msg,
                )
                with _tracking_lock:
                    if not failure_info:
                        failure_info["step"] = step_name
                        failure_info["error"] = error_msg
                raise
            finally:
                try:
                    step_instance.teardown(context, success_flag)
                except Exception as te:
                    logger.warning("[%s] teardown() raised: %s", step_name, te)

        executor = ThreadedExecutor(max_workers=self._config.max_concurrent_steps)

        try:
            executor.run(
                dag=self._dag,
                state=state,
                execute_fn=execute_step,
                cancel_event=self._cancel_event,
            )
        except Exception as exc:
            error = (
                failure_info.get("error")
                or f"Orchestrator error: {exc}\n{traceback.format_exc()}"
            )
            state.mark_run_failed(error=error)
            _safe_metastore(self._metastore.record_run_failed, run_id, error)
            _safe_metastore(self._metastore.close)
            return RunResult(
                run_id=run_id,
                success=False,
                status="FAILED",
                steps_executed=steps_executed,
                steps_skipped=steps_skipped,
                failed_step=failure_info.get("step"),
                error=error,
                state_uri=state.store_uri,
                metadata=copy.deepcopy(dict(context.metadata)),
            )

        if self._cancel_event.is_set():
            state.mark_run_cancelled()
            _safe_metastore(self._metastore.record_run_cancelled, run_id)
            _safe_metastore(self._metastore.close)
            return RunResult(
                run_id=run_id,
                success=False,
                status="CANCELLED",
                steps_executed=steps_executed,
                steps_skipped=steps_skipped,
                failed_step=None,
                error=None,
                state_uri=state.store_uri,
                metadata=copy.deepcopy(dict(context.metadata)),
            )

        state.mark_run_success()
        _safe_metastore(self._metastore.record_run_success, run_id, context.list_outputs())
        _safe_metastore(self._metastore.close)
        logger.info(
            "Pipeline '%s' finished. Executed: %s | Skipped: %s",
            pipeline_cfg.name,
            steps_executed,
            steps_skipped,
        )
        return RunResult(
            run_id=run_id,
            success=True,
            status="SUCCESS",
            steps_executed=steps_executed,
            steps_skipped=steps_skipped,
            failed_step=None,
            error=None,
            state_uri=state.store_uri,
            metadata=copy.deepcopy(dict(context.metadata)),
        )

    def _initialise_state(
        self,
        run_id: str,
        pipeline_cfg: PipelineConfig,
        store: ArtifactStore,
        store_prefix: str,
        context: WriterContext,
    ) -> RunState:
        if self._config.resume:
            try:
                state = RunState.load_existing(
                    run_id=run_id,
                    pipeline_name=pipeline_cfg.name,
                    store=store,
                    store_prefix=store_prefix,
                )
                context.restore_outputs(state.all_step_outputs())
                logger.info("Resuming run '%s'.", run_id)
                return state
            except Exception as exc:
                logger.warning(
                    "Could not load existing state for run '%s' (reason: %s). "
                    "Starting fresh.",
                    run_id,
                    exc,
                )

        return RunState.create_new(
            run_id=run_id,
            pipeline_name=pipeline_cfg.name,
            store=store,
            store_prefix=store_prefix,
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


def _execute_with_timeout(
    *,
    step_instance: Any,
    context: WriterContext,
    step_name: str,
    step_cfg: StepConfig,
) -> dict[str, Any]:
    """
    Call step_instance.execute(context) and return its dict output.

    If timeout_seconds is set, raises TimeoutError when exceeded.

    KNOWN LIMITATION: when the timeout fires the step thread is NOT killed —
    Python does not support thread cancellation. The thread leaks until the
    step naturally returns or the process exits.
    """
    def _run() -> dict[str, Any]:
        output = step_instance.execute(context)
        if not isinstance(output, dict):
            raise TypeError(
                f"Step '{step_name}' must return a dict, got {type(output).__name__}. "
                "Return a JSON-serializable dict from execute()."
            )
        try:
            json.dumps(output)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"Step '{step_name}' returned a non-JSON-serializable dict: {exc}"
            ) from exc
        return output

    timeout_s = step_cfg.config.get("timeout_seconds")
    if timeout_s is None:
        return _run()

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_run)
    try:
        result = future.result(timeout=float(timeout_s))
        pool.shutdown(wait=False)
        return result
    except concurrent.futures.TimeoutError:
        pool.shutdown(wait=False)
        raise TimeoutError(
            f"Step {step_name!r} exceeded timeout of {timeout_s}s. "
            "The step thread continues running in the background."
        ) from None


def _has_skipped_dependency(step_cfg: StepConfig, state: RunState) -> bool:
    return any(
        state.step_status(dep) == StepStatus.SKIPPED for dep in step_cfg.depends_on
    )


def _format_error(step_name: str, exc: Exception) -> str:
    return (
        f"Step '{step_name}' raised {type(exc).__name__}: {exc}\n"
        f"{traceback.format_exc()}"
    )


def build_runner(
    config_path: Path | str,
    resume: bool = False,
    initial_metadata: dict[str, Any] | None = None,
) -> SequentialRunner:
    """Factory: load a pipeline JSON config and return a ready-to-run SequentialRunner."""
    pipeline_cfg = PipelineConfig.from_file(config_path)

    runner_cfg = pipeline_cfg.runner
    if resume:
        runner_cfg = dataclasses.replace(runner_cfg, resume=True)

    llm = None
    if pipeline_cfg.llm is not None:
        from runlet.llm.proxy import LLMProxy

        llm = LLMProxy.from_config(pipeline_cfg.llm)

    dag = DAG(pipeline_cfg)
    return SequentialRunner(
        dag=dag,
        runner_config=runner_cfg,
        initial_metadata=initial_metadata,
        llm=llm,
    )
