"""Tests for the RunMetastore ABC contract using NoopMetastore. No optional deps required."""

import pytest

from runlet.metastore import (
    NoopMetastore,
    RunMetastore,
    build_metastore,
    build_metastore_config,
)


def test_build_metastore_none_returns_noop():
    ms = build_metastore(None)
    assert isinstance(ms, NoopMetastore)


def test_build_metastore_empty_dict_returns_noop():
    ms = build_metastore(build_metastore_config({}))
    assert isinstance(ms, NoopMetastore)


def test_build_metastore_explicit_noop():
    ms = build_metastore(build_metastore_config({"type": "noop"}))
    assert isinstance(ms, NoopMetastore)


def test_noop_satisfies_abc():
    ms = NoopMetastore()
    assert isinstance(ms, RunMetastore)


def test_noop_writes_are_silent():
    ms = NoopMetastore()
    ms.record_run_started("r1", "my-pipe")
    ms.record_step_running("r1", "extract", 1)
    ms.record_step_success("r1", "extract", 1, 1.5, {"data_uri": "x", "count": 10})
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


def test_noop_record_run_success_accepts_outputs():
    ms = NoopMetastore()
    ms.record_run_started("r3", "pipe")
    # must not raise — outputs kwarg is part of the contract
    ms.record_run_success("r3", outputs={"score": 0.9, "download_url": "s3://bucket/key"})
    ms.close()

    with pytest.raises(ValueError, match="is not a valid MetastoreType"):
        build_metastore_config({"type": "oracle"})


def test_record_run_success_stores_outputs_in_sqlite(tmp_path):
    """record_run_success() must persist the outputs dict so get_run().outputs is populated."""
    from runlet.metastore.stores.sqlite import SqliteConfig, SqliteMetastore

    cfg = SqliteConfig(db_path=str(tmp_path / "meta.db"))
    ms = SqliteMetastore(cfg)
    ms.init_schema()

    outputs = {"step_a": {"count": 42}, "step_b": {"uri": "s3://bucket/key"}}
    ms.record_run_started("r-outputs", "pipe")
    ms.record_run_success("r-outputs", outputs)

    rec = ms.get_run("r-outputs")
    assert rec is not None
    assert rec.status == "success"
    assert rec.outputs == outputs
    ms.close()
