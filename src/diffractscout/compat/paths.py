"""Writable user storage independent of source checkouts and site-packages."""
from __future__ import annotations

import os
from pathlib import Path


def user_data_dir() -> Path:
    override = os.environ.get("DIFFRACTSCOUT_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "DiffractScout"
