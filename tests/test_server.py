"""Tests for build_app — verifies decorator Pipeline objects register correctly."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from runlet import Pipeline
from runlet.ui import server as server_module


@pytest.fixture(autouse=True)
def clear_registry():
    """Reset the global registry between tests."""
    server_module.registry.clear()
    yield
    server_module.registry.clear()


def _make_pipe(name: str, tmp_path) -> Pipeline:
    pipe = Pipeline(name, store={"type": "filesystem", "base_dir": str(tmp_path)})

    @pipe.step("fetch")
    def fetch(context):
        return {"rows": 10}

    @pipe.step("process", depends_on=["fetch"])
    def process(context):
        return {"done": True}

    return pipe


# ---------------------------------------------------------------------------
# build_app with decorator pipelines
# ---------------------------------------------------------------------------

def test_build_app_registers_decorator_pipeline(tmp_path):
    pipe = _make_pipe("deco-pipeline", tmp_path)
    app = server_module.build_app(pipelines=[pipe])
    client = TestClient(app)

    resp = client.get("/api/pipelines")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "deco-pipeline"


def test_pipeline_nodes_and_edges(tmp_path):
    pipe = _make_pipe("dag-pipeline", tmp_path)
    app = server_module.build_app(pipelines=[pipe])
    client = TestClient(app)

    resp = client.get("/api/pipelines/dag-pipeline")
    assert resp.status_code == 200
    data = resp.json()

    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"fetch", "process"}

    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    assert edge["source"] == "fetch"
    assert edge["target"] == "process"


def test_pipeline_node_has_condition_false_for_decorator(tmp_path):
    pipe = _make_pipe("cond-pipeline", tmp_path)
    app = server_module.build_app(pipelines=[pipe])
    client = TestClient(app)

    resp = client.get("/api/pipelines/cond-pipeline")
    nodes = resp.json()["nodes"]
    assert all(not n["has_condition"] for n in nodes)


def test_build_app_no_args_returns_empty():
    app = server_module.build_app()
    client = TestClient(app)

    resp = client.get("/api/pipelines")
    assert resp.status_code == 200
    assert resp.json() == []


def test_build_app_multiple_decorator_pipelines(tmp_path):
    pipe_a = _make_pipe("alpha", tmp_path)
    pipe_b = _make_pipe("beta", tmp_path)
    app = server_module.build_app(pipelines=[pipe_a, pipe_b])
    client = TestClient(app)

    resp = client.get("/api/pipelines")
    names = {p["name"] for p in resp.json()}
    assert names == {"alpha", "beta"}


def test_get_unknown_pipeline_returns_404(tmp_path):
    pipe = _make_pipe("known", tmp_path)
    app = server_module.build_app(pipelines=[pipe])
    client = TestClient(app)

    resp = client.get("/api/pipelines/unknown")
    assert resp.status_code == 404


def test_execution_order_in_nodes(tmp_path):
    pipe = _make_pipe("order-pipe", tmp_path)
    app = server_module.build_app(pipelines=[pipe])
    client = TestClient(app)

    resp = client.get("/api/pipelines/order-pipe")
    nodes = {n["id"]: n["execution_order"] for n in resp.json()["nodes"]}
    assert nodes["fetch"] < nodes["process"]
