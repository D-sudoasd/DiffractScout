"""Stable Unicode output for Windows consoles and redirected CLI streams."""
from __future__ import annotations

import sys


def configure_cli_output() -> None:
    """Use UTF-8 for CLI text without changing input or exported file encodings."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
