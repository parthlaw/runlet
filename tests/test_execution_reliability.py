"""Tests for Plan 2: Execution Reliability features."""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator

from runlet import BaseArtifact, BaseStep, artifact
from runlet.orchestrator.config import PipelineConfig
from runlet.orchestrator.context import PipelineContext
from runlet.orchestrator.dag import DAG
from runlet.orchestrator.models import RunnerConfig, RunResult
from runlet.orchestrator.runner import SequentialRunner

# ---------------------------------------------------------------------------
# Shared artifact types
# ---------------------------------------------------------------------------

@artifact(version=1)
class SimpleRecord(BaseArtifact):
    value: int


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _pipeline_cfg(store_dir: str, steps: list) -> dict:
    return {
        "pipeline": {"name": "reliability-test"},
        "store": {"type": "filesystem", "base_dir": store_dir, "prefix": ""},
        "steps": steps,
    }


def _make_runner(store_dir: str, steps: list, max_concurrent: int = 1) -> SequentialRunner:
    raw = _pipeline_cfg(store_dir, steps)
    cfg = PipelineConfig.from_dict(raw)
    dag = DAG(cfg)
    return SequentialRunner(dag, RunnerConfig(max_concurrent_steps=max_concurrent))


def _fake_import(monkeypatch, **classes: type) -> None:
    """Patch importlib.import_module to resolve 'test_steps' → classes dict."""
    import importlib
    import types
    original = importlib.import_module

    def fake(name: str, *args, **kwargs):
        if name == "test_steps":
            m = types.ModuleType("test_steps")
            for k, v in classes.items():
                setattr(m, k, v)
            return m
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake)


def _step_cfg(name: str, cls_name: str, depends_on: list[str] | None = None, **extra) -> dict:
    cfg: dict = {"name": name, "module": "test_steps", "class": cls_name}
    cfg["depends_on"] = depends_on or []
    cfg.update(extra)
    return cfg


# ---------------------------------------------------------------------------
# 2.1 / 2.2 — Retry
# ---------------------------------------------------------------------------

