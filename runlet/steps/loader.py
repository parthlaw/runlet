"""Step loader — dynamic import and instantiation of step classes from config."""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class StepImportError(ImportError):
    """Raised when a step class cannot be dynamically imported or instantiated."""


def load_step(step_cfg: Any) -> Any:
    """
    Dynamically import and instantiate a step class from its config.

    Raises
    ------
    StepImportError
        If the module cannot be imported, the class is not found, or
        instantiation or config validation fails.
    """
    try:
        module = importlib.import_module(step_cfg.module)
    except ImportError as exc:
        raise StepImportError(
            f"Cannot import module '{step_cfg.module}' for step '{step_cfg.name}'. "
            f"Ensure it is on sys.path. Original error: {exc}"
        ) from exc

    cls = getattr(module, step_cfg.class_name, None)
    if cls is None:
        raise StepImportError(
            f"Module '{step_cfg.module}' has no class '{step_cfg.class_name}' "
            f"(step '{step_cfg.name}')."
        )

    try:
        instance = cls(name=step_cfg.name, config=step_cfg.config)
        instance.validate_config()
    except Exception as exc:
        raise StepImportError(
            f"Failed to instantiate '{step_cfg.class_name}' for step "
            f"'{step_cfg.name}': {exc}"
        ) from exc

    logger.debug(
        "Loaded step '%s' from %s.%s",
        step_cfg.name,
        step_cfg.module,
        step_cfg.class_name,
    )
    return instance
