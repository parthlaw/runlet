"""Tests for RunState transitions and persistence."""
import threading

import pytest

from runlet.artifact_store import FilesystemStore
from runlet.orchestrator.state import RunState, RunStatus, StepStatus


@pytest.fixture
def store(tmp_path):
    return FilesystemStore(str(tmp_path))


def test_step_status_transitions(store):
    state = RunState.create_new("run1", "test-pipeline", store, "")
    assert state.step_status("step_a") == StepStatus.PENDING
    assert not state.is_step_complete("step_a")

    state.mark_step_running("step_a")
    assert state.step_status("step_a") == StepStatus.RUNNING

    state.mark_step_success("step_a", output={"count": 42}, duration_seconds=1.0)
    assert state.step_status("step_a") == StepStatus.SUCCESS
    assert state.is_step_complete("step_a")


def test_step_failed(store):
    state = RunState.create_new("run1", "p", store, "")
    state.mark_step_running("step_a")
    state.mark_step_failed("step_a", error="boom", duration_seconds=0.1)
    assert state.step_status("step_a") == StepStatus.FAILED
    assert not state.is_step_complete("step_a")


def test_step_skipped(store):
    state = RunState.create_new("run1", "p", store, "")
    state.mark_step_skipped("step_a")
    assert state.is_step_complete("step_a")


def test_round_trip_load_existing(store):
    state = RunState.create_new("run42", "pipe", store, "")
    state.mark_step_running("extract")
    state.mark_step_success("extract", output={"uri": "x/y", "count": 10}, duration_seconds=2.5)
    state.mark_run_success()

    reloaded = RunState.load_existing("run42", "pipe", store, "")
    assert reloaded.step_status("extract") == StepStatus.SUCCESS
    assert reloaded.is_step_complete("extract")
    assert reloaded.step_output("extract") == {"uri": "x/y", "count": 10}
    assert reloaded.run_status == RunStatus.SUCCESS


def test_concurrent_mark_step_success_all_persisted(store):
    """10 threads completing unique steps simultaneously must all appear in reloaded state."""
    state = RunState.create_new("run-concurrent", "pipe", store, "")
    step_names = [f"step_{i}" for i in range(10)]
    errors: list[Exception] = []

    def complete_step(name: str) -> None:
        try:
            state.mark_step_success(name, output={"done": True}, duration_seconds=0.1)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=complete_step, args=(n,)) for n in step_names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors

    reloaded = RunState.load_existing("run-concurrent", "pipe", store, "")
    for name in step_names:
        assert reloaded.step_status(name) == StepStatus.SUCCESS, f"{name} missing from reloaded state"
        assert reloaded.step_output(name) == {"done": True}
