"""
runlet CLI entry point.

Usage:
    runlet serve --config a.json --config b.json [--host 0.0.0.0] [--port 8000]
    runlet serve --pipeline myapp.pipeline:pipe [--host 0.0.0.0] [--port 8000]
    runlet serve --config a.json --pipeline myapp.pipeline:pipe
"""

from __future__ import annotations

import argparse
import importlib
import sys


def _resolve_pipeline(spec: str) -> object:
    """Import and return a Pipeline object from a 'module:attribute' spec.

    Exits with an error message if the spec is malformed, the module cannot
    be imported, the attribute is missing, or the object is not a Pipeline.
    """
    if ":" not in spec:
        print(
            f"error: --pipeline value {spec!r} must be in 'module:attribute' format "
            "(e.g. 'myapp.pipeline:pipe').",
            file=sys.stderr,
        )
        sys.exit(1)

    module_path, _, attr = spec.partition(":")

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        print(
            f"error: cannot import module {module_path!r}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    obj = getattr(module, attr, None)
    if obj is None:
        print(
            f"error: module {module_path!r} has no attribute {attr!r}.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Import here to avoid a hard dependency when the ui extra is not installed.
    from runlet.pipeline import Pipeline

    if not isinstance(obj, Pipeline):
        print(
            f"error: {spec!r} is a {type(obj).__name__!r}, not a Pipeline instance.",
            file=sys.stderr,
        )
        sys.exit(1)

    return obj


def _serve(args: argparse.Namespace) -> None:
    try:
        import uvicorn
    except ImportError:
        print(
            "error: 'ui' extras required. Install with: pip install runlet[ui]",
            file=sys.stderr,
        )
        sys.exit(1)

    from runlet.pipeline import Pipeline
    from runlet.ui.server import build_app

    config_paths: list[str] = args.config or []
    pipeline_specs: list[str] = args.pipeline or []

    if not config_paths and not pipeline_specs:
        print(
            "error: at least one --config or --pipeline argument is required.",
            file=sys.stderr,
        )
        sys.exit(1)

    pipelines: list[Pipeline] = [
        _resolve_pipeline(spec) for spec in pipeline_specs  # type: ignore[misc]
    ]

    app = build_app(config_paths=config_paths or None, pipelines=pipelines or None)
    uvicorn.run(app, host=args.host, port=args.port)


def main() -> None:
    parser = argparse.ArgumentParser(prog="runlet")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start the pipeline runner UI server")
    serve.add_argument(
        "--config",
        metavar="PATH",
        action="append",
        help="Path to a pipeline JSON config (repeatable for multiple pipelines)",
    )
    serve.add_argument(
        "--pipeline",
        metavar="MODULE:ATTR",
        action="append",
        help=(
            "Decorator-defined Pipeline object in 'module:attribute' format "
            "(e.g. 'myapp.pipeline:pipe'). Repeatable."
        ),
    )
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()
    if args.command == "serve":
        _serve(args)
