from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


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
