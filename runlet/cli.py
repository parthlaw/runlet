"""
runlet CLI entry point.

Usage:
    runlet serve --config a.json --config b.json [--host 0.0.0.0] [--port 8000]
"""

from __future__ import annotations

import argparse
import sys


def _serve(args: argparse.Namespace) -> None:
    try:
        import uvicorn
    except ImportError:
        print(
            "error: 'ui' extras required. Install with: pip install runlet[ui]",
            file=sys.stderr,
        )
        sys.exit(1)

    from runlet.ui.server import build_app

    app = build_app(args.config)
    uvicorn.run(app, host=args.host, port=args.port)


def main() -> None:
    parser = argparse.ArgumentParser(prog="runlet")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start the pipeline runner UI server")
    serve.add_argument(
        "--config",
        metavar="PATH",
        action="append",
        required=True,
        help="Path to a pipeline JSON config (repeatable for multiple pipelines)",
    )
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()
    if args.command == "serve":
        _serve(args)
