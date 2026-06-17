"""Tests for RunState transitions and restore logic."""
import datetime
import threading

from runlet.metastore.metastore import StepRecord
from runlet.orchestrator.state.state import RunState, StepStatus


def _step_record(step_name, status, attempt, output=None, error=None):
    return StepRecord(
        run_id="run1",
        step_name=step_name,
        status=status,
        attempt=attempt,
        duration_seconds=0.1,
        error=error,
        output=output or {},
        recorded_at=datetime.datetime.now(tz=datetime.UTC),
    )


def test_step_status_transitions():
    state = RunState(run_id="run1", pipeline_name="test-pipeline")
    assert state.step_status("step_a") == StepStatus.PENDING
    assert not state.is_step_complete("step_a")

    state.mark_step_running("step_a")
    assert state.step_status("step_a") == StepStatus.RUNNING

    state.mark_step_success("step_a", duration_seconds=1.0)
    assert state.step_status("step_a") == StepStatus.SUCCESS
    assert state.is_step_complete("step_a")


def test_step_failed():
    state = RunState(run_id="run1", pipeline_name="p")
    state.mark_step_running("step_a")
    state.mark_step_failed("step_a", error="boom", duration_seconds=0.1)
    assert state.step_status("step_a") == StepStatus.FAILED
    assert not state.is_step_complete("step_a")


def test_step_skipped():
    state = RunState(run_id="run1", pipeline_name="p")
    state.mark_step_skipped("step_a")
    assert state.is_step_complete("step_a")


def test_restore_from_records_simple_success():
    records = [
        _step_record("extract", "success", 1, output={"uri": "x/y", "count": 10}),
    ]
    state = RunState.restore_from_records("run42", "pipe", records)
    assert state.step_status("extract") == StepStatus.SUCCESS
    assert state.is_step_complete("extract")


def test_restore_from_records_skipped():
    records = [
        _step_record("optional_step", "skipped", 0),
    ]
    state = RunState.restore_from_records("run42", "pipe", records)
    assert state.step_status("optional_step") == StepStatus.SKIPPED
    assert state.is_step_complete("optional_step")


def test_restore_from_records_retry_then_success():
    """attempt=1 FAILED, attempt=2 SUCCESS → step complete."""
    records = [
        _step_record("etl", "failed", 1, error="timeout"),
        _step_record("etl", "success", 2, output={"rows": 500}),
    ]
    state = RunState.restore_from_records("run42", "pipe", records)
    assert state.step_status("etl") == StepStatus.SUCCESS
    assert state.is_step_complete("etl")


def test_restore_from_records_failed_not_complete():
    """A step that only has FAILED records is left PENDING so it re-runs on resume."""
    records = [
        _step_record("etl", "failed", 1, error="crash"),
    ]
    state = RunState.restore_from_records("run42", "pipe", records)
    assert state.step_status("etl") == StepStatus.PENDING
    assert not state.is_step_complete("etl")


def test_restore_from_records_mixed_steps():
    """Mix of complete and incomplete steps."""
    records = [
        _step_record("ingest", "success", 1, output={"count": 7}),
        _step_record("transform", "failed", 1, error="oom"),
        _step_record("export", "skipped", 0),
    ]
    state = RunState.restore_from_records("run99", "pipe", records)
    assert state.is_step_complete("ingest")
    assert not state.is_step_complete("transform")
    assert state.is_step_complete("export")


def test_concurrent_mark_step_success_thread_safety():
    """10 threads completing unique steps simultaneously — no races or errors."""
    state = RunState(run_id="run-concurrent", pipeline_name="pipe")
    step_names = [f"step_{i}" for i in range(10)]
    errors: list[Exception] = []

    def complete_step(name: str) -> None:
        try:
            state.mark_step_success(name, duration_seconds=0.1)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=complete_step, args=(n,)) for n in step_names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    for name in step_names:
        assert state.step_status(name) == StepStatus.SUCCESS
