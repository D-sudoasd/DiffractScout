import csv
from pathlib import Path

from openpyxl import load_workbook

from diffractscout.exporters import _write_csv, write_excel_workbook


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
