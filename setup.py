"""
Custom build hook: runs `npm ci && npm run build` inside ./frontend/ before
setuptools collects package data, so the UI static assets are always built
from source rather than committed to the repository.
"""

import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class BuildPyWithUI(_build_py):
    def run(self) -> None:
        frontend_dir = Path(__file__).parent / "frontend"

        if not frontend_dir.exists():
            print(
                "WARNING: frontend/ directory not found — skipping UI build.",
                file=sys.stderr,
            )
        else:
            print("-- Building frontend (npm ci && npm run build) --")
            subprocess.run(["npm", "ci"], cwd=frontend_dir, check=True)
            subprocess.run(["npm", "run", "build"], cwd=frontend_dir, check=True)

        super().run()


setup(cmdclass={"build_py": BuildPyWithUI})
