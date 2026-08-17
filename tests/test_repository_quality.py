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


def test_portable_entrypoint_help_is_executable() -> None:
    root = Path(__file__).resolve().parents[1]
    recipe = (root / "scripts/package_windows_portable.py").read_text(encoding="utf-8")
    assert "python -m PyInstaller" in recipe
    assert "--paths src" in recipe
    assert "scripts\\\\diffractscout_entry.py" in recipe

    completed = subprocess.run(
        [sys.executable, "scripts/diffractscout_entry.py", "--help"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()
    assert "diffractscout" in completed.stdout.lower()
