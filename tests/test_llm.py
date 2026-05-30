"""Tests for the LLM proxy layer (LLMConfig, LLMProxy, context.llm)."""

from __future__ import annotations

import os
import json
import importlib
import types
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from runlet.artifacts import BaseArtifact, artifact
from runlet.llm.config import LLMConfig
from runlet.llm.proxy import LLMProxy
from runlet.orchestrator.context import PipelineContext
from runlet.orchestrator.writer_context import build_context
from runlet.artifact_store.stores.filesystem import FilesystemStore
from runlet.orchestrator.config import PipelineConfig
from runlet.orchestrator.dag import DAG
from runlet.orchestrator.models import RunnerConfig
from runlet.orchestrator.runner import SequentialRunner
from runlet import BaseStep


# ---------------------------------------------------------------------------
# LLMConfig parsing
# ---------------------------------------------------------------------------

def test_llm_config_from_dict_valid():
    cfg = LLMConfig.from_dict({
        "model": "gpt-4o-mini",
        "api_key_env": "MY_KEY",
        "base_url": "https://api.example.com",
    })
    assert cfg.model == "gpt-4o-mini"
    assert cfg.api_key_env == "MY_KEY"
    assert cfg.base_url == "https://api.example.com"


def test_llm_config_base_url_optional():
    cfg = LLMConfig.from_dict({"model": "gpt-4o", "api_key_env": "OPENAI_API_KEY"})
    assert cfg.base_url is None


def test_llm_config_missing_model_raises():
    with pytest.raises(ValueError, match="model"):
        LLMConfig.from_dict({"api_key_env": "MY_KEY"})


def test_llm_config_missing_api_key_env_raises():
    with pytest.raises(ValueError, match="api_key_env"):
        LLMConfig.from_dict({"model": "gpt-4o"})


# ---------------------------------------------------------------------------
# LLMProxy construction
# ---------------------------------------------------------------------------

def test_llm_proxy_from_config_missing_env_raises(monkeypatch):
    monkeypatch.delenv("MY_LLM_KEY", raising=False)
    cfg = LLMConfig(model="gpt-4o-mini", api_key_env="MY_LLM_KEY")
    with pytest.raises(RuntimeError, match="MY_LLM_KEY"):
        LLMProxy.from_config(cfg)


def test_llm_proxy_from_config_builds_proxy(monkeypatch):
    monkeypatch.setenv("MY_LLM_KEY", "sk-test-key")
    cfg = LLMConfig(model="gpt-4o-mini", api_key_env="MY_LLM_KEY")

    mock_client = MagicMock()
    with patch.object(LLMProxy, "_build_client", return_value=mock_client):
        proxy = LLMProxy.from_config(cfg)

    assert proxy._model == "gpt-4o-mini"
    assert proxy._client is mock_client


def test_llm_proxy_complete_calls_instructor(monkeypatch):
    class Sentiment(BaseModel):
        label: str

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = Sentiment(label="positive")

    with patch.object(LLMProxy, "_build_client", return_value=mock_client):
        proxy = LLMProxy(model="gpt-4o-mini", api_key="sk-dummy")

    result = proxy.complete(
        messages=[{"role": "user", "content": "hello"}],
        response_model=Sentiment,
    )

    assert result.label == "positive"
    mock_client.chat.completions.create.assert_called_once_with(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hello"}],
        response_model=Sentiment,
    )


def test_llm_proxy_complete_model_override(monkeypatch):
    class Out(BaseModel):
        value: int

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = Out(value=42)

    with patch.object(LLMProxy, "_build_client", return_value=mock_client):
        proxy = LLMProxy(model="gpt-4o-mini", api_key="sk-dummy")

    proxy.complete(
        messages=[{"role": "user", "content": "hi"}],
        response_model=Out,
        model="gpt-4o",
    )

    call_kwargs = mock_client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# context.llm property
# ---------------------------------------------------------------------------

def test_context_llm_raises_when_not_configured(tmp_path):
    store = FilesystemStore(str(tmp_path))
    ctx = build_context(
        run_id="r",
        pipeline_name="p",
        store=store,
        upload_store=store,
    )
    with pytest.raises(RuntimeError, match="No LLM"):
        _ = ctx.llm


