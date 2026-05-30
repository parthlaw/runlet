"""Tests for @artifact decorator."""

import pytest

from pydantic import field_validator

from runlet.artifacts import BaseArtifact, artifact
from runlet.artifacts.registry import ArtifactRegistry


# ---------------------------------------------------------------------------
# Helpers — use isolated registries so tests don't pollute each other
# ---------------------------------------------------------------------------

def make_registry() -> ArtifactRegistry:
    return ArtifactRegistry()


# ---------------------------------------------------------------------------
# Basic decorator behaviour
# ---------------------------------------------------------------------------

def test_artifact_sets_schema_attributes():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class MyRecord(BaseArtifact):
        value: int

    assert MyRecord.SCHEMA_NAME == "MyRecord"
    assert MyRecord.SCHEMA_VERSION == 1
    assert issubclass(MyRecord, BaseArtifact)


def test_artifact_model_dump_model_validate_roundtrip():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Item(BaseArtifact):
        name: str
        count: int

    obj = Item(name="hello", count=42)
    record = obj.model_dump()
    restored = Item.model_validate(record)
    assert restored.name == "hello"
    assert restored.count == 42


def test_instance_methods_survive_decorator():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class MyArt(BaseArtifact):
        x: int

        def doubled(self) -> int:
            return self.x * 2

    obj = MyArt(x=5)
    assert obj.doubled() == 10


def test_pydantic_field_validator_works():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Normalised(BaseArtifact):
        text: str

        @field_validator("text")
        @classmethod
        def strip_lower(cls, v: str) -> str:
            return v.strip().lower()

    obj = Normalised(text="  Hello  ")
    assert obj.text == "hello"


def test_non_base_artifact_raises_type_error():
    reg = make_registry()

    with pytest.raises(TypeError, match="BaseArtifact subclass"):
        @artifact(version=1, registry=reg)
        class Plain:
            x: int


def test_custom_schema_name():
    reg = make_registry()

    @artifact(version=2, name="AliasedRecord", registry=reg)
    class InternalName(BaseArtifact):
        v: int

    assert InternalName.SCHEMA_NAME == "AliasedRecord"


def test_isinstance_check():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Rec(BaseArtifact):
        n: int

    assert isinstance(Rec(n=1), BaseArtifact)


def test_model_fields_populated():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Hinted(BaseArtifact):
        x: int
        y: str

    assert "x" in Hinted.model_fields
    assert "y" in Hinted.model_fields


def test_same_class_reregistered_is_idempotent():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Foo(BaseArtifact):
        v: int

    # Registering the same class object again must not raise.
    reg.register(Foo)


def test_artifact_is_frozen():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Immutable(BaseArtifact):
        value: int

    obj = Immutable(value=10)
    with pytest.raises(Exception):
        obj.value = 99  # type: ignore[misc]
