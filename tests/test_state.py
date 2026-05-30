"""Tests for RunState transitions and persistence."""
import pytest

from runlet.artifact_store import FilesystemStore
from runlet.artifacts.ref import ArtifactRef
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

    ref = ArtifactRef.from_uri("p", "Schema", 1)
    state.mark_step_success("step_a", paths={"output": ref}, duration_seconds=1.0)
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
    ref = ArtifactRef.from_uri("x/y", "Schema", 1)
    state.mark_step_success("extract", paths={"out": ref}, duration_seconds=2.5)
    state.mark_run_success()

    reloaded = RunState.load_existing("run42", "pipe", store, "")
    assert reloaded.step_status("extract") == StepStatus.SUCCESS
    assert reloaded.is_step_complete("extract")
    assert reloaded.step_paths("extract") == {"out": ref}
    assert reloaded.run_status == RunStatus.SUCCESS
