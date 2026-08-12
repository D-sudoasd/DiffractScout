from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_repository_documentation_and_metadata_are_internally_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/check_docs.py"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "PASS" in completed.stdout
