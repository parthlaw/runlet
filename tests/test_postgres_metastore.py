"""
Integration tests for PostgresMetastore against a real database.

Requires:
    - psycopg installed:  pip install runlet[postgres]
    - TEST_METASTORE_DSN env var set to a valid PostgreSQL or CockroachDB DSN

Run with:
    TEST_METASTORE_DSN=postgresql://user:pw@localhost:5432/testdb pytest tests/test_postgres_metastore.py
"""

import os

import pytest

psycopg = pytest.importorskip("psycopg")

_DSN = os.environ.get("TEST_METASTORE_DSN")
if not _DSN:
    pytest.skip("TEST_METASTORE_DSN not set", allow_module_level=True)

from runlet.metastore.stores.postgres import PostgresConfig, PostgresMetastore


@pytest.fixture
def metastore():
    cfg = PostgresConfig(dsn=_DSN)
    ms = PostgresMetastore(cfg)
    ms.init_schema()
    yield ms
    # Cleanup: remove all test rows so tests are repeatable
    with ms._conn.cursor() as cur:
        cur.execute("DELETE FROM pipeline_runs WHERE run_id LIKE 'test-%'")
    ms._conn.commit()
    ms.close()


def test_run_lifecycle(metastore):
    metastore.record_run_started("test-run1", "my-pipe")
    rec = metastore.get_run("test-run1")
    assert rec is not None
    assert rec.status == "running"
    assert rec.pipeline_name == "my-pipe"

    metastore.record_run_success("test-run1")
    rec = metastore.get_run("test-run1")
    assert rec.status == "success"
    assert rec.error is None


def test_run_failed(metastore):
    metastore.record_run_started("test-run2", "pipe")
    metastore.record_run_failed("test-run2", "something broke")
    rec = metastore.get_run("test-run2")
    assert rec.status == "failed"
    assert rec.error == "something broke"


def test_run_cancelled(metastore):
    metastore.record_run_started("test-run3", "pipe")
    metastore.record_run_cancelled("test-run3")
    rec = metastore.get_run("test-run3")
    assert rec.status == "cancelled"


def test_step_success_lifecycle(metastore):
    metastore.record_run_started("test-run4", "pipe")
    metastore.record_step_running("test-run4", "extract", 1)
    metastore.record_step_success(
        "test-run4", "extract", 1, 2.5,
        {"output": {"uri": "blob://abc"}},
        {"output": {"name": "Record", "version": 1, "record_count": 42}},
    )

    steps = metastore.list_steps("test-run4")
    assert len(steps) == 1
    s = steps[0]
    assert s.status == "success"
    assert s.attempt == 1
    assert s.duration_seconds == pytest.approx(2.5)
    assert s.paths == {"output": {"uri": "blob://abc"}}
    assert s.schema_info["output"]["record_count"] == 42


def test_step_retry_creates_separate_rows(metastore):
    metastore.record_run_started("test-run5", "pipe")
    metastore.record_step_running("test-run5", "load", 1)
    metastore.record_step_failed("test-run5", "load", 1, 0.1, "timeout")
    metastore.record_step_running("test-run5", "load", 2)
    metastore.record_step_success("test-run5", "load", 2, 1.2, {}, {})

    steps = metastore.list_steps("test-run5")
    assert len(steps) == 2
    assert steps[0].attempt == 1
    assert steps[0].status == "failed"
    assert steps[0].error == "timeout"
    assert steps[1].attempt == 2
    assert steps[1].status == "success"


def test_step_skipped(metastore):
    metastore.record_run_started("test-run6", "pipe")
    metastore.record_step_skipped("test-run6", "transform")

    steps = metastore.list_steps("test-run6")
    assert len(steps) == 1
    assert steps[0].status == "skipped"
    assert steps[0].attempt == 0


def test_step_failed_before_running(metastore):
    # Step can fail without a prior record_step_running call (e.g. load error).
    metastore.record_run_started("test-run7", "pipe")
    metastore.record_step_failed("test-run7", "broken-step", 1, 0.0, "ImportError")

    steps = metastore.list_steps("test-run7")
    assert len(steps) == 1
    assert steps[0].status == "failed"
    assert steps[0].error == "ImportError"


def test_list_runs_filter_by_status(metastore):
    metastore.record_run_started("test-run8", "pipe")
    metastore.record_run_success("test-run8")
    metastore.record_run_started("test-run9", "pipe")
    metastore.record_run_failed("test-run9", "oops")

    success_runs = metastore.list_runs(status="success")
    assert any(r.run_id == "test-run8" for r in success_runs)

    failed_runs = metastore.list_runs(status="failed")
    assert any(r.run_id == "test-run9" for r in failed_runs)


def test_list_runs_filter_by_pipeline_name(metastore):
    metastore.record_run_started("test-run10", "pipeline-alpha")
    metastore.record_run_started("test-run11", "pipeline-beta")

    alpha = metastore.list_runs(pipeline_name="pipeline-alpha")
    assert all(r.pipeline_name == "pipeline-alpha" for r in alpha)
    assert any(r.run_id == "test-run10" for r in alpha)
    assert not any(r.run_id == "test-run11" for r in alpha)


def test_resume_upserts_run_back_to_running(metastore):
    metastore.record_run_started("test-run12", "pipe")
    metastore.record_run_failed("test-run12", "crash")
    # Simulate resume
    metastore.record_run_started("test-run12", "pipe")
    rec = metastore.get_run("test-run12")
    assert rec.status == "running"


def test_get_run_not_found_returns_none(metastore):
    assert metastore.get_run("does-not-exist") is None


def test_list_steps_empty_for_unknown_run(metastore):
    assert metastore.list_steps("no-such-run") == []
