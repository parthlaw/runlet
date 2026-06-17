"""Tests for DAG parsing and topology."""
import pytest

from runlet.orchestrator.config import ALLOWED_CONDITION_OPS, PipelineConfig
from runlet.orchestrator.graph.dag import DAG
from runlet.orchestrator.errors import ConfigValidationError, CyclicDependencyError

BASE_STORE = {"type": "filesystem", "base_dir": "/tmp/test", "prefix": ""}

def _make_config(steps, pipeline_name="test"):
    return {
        "pipeline": {"name": pipeline_name},
        "store": BASE_STORE,
        "steps": steps,
    }


def test_topological_order_linear():
    raw = _make_config([
        {"name": "a", "module": "m", "class": "C", "depends_on": []},
        {"name": "b", "module": "m", "class": "C", "depends_on": ["a"]},
        {"name": "c", "module": "m", "class": "C", "depends_on": ["b"]},
    ])
    dag = DAG(PipelineConfig.from_dict(raw))
    assert dag.topological_order == ["a", "b", "c"]


def test_topological_order_alphabetical_tiebreak():
    raw = _make_config([
        {"name": "b", "module": "m", "class": "C", "depends_on": []},
        {"name": "a", "module": "m", "class": "C", "depends_on": []},
        {"name": "c", "module": "m", "class": "C", "depends_on": ["a", "b"]},
    ])
    dag = DAG(PipelineConfig.from_dict(raw))
    order = dag.topological_order
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("c")
    assert order[0] == "a"  # alphabetical wins when both have in_degree=0


def test_cycle_detection():
    raw = _make_config([
        {"name": "a", "module": "m", "class": "C", "depends_on": ["b"]},
        {"name": "b", "module": "m", "class": "C", "depends_on": ["a"]},
    ])
    with pytest.raises(CyclicDependencyError):
        DAG(PipelineConfig.from_dict(raw))


def test_unknown_dependency_raises():
    raw = _make_config([
        {"name": "a", "module": "m", "class": "C", "depends_on": ["nonexistent"]},
    ])
    with pytest.raises(ConfigValidationError, match="unknown step"):
        DAG(PipelineConfig.from_dict(raw))


def test_condition_valid_operators_parse():
    for op in ALLOWED_CONDITION_OPS:
        raw = _make_config([
            {"name": "a", "module": "m", "class": "C", "depends_on": []},
            {
                "name": "b", "module": "m", "class": "C",
                "depends_on": ["a"],
                "condition": {"step": "a", "field": "status", "op": op, "value": "ok"},
            },
        ])
        dag = DAG(PipelineConfig.from_dict(raw))
        assert "b" in dag.topological_order


def test_condition_invalid_operator_raises():
    raw = _make_config([
        {"name": "a", "module": "m", "class": "C", "depends_on": []},
        {
            "name": "b", "module": "m", "class": "C",
            "depends_on": ["a"],
            "condition": {"step": "a", "field": "x", "op": "INVALID", "value": 1},
        },
    ])
    with pytest.raises(ConfigValidationError, match="op must be one of"):
        PipelineConfig.from_dict(raw)
