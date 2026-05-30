"""
context — backward-compatible re-exports.

RuntimeContext and WriterContext now live in their own modules.
PipelineContext is kept as an alias for WriterContext so existing code continues
to work without changes.
"""

from runlet.orchestrator.runtime_context import RuntimeContext
from runlet.orchestrator.writer_context import WriterContext, build_context

# Backward-compatible alias — prefer WriterContext or RuntimeContext in new code.
PipelineContext = WriterContext

__all__ = [
    "PipelineContext",
    "RuntimeContext",
    "WriterContext",
    "build_context",
]