def test_context_llm_returns_proxy_when_configured(tmp_path):
    store = FilesystemStore(str(tmp_path))
    mock_proxy = MagicMock()
    ctx = build_context(
        run_id="r",
        pipeline_name="p",
        store=store,
        upload_store=store,
        llm=mock_proxy,
    )
    assert ctx.llm is mock_proxy


# ---------------------------------------------------------------------------
# build_runner integration
# ---------------------------------------------------------------------------

def _pipeline_json(store_dir: str, extra: dict | None = None) -> dict:
    raw: dict = {
        "pipeline": {"name": "llm-test"},
        "store": {"type": "filesystem", "base_dir": store_dir, "prefix": ""},
        "steps": [
            {"name": "dummy", "module": "test_steps", "class": "DummyStep", "depends_on": []},
        ],
    }
    if extra:
        raw.update(extra)
    return raw


def _fake_import(monkeypatch, **classes: type) -> None:
    original = importlib.import_module

    def fake(name: str, *args, **kwargs):
        if name == "test_steps":
            m = types.ModuleType("test_steps")
            for k, v in classes.items():
                setattr(m, k, v)
            return m
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake)


def test_build_runner_without_llm_block_context_llm_raises(tmp_path, monkeypatch):
    """A pipeline without an 'llm' block should have context.llm raise RuntimeError."""
    llm_accessed: list[bool] = []

    @artifact(version=1)
    class Rec(BaseArtifact):
        v: int

    class DummyStep(BaseStep):
        def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
            try:
                _ = context.llm
            except RuntimeError:
                llm_accessed.append(False)
            yield Rec(v=1)

    _fake_import(monkeypatch, DummyStep=DummyStep)

    cfg = PipelineConfig.from_dict(_pipeline_json(str(tmp_path)))
    dag = DAG(cfg)
    runner = SequentialRunner(dag, RunnerConfig())
    result = runner.run("no-llm-run")

    assert result.success
    assert llm_accessed == [False]


def test_build_runner_with_llm_block_missing_env_raises(tmp_path, monkeypatch):
    """A pipeline with 'llm' block but missing env var must raise at build time."""
    import tempfile, json as _json
    from pathlib import Path
    from runlet.orchestrator.runner import build_runner

    monkeypatch.delenv("TEST_LLM_KEY_MISSING", raising=False)

    raw = _pipeline_json(str(tmp_path), extra={
        "llm": {"model": "gpt-4o-mini", "api_key_env": "TEST_LLM_KEY_MISSING"}
    })
    config_file = tmp_path / "pipeline.json"
    config_file.write_text(_json.dumps(raw))

    with pytest.raises(RuntimeError, match="TEST_LLM_KEY_MISSING"):
        build_runner(config_file)


def test_build_runner_with_llm_block_wires_proxy(tmp_path, monkeypatch):
    """With the env var set and _build_client patched, context.llm returns the proxy."""
    import tempfile, json as _json
    from runlet.orchestrator.runner import build_runner

    monkeypatch.setenv("TEST_LLM_KEY", "sk-dummy")

    llm_proxy_seen: list[object] = []

    @artifact(version=1)
    class Rec2(BaseArtifact):
        v: int

    class LLMStep(BaseStep):
        def execute(self, context: PipelineContext) -> Iterator[BaseArtifact]:
            llm_proxy_seen.append(context.llm)
            yield Rec2(v=1)

    _fake_import(monkeypatch, DummyStep=LLMStep)

    raw = _pipeline_json(str(tmp_path), extra={
        "llm": {"model": "gpt-4o-mini", "api_key_env": "TEST_LLM_KEY"}
    })
    config_file = tmp_path / "pipeline.json"
    config_file.write_text(_json.dumps(raw))

    mock_client = MagicMock()
    with patch.object(LLMProxy, "_build_client", return_value=mock_client):
        runner = build_runner(config_file)
        result = runner.run("llm-wired-run")

    assert result.success
    assert len(llm_proxy_seen) == 1
    assert isinstance(llm_proxy_seen[0], LLMProxy)
