"""Condition evaluation for step-skipping logic."""

from __future__ import annotations

import operator
from typing import Any

from runlet.orchestrator.config.models import ConditionConfig
from runlet.orchestrator.errors import ConditionEvaluationError

_CONDITION_OPS: dict[str, Any] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}


def evaluate_condition(context: Any, condition: ConditionConfig) -> bool:
    """
    Evaluate a step condition against the first record of an upstream step's output.

    Returns True if the condition holds (step should run).
    Raises ConditionEvaluationError if the record can't be read or compared.
    """
    try:
        record = context.read_first_record(condition.step)
    except (KeyError, ValueError) as exc:
        raise ConditionEvaluationError(
            f"Cannot read output from step '{condition.step}': {exc}"
        ) from exc
    actual = _resolve_field_path(record, condition.field)
    compare_fn = _CONDITION_OPS[condition.op]
    try:
        return bool(compare_fn(actual, condition.value))
    except TypeError as exc:
        raise ConditionEvaluationError(
            f"Cannot compare {actual!r} {condition.op} {condition.value!r}: {exc}"
        ) from exc


def _resolve_field_path(record: dict[str, Any], field_path: str) -> Any:
    current: Any = record
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ConditionEvaluationError(
                f"Field '{field_path}' not found in record (missing '{part}')."
            )
        current = current[part]
    return current
