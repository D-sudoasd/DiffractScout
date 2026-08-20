import csv
import json
from pathlib import Path

import pytest

from openpyxl import load_workbook

import diffractscout.exporters as exporters
from diffractscout.demo import write_demo_inputs
from diffractscout.exporters import _write_csv, write_excel_workbook
from diffractscout.pipeline import analyze_cifs


def test_csv_and_excel_escape_formula_like_external_text(tmp_path: Path) -> None:
    csv_path = tmp_path / "safe.csv"
    _write_csv(csv_path, [{"value": "=HYPERLINK(\"https://example.invalid\")"}], ["value"])
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["value"].startswith("'=")

    workbook_path = tmp_path / "safe.xlsx"
    write_excel_workbook(
        workbook_path,
        summary=[{"key": "external", "value": "+SUM(1,1)"}],
        phases=[],
        peaks=[],
        elasticity=[],
        candidates=[],
        downloads=[],
        diagnostics=[],
        patterns=[],
    )
    workbook = load_workbook(workbook_path, data_only=False, read_only=True)
    assert workbook["Summary"]["B2"].value == "'+SUM(1,1)"


def test_empty_csv_keeps_a_stable_header(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    _write_csv(path, [], ["a", "b"])
    assert path.read_text(encoding="utf-8-sig").splitlines() == ["a,b"]


def test_write_text_atomic_cleans_unique_temp_after_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "README.md"
    path.write_text("old", encoding="utf-8")

    def fail_replace(self: Path, _target: Path) -> Path:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        exporters._write_text_atomic(path, "new")

    assert path.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".README.md.*.tmp"))


def test_write_text_atomic_preserves_replace_error_when_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "README.md"

    def fail_replace(self: Path, _target: Path) -> Path:
        raise OSError("primary replace failure")

    def fail_unlink(self: Path, *, missing_ok: bool = False) -> None:
        raise PermissionError("cleanup failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(OSError, match="primary replace failure"):
        exporters._write_text_atomic(path, "new")


def test_write_text_atomic_returns_published_path_when_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "README.md"

    def fail_unlink(self: Path, *, missing_ok: bool = False) -> None:
        raise PermissionError("cleanup failure")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    assert exporters._write_text_atomic(path, "new") == path
    assert path.read_text(encoding="utf-8") == "new"


def test_excel_uses_an_omission_note_above_row_limit(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(exporters, "EXCEL_DATA_ROW_LIMIT", 2)
    workbook_path = tmp_path / "limited.xlsx"
    write_excel_workbook(
        workbook_path,
        summary=[],
        phases=[],
        peaks=[{"phase_name": str(index)} for index in range(3)],
        elasticity=[],
        candidates=[],
        downloads=[],
        diagnostics=[],
        patterns=[],
    )
    workbook = load_workbook(workbook_path, data_only=False, read_only=True)
    assert workbook["Peaks"]["A2"].value == "omitted_from_workbook"
    assert "corresponding CSV" in workbook["Peaks"]["B2"].value


def test_provenance_records_portable_runtime_environment(tmp_path: Path) -> None:
    inputs = write_demo_inputs(tmp_path / "inputs")
    result = analyze_cifs([inputs], tmp_path / "bundle", include_excel=False)
    payload = json.loads((result.output_dir / "provenance.json").read_text(encoding="utf-8"))
    environment = payload["runtime_environment"]
    assert environment["python"]
    assert environment["operating_system"]
    assert "executable" not in environment
    assert "hostname" not in environment
