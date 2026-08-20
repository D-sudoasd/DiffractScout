from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from packaging.requirements import Requirement
import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


def _load_check_docs():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts/check_docs.py"
    spec = importlib.util.spec_from_file_location("diffractscout_check_docs", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_joss_evidence_schema_declares_current_ledger_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "docs/evidence/impact_evidence.schema.json").read_text(encoding="utf-8")
    )
    payload = json.loads(
        (root / "docs/evidence/impact_evidence.json").read_text(encoding="utf-8")
    )
    required = set(schema["required"])
    assert required <= set(payload)
    assert schema["properties"]["schema"]["const"] == payload["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(payload)
    assert set(schema["$defs"]) >= {
        "evidenceRecord",
        "publicDevelopmentRecord",
        "researchUseRecord",
        "validationRecord",
        "externalEngagementRecord",
        "archivedRelease",
    }


def test_documentation_scan_ignores_project_local_tool_environments(tmp_path: Path) -> None:
    module = _load_check_docs()
    fake_root = tmp_path / "repo"
    (fake_root / "docs").mkdir(parents=True)
    (fake_root / "docs" / "valid.yaml").write_text("name: project\n", encoding="utf-8")
    (fake_root / ".venv-joss" / "Lib").mkdir(parents=True)
    (fake_root / ".venv-joss" / "Lib" / "third-party.yaml").write_text(
        "- dependency\n", encoding="utf-8"
    )
    (fake_root / ".pytest-tmp").mkdir()
    (fake_root / ".pytest-tmp" / "result.json").write_text("not json", encoding="utf-8")

    module.ROOT = fake_root

    assert module._repository_files({".yaml"}) == [fake_root / "docs" / "valid.yaml"]
    assert module._repository_files({".json"}) == []


def test_materials_project_extra_markers_evaluate_for_supported_python_versions() -> None:
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [
        Requirement(item) for item in metadata["project"]["optional-dependencies"]["mp"]
    ]

    def active(name: str, python_version: str) -> list[Requirement]:
        return [
            requirement
            for requirement in requirements
            if requirement.name == name
            and requirement.marker is not None
            and requirement.marker.evaluate({"python_version": python_version})
        ]

    mp_310 = active("mp-api", "3.10")
    mp_313 = active("mp-api", "3.13")
    pmg_310 = active("pymatgen", "3.10")
    pmg_313 = active("pymatgen", "3.13")
    assert len(mp_310) == len(mp_313) == len(pmg_310) == len(pmg_313) == 1
    assert mp_310[0].specifier.contains("0.45")
    assert not mp_310[0].specifier.contains("0.46")
    assert mp_313[0].specifier.contains("0.46")
    assert pmg_310[0].specifier.contains("2025.10.7")
    assert not pmg_310[0].specifier.contains("2026.1")
    assert pmg_313[0].specifier.contains("2026.1")


def test_quick_export_batch_normalizes_first_path_without_delayed_expansion() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "quick_export_diffractscout.bat").read_text(encoding="utf-8")

    assert "DisableDelayedExpansion" in script
    assert "EnableDelayedExpansion" not in script
    assert "set \"FIRST=%~1\"" in script
    assert "%%~dpI%%~nI_diffractscout.xlsx" in script


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows cmd.exe")
def test_quick_export_batch_reports_special_character_sibling_path(
    tmp_path: Path,
) -> None:
    """Run the launcher with cmd metacharacters and verify its user-visible path."""

    root = Path(__file__).resolve().parents[1]
    script = root / "quick_export_diffractscout.bat"
    input_dir = tmp_path / "sample & (pipe)!"
    input_dir.mkdir()
    (input_dir / "sample.cif").write_bytes(
        (root / "examples" / "demo_cifs" / "synthetic_fcc_al.cif").read_bytes()
    )
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "call", str(script), str(input_dir)],
        input="\r\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )

    expected = input_dir.parent / f"{input_dir.name}_diffractscout.xlsx"
    assert completed.returncode == 0, completed.stderr
    assert f'Excel: "{expected}"' in completed.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows cmd.exe")
def test_quick_export_batch_prefers_installed_console_over_unrelated_py(
    tmp_path: Path,
) -> None:
    """A working console entry point wins over an unrelated ``py -3``."""

    root = Path(__file__).resolve().parents[1]
    script = root / "quick_export_diffractscout.bat"
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    console_marker = tmp_path / "console-used.txt"
    py_marker = tmp_path / "py-used.txt"
    console_stub = tmp_path / "diffractscout-quick-export.cmd"
    console_stub.write_text(
        "@echo off\r\necho console>\"%CONSOLE_MARKER%\"\r\nexit /b 0\r\n",
        encoding="ascii",
    )
    py_stub = tmp_path / "py.cmd"
    py_stub.write_text(
        "@echo off\r\necho py>\"%PY_MARKER%\"\r\nexit /b 9\r\n",
        encoding="ascii",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(tmp_path) + os.pathsep + environment.get("PATH", "")
    environment["CONSOLE_MARKER"] = str(console_marker)
    environment["PY_MARKER"] = str(py_marker)
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "call", str(script), str(input_dir)],
        input="\r\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert console_marker.read_text(encoding="ascii").strip() == "console"
    assert not py_marker.exists()
