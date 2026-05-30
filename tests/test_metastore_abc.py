"""Tests for the RunMetastore ABC contract using NoopMetastore. No optional deps required."""

from runlet.metastore import (
    NoopMetastore,
    RunMetastore,
    build_metastore,
)


def test_build_metastore_none_returns_noop():
    ms = build_metastore(None)
    assert isinstance(ms, NoopMetastore)


def test_build_metastore_empty_dict_returns_noop():
    ms = build_metastore({})
    assert isinstance(ms, NoopMetastore)


def test_build_metastore_explicit_noop():
    ms = build_metastore({"type": "noop"})
    assert isinstance(ms, NoopMetastore)


def test_noop_satisfies_abc():
    ms = NoopMetastore()
    assert isinstance(ms, RunMetastore)


def test_noop_writes_are_silent():
    ms = NoopMetastore()
    ms.record_run_started("r1", "my-pipe")
    ms.record_step_running("r1", "extract", 1)
    ms.record_step_success("r1", "extract", 1, 1.5, {"output": {"uri": "x"}}, {"count": 10})
    ms.record_step_skipped("r1", "load")
    ms.record_run_success("r1")
    ms.close()


def test_noop_writes_failed_paths():
    ms = NoopMetastore()
    ms.record_run_started("r2", "pipe")
    ms.record_step_running("r2", "load", 1)
    ms.record_step_failed("r2", "load", 1, 0.5, "timeout")
    ms.record_run_failed("r2", "step load failed")
    ms.close()


def test_noop_queries_return_empty():
    ms = NoopMetastore()
    assert ms.get_run("missing") is None
    assert ms.list_runs() == []
    assert ms.list_runs(pipeline_name="x", status="failed") == []
    assert ms.list_steps("r1") == []


def test_noop_close_is_idempotent():
    ms = NoopMetastore()
    ms.close()
    ms.close()


def test_build_metastore_unknown_type_raises():
    import pytest

    with pytest.raises(ValueError, match="Unknown metastore type"):
        build_metastore({"type": "oracle"})
