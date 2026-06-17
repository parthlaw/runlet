"""StepRunner — callable that executes a single pipeline step end-to-end.

The executor (SequentialExecutor / ThreadedExecutor) owns *scheduling*:
which steps to call and in what order or concurrency.

StepRunner owns *execution*: what happens when the executor dispatches a
step name — skip resolution, registry lookup, retry loop, output validation,
and metastore recording.

Thread safety
-------------
``_steps_executed``, ``_steps_skipped``, and ``_failure_info`` are mutated
from executor worker threads (ThreadedExecutor) and protected by
``_tracking_lock``. The ``steps_executed``, ``steps_skipped``, and
``failure_info`` properties return copies.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from typing import Any

from runlet.orchestrator.config.models import PipelineConfig, StepConfig
from runlet.orchestrator.errors import ConditionEvaluationError
from runlet.orchestrator.execution.retry import DEFAULT_POLICY, RetryPolicy
from runlet.orchestrator.registry.registry import StepRegistry
from runlet.orchestrator.state.condition_evaluator import evaluate_condition
from runlet.orchestrator.state.state import RunState, StepStatus
from runlet.orchestrator.context.run_context import RunContext
from runlet.orchestrator.context.step_context import StepContext

logger = logging.getLogger(__name__)


def _safe_metastore(fn: Any, *args: Any) -> None:
    """Call a metastore method, logging any failure without raising."""
    try:
        fn(*args)
    except Exception as exc:
        logger.warning("Metastore write failed (non-fatal): %s: %s", fn.__name__, exc)


class StepRunner:
    """Callable executed by the executor for each step in the DAG.

    Instantiate once per pipeline run and pass ``__call__`` (or the instance
    itself) to ``executor.run()`` as ``execute_fn``.

    Parameters
    ----------
    run_id:
        The active run identifier — forwarded to every metastore write.
    pipeline_cfg:
        Resolved pipeline configuration — used to look up per-step config.
    state:
        Mutable in-memory run state shared with the executor.
    context:
        Writer context for the run — steps receive a read-only view of this.
    metastore:
        Metastore instance; writes are wrapped in ``_safe_metastore`` so
        failures are logged but never propagate to the executor.
    registry:
        Step registry used to resolve step names to step instances.
    """

    def __init__(
        self,
        run_id: str,
        pipeline_cfg: PipelineConfig,
        state: RunState,
        context: RunContext,
        metastore: Any,
        registry: StepRegistry,
    ) -> None:
        self._run_id = run_id
        self._pipeline_cfg = pipeline_cfg
        self._state = state
        self._run_context = context
        self._metastore = metastore
        self._registry = registry

        self._tracking_lock = threading.Lock()
        self._steps_executed: list[str] = []
        self._steps_skipped: list[str] = []
        self._failure_info: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public read-only properties (consumed by WorkflowRunner after run)
    # ------------------------------------------------------------------

    @property
    def steps_executed(self) -> list[str]:
        with self._tracking_lock:
            return list(self._steps_executed)

    @property
    def steps_skipped(self) -> list[str]:
        with self._tracking_lock:
            return list(self._steps_skipped)

    @property
    def failure_info(self) -> dict[str, str]:
        with self._tracking_lock:
            return dict(self._failure_info)

    # ------------------------------------------------------------------
    # Executor interface
    # ------------------------------------------------------------------

    def __call__(self, step_name: str) -> None:
        """Execute one step. Raises on unrecoverable failure so the executor
        can cancel remaining work."""

        run_id = self._run_id

        # --- Already complete (resume path) ---
        if self._state.is_step_complete(step_name):
            logger.info("[%s] Already complete — skipping.", step_name)
            with self._tracking_lock:
                self._steps_skipped.append(step_name)
            return

        step_cfg = self._pipeline_cfg.get_step(step_name)

        # Build the read-only step view for this dispatch
        step_context = StepContext(self._run_context)

        # --- Skip resolution (dependency skip + condition skip) ---
        if self._should_skip(step_name, step_cfg, step_context):
            return

        # --- Registry lookup ---
        try:
            step_instance = self._registry.get(step_name)
        except Exception as exc:
            error_msg = _format_error(step_name, exc)
            self._state.mark_step_failed(
                step_name=step_name, error=error_msg, duration_seconds=0.0
            )
            _safe_metastore(
                self._metastore.record_step_failed,
                run_id, step_name, 1, 0.0, error_msg,
            )
            self._record_first_failure(step_name, error_msg)
            raise

        # --- Retry loop ---
        success_flag = False
        try:
            output, duration, attempt = self._run_with_retry(
                step_name, step_cfg, step_instance, step_context
            )
            self._state.mark_step_success(
                step_name=step_name,
                duration_seconds=duration,
                attempt=attempt,
            )
            _safe_metastore(
                self._metastore.record_step_success,
                run_id, step_name, attempt, duration, output,
            )
            self._run_context._register_output(step_name, output)
            with self._tracking_lock:
                self._steps_executed.append(step_name)
            success_flag = True
            logger.debug("[%s] Completed → output keys: %s", step_name, list(output))

        except Exception as exc:
            # _run_with_retry already recorded intermediate retry failures;
            # this records the final exhausted failure.
            duration = getattr(exc, "_duration", 0.0)
            attempt = getattr(exc, "_attempt", 1)
            error_msg = _format_error(step_name, exc)
            self._state.mark_step_failed(
                step_name=step_name,
                error=error_msg,
                duration_seconds=duration,
                attempt=attempt,
            )
            _safe_metastore(
                self._metastore.record_step_failed,
                run_id, step_name, attempt, duration, error_msg,
            )
            self._record_first_failure(step_name, error_msg)
            raise

        finally:
            try:
                step_instance.teardown(step_context, success_flag)
            except Exception as te:
                logger.warning("[%s] teardown() raised: %s", step_name, te)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _should_skip(self, step_name: str, step_cfg: StepConfig, step_context: StepContext) -> bool:
        """Evaluate dependency-skip and condition-skip rules.

        Marks the step skipped and returns True if the step should be
        bypassed. Raises ConditionEvaluationError (re-raises after
        recording failure) if condition evaluation itself fails.
        """

        run_id = self._run_id

        # Dependency skipped
        if any(
            self._state.step_status(dep) == StepStatus.SKIPPED
            for dep in step_cfg.depends_on
        ):
            logger.info("[%s] Skipping — dependency was skipped.", step_name)
            self._record_skip(step_name)
            return True

        # Condition not met
        if step_cfg.condition is not None:
            try:
                if not evaluate_condition(step_context, step_cfg.condition):
                    logger.info("[%s] Skipping — condition not met.", step_name)
                    self._record_skip(step_name)
                    return True
            except ConditionEvaluationError as exc:
                error_msg = _format_error(step_name, exc)
                self._state.mark_step_failed(
                    step_name=step_name, error=error_msg, duration_seconds=0.0
                )
                _safe_metastore(
                    self._metastore.record_step_failed,
                    run_id, step_name, 1, 0.0, error_msg,
                )
                self._record_first_failure(step_name, error_msg)
                raise

        return False

    def _record_skip(self, step_name: str) -> None:

        self._state.mark_step_skipped(step_name)
        _safe_metastore(self._metastore.record_step_skipped, self._run_id, step_name)
        with self._tracking_lock:
            self._steps_skipped.append(step_name)

    def _record_first_failure(self, step_name: str, error_msg: str) -> None:
        """Record the first step failure into failure_info (thread-safe)."""
        with self._tracking_lock:
            if not self._failure_info:
                self._failure_info["step"] = step_name
                self._failure_info["error"] = error_msg

    def _run_with_retry(
        self,
        step_name: str,
        step_cfg: StepConfig,
        step_instance: Any,
        step_context: StepContext,
    ) -> tuple[dict, float, int]:
        """Run step_instance.execute() with retry/backoff.

        Returns (output, duration_seconds, final_attempt) on success.
        Raises the last exception on exhaustion, with ``_duration`` and
        ``_attempt`` attributes attached for the caller to read.
        """

        policy = RetryPolicy.from_config(step_cfg.retry) if step_cfg.retry else DEFAULT_POLICY
        attempt = 0
        started_at = time.monotonic()

        while True:
            attempt += 1
            self._state.mark_step_running(step_name, attempt=attempt)
            _safe_metastore(
                self._metastore.record_step_running, self._run_id, step_name, attempt
            )
            started_at = time.monotonic()

            try:
                output = step_instance.execute(step_context)
                self._validate_output(step_name, output)
                duration = time.monotonic() - started_at
                return output, duration, attempt

            except Exception as exc:
                duration = time.monotonic() - started_at
                logger.warning(
                    "[%s] Attempt %d/%d failed: %s",
                    step_name, attempt, policy.max_attempts, exc,
                )
                if policy.should_retry(attempt, exc):
                    retry_error = _format_error(step_name, exc)
                    self._state.mark_step_failed(
                        step_name=step_name,
                        error=retry_error,
                        duration_seconds=duration,
                        attempt=attempt,
                    )
                    _safe_metastore(
                        self._metastore.record_step_failed,
                        self._run_id, step_name, attempt, duration, retry_error,
                    )
                    policy.wait_before_retry(attempt)
                    logger.info("[%s] Retrying (attempt %d)...", step_name, attempt + 1)
                else:
                    exc._duration = duration  # type: ignore[attr-defined]
                    exc._attempt = attempt  # type: ignore[attr-defined]
                    raise

    def _validate_output(self, step_name: str, output: Any) -> None:
        """Raise TypeError if output is not a JSON-serializable dict."""
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


# ---------------------------------------------------------------------------
# Module-level helpers (used internally; also imported by runner.py)
# ---------------------------------------------------------------------------

def _format_error(step_name: str, exc: Exception) -> str:
    return (
        f"Step '{step_name}' raised {type(exc).__name__}: {exc}\n"
        f"{traceback.format_exc()}"
    )
