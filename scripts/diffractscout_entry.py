"""Standalone PyInstaller entry point for the DiffractScout CLI."""

from __future__ import annotations

from pathlib import Path
import sys


_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from diffractscout.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