class TestRetry:
    def test_step_retries_and_eventually_succeeds(self, tmp_path, monkeypatch):
        call_counts: list[int] = [0]

        class FlakyStep(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                call_counts[0] += 1
                if call_counts[0] < 3:
                    raise ValueError("transient error")
                yield SimpleRecord(value=call_counts[0])

        _fake_import(monkeypatch, FlakyStep=FlakyStep)

        runner = _make_runner(str(tmp_path), [
            _step_cfg(
                "flaky", "FlakyStep",
                retry={"max_attempts": 3, "backoff_base": 0.0,
                       "backoff_multiplier": 1.0, "jitter": 0.0},
            ),
        ])
        result = runner.run("retry-success")

        assert result.success
        assert result.status == "SUCCESS"
        assert call_counts[0] == 3  # called 3 times total

    def test_retry_exhaustion_returns_failed(self, tmp_path, monkeypatch):
        call_counts: list[int] = [0]

        class AlwaysFailStep(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                call_counts[0] += 1
                raise RuntimeError("always fails")
                yield  # make it a generator

        _fake_import(monkeypatch, AlwaysFailStep=AlwaysFailStep)

        runner = _make_runner(str(tmp_path), [
            _step_cfg(
                "fail", "AlwaysFailStep",
                retry={"max_attempts": 2, "backoff_base": 0.0,
                       "backoff_multiplier": 1.0, "jitter": 0.0},
            ),
        ])
        result = runner.run("retry-exhaustion")

        assert not result.success
        assert result.status == "FAILED"
        assert result.failed_step == "fail"
        assert call_counts[0] == 2  # 2 attempts total


# ---------------------------------------------------------------------------
# 2.3 — Per-step timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_step_exceeds_timeout_raises_timeout_error(self, tmp_path, monkeypatch):
        class SlowStep(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                time.sleep(0.2)  # pool waits for this after TimeoutError
                yield SimpleRecord(value=1)

        _fake_import(monkeypatch, SlowStep=SlowStep)

        runner = _make_runner(str(tmp_path), [
            _step_cfg("slow", "SlowStep", config={"timeout_seconds": 0.05}),
        ])
        result = runner.run("timeout-test")

        assert not result.success
        assert result.status == "FAILED"
        assert result.failed_step == "slow"
        assert result.error is not None
        assert "TimeoutError" in result.error or "timeout" in result.error.lower()


# ---------------------------------------------------------------------------
# 2.4 — validate_config (already wired in loader.py)
# ---------------------------------------------------------------------------

class TestValidateConfig:
    def test_invalid_config_fails_fast(self, tmp_path, monkeypatch):
        class StrictStep(BaseStep):
            def validate_config(self) -> None:
                if "required_key" not in self.config:
                    raise ValueError("required_key is missing from config")

            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                yield SimpleRecord(value=1)

        _fake_import(monkeypatch, StrictStep=StrictStep)

        runner = _make_runner(str(tmp_path), [
            _step_cfg("strict", "StrictStep"),  # no "required_key" in config
        ])
        result = runner.run("validate-config-test")

        assert not result.success
        assert result.status == "FAILED"
        assert result.failed_step == "strict"
        assert result.error is not None
        assert "required_key" in result.error


# ---------------------------------------------------------------------------
# 2.4 — teardown
# ---------------------------------------------------------------------------

class TestTeardown:
    def test_teardown_called_on_success(self, tmp_path, monkeypatch):
        teardown_calls: list[bool] = []

        class TeardownStep(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                yield SimpleRecord(value=1)

            def teardown(self, context: PipelineContext, success: bool) -> None:
                teardown_calls.append(success)

        _fake_import(monkeypatch, TeardownStep=TeardownStep)

        runner = _make_runner(str(tmp_path), [_step_cfg("td", "TeardownStep")])
        result = runner.run("teardown-success")

        assert result.success
        assert teardown_calls == [True]

    def test_teardown_called_on_failure(self, tmp_path, monkeypatch):
        teardown_calls: list[bool] = []

        class FailingTdStep(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                raise RuntimeError("step fails")
                yield

            def teardown(self, context: PipelineContext, success: bool) -> None:
                teardown_calls.append(success)

        _fake_import(monkeypatch, FailingTdStep=FailingTdStep)

        runner = _make_runner(str(tmp_path), [_step_cfg("fail_td", "FailingTdStep")])
        result = runner.run("teardown-failure")

        assert not result.success
        assert teardown_calls == [False]

    def test_teardown_exception_is_swallowed(self, tmp_path, monkeypatch):
        """A teardown exception must not mask the original step result."""

        class TdRaisesStep(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                yield SimpleRecord(value=1)

            def teardown(self, context: PipelineContext, success: bool) -> None:
                raise RuntimeError("teardown exploded")

        _fake_import(monkeypatch, TdRaisesStep=TdRaisesStep)

        runner = _make_runner(str(tmp_path), [_step_cfg("td_raises", "TdRaisesStep")])
        result = runner.run("teardown-swallow")

        # Step itself succeeded; teardown exception must not surface
        assert result.success
        assert result.status == "SUCCESS"


# ---------------------------------------------------------------------------
# 2.5 — Cooperative cancellation
# ---------------------------------------------------------------------------

class TestCancellation:
    def test_cancel_before_run_returns_cancelled(self, tmp_path, monkeypatch):
        class NormalStep(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                yield SimpleRecord(value=1)

        _fake_import(monkeypatch, NormalStep=NormalStep)

        runner = _make_runner(str(tmp_path), [_step_cfg("s", "NormalStep")])
        runner.cancel()
        result = runner.run("pre-cancel")

        assert result.status == "CANCELLED"
        assert not result.success
        assert result.steps_executed == []

    def test_cancel_after_first_step_stops_second(self, tmp_path, monkeypatch):
        step2_executed: list[bool] = [False]

        class Step1(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                yield SimpleRecord(value=1)
                # Sleep inside generator so the cancel can arrive before step2 is dispatched
                time.sleep(0.1)

        class Step2(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                step2_executed[0] = True
                yield SimpleRecord(value=1)

        _fake_import(monkeypatch, Step1=Step1, Step2=Step2)

        runner = _make_runner(str(tmp_path), [
            _step_cfg("step1", "Step1"),
            _step_cfg("step2", "Step2", depends_on=["step1"]),
        ])

        result_holder: list[RunResult | None] = [None]

        def run_pipeline() -> None:
            result_holder[0] = runner.run("mid-cancel")

        t = threading.Thread(target=run_pipeline, daemon=True)
        t.start()
        time.sleep(0.02)  # Let step1 start executing before we cancel
        runner.cancel()
        t.join(timeout=10.0)

        result = result_holder[0]
        assert result is not None
        assert result.status == "CANCELLED"
        assert not step2_executed[0]


# ---------------------------------------------------------------------------
# 2.6 — Bounded parallel execution (ThreadedExecutor)
# ---------------------------------------------------------------------------

class TestParallelExecution:
    def test_fan_out_runs_branches_concurrently(self, tmp_path, monkeypatch):
        """A → B, A → C with max_workers=2 should run B and C in parallel."""
        start_times: dict[str, float] = {}
        end_times: dict[str, float] = {}

        class ProducerStep(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                yield SimpleRecord(value=1)

        class BranchStep(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                start_times[self.name] = time.monotonic()
                time.sleep(0.1)  # simulate work
                end_times[self.name] = time.monotonic()
                yield SimpleRecord(value=1)

        _fake_import(monkeypatch, ProducerStep=ProducerStep, BranchStep=BranchStep)

        runner = _make_runner(
            str(tmp_path),
            [
                _step_cfg("a", "ProducerStep"),
                _step_cfg("b", "BranchStep", depends_on=["a"]),
                _step_cfg("c", "BranchStep", depends_on=["a"]),
            ],
            max_concurrent=2,
        )
        result = runner.run("parallel-fan-out")

        assert result.success, result.error
        assert set(result.steps_executed) == {"a", "b", "c"}

        # B and C overlap: one must start before the other ends
        b_start, b_end = start_times["b"], end_times["b"]
        c_start, c_end = start_times["c"], end_times["c"]
        overlap = min(b_end, c_end) - max(b_start, c_start)
        assert overlap > 0, (
            f"B and C did not overlap (b: {b_start:.3f}-{b_end:.3f}, "
            f"c: {c_start:.3f}-{c_end:.3f})"
        )

    def test_sequential_order_preserved_with_one_worker(self, tmp_path, monkeypatch):
        """With max_workers=1, execution must remain sequential."""
        order: list[str] = []

        class OrderedStep(BaseStep):
            def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
                order.append(self.name)
                yield SimpleRecord(value=1)

        _fake_import(monkeypatch, OrderedStep=OrderedStep)

        runner = _make_runner(str(tmp_path), [
            _step_cfg("s1", "OrderedStep"),
            _step_cfg("s2", "OrderedStep", depends_on=["s1"]),
            _step_cfg("s3", "OrderedStep", depends_on=["s2"]),
        ])
        result = runner.run("sequential-order")

        assert result.success
        assert order == ["s1", "s2", "s3"]
