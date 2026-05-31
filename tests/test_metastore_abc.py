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


def test_noop_record_run_success_accepts_outputs():
    ms = NoopMetastore()
    ms.record_run_started("r3", "pipe")
    # must not raise — outputs kwarg is part of the contract
    ms.record_run_success("r3", outputs={"score": 0.9, "download_url": "s3://bucket/key"})
    ms.close()


def test_noop_record_run_success_no_outputs():
    ms = NoopMetastore()
    ms.record_run_started("r4", "pipe")
    ms.record_run_success("r4")  # backward-compat: outputs defaults to None
    ms.close()


def test_run_record_has_outputs_field():
    import datetime

    from runlet.metastore.metastore import RunRecord

    rec = RunRecord(
        run_id="r5",
        pipeline_name="pipe",
        status="success",
        error=None,
        created_at=datetime.datetime.now(tz=datetime.UTC),
        updated_at=datetime.datetime.now(tz=datetime.UTC),
        outputs={"score": 0.95},
    )
    assert rec.outputs == {"score": 0.95}


def test_run_record_outputs_defaults_to_empty():
    import datetime

    from runlet.metastore.metastore import RunRecord

    rec = RunRecord(
        run_id="r6",
        pipeline_name="pipe",
        status="success",
        error=None,
        created_at=datetime.datetime.now(tz=datetime.UTC),
        updated_at=datetime.datetime.now(tz=datetime.UTC),
    )
    assert rec.outputs == {}
