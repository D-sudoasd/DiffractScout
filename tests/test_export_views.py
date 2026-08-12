"""Lab-view Excel sheets and expanded peak/pattern export columns."""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import load_workbook

from diffractscout.demo import write_demo_inputs
from diffractscout.export_views import BEGINNER_PEAK_HEADERS_ZH, beginner_peak_rows_zh, user_guide_rows
from diffractscout.models import AnalysisSettings
from diffractscout.pipeline import analyze_cifs


def test_demo_analyze_writes_lab_view_sheets(tmp_path: Path) -> None:
    inputs = write_demo_inputs(tmp_path / "inputs")
    result = analyze_cifs(
        [inputs],
        tmp_path / "bundle",
        settings=AnalysisSettings(export_lab_views=True),
        include_excel=True,
    )
    workbook_path = result.output_dir / "results.xlsx"
    assert workbook_path.is_file()
    workbook = load_workbook(workbook_path, data_only=False, read_only=True)
    assert "推荐峰表" in workbook.sheetnames
    assert "使用说明" in workbook.sheetnames
    assert "Peaks" in workbook.sheetnames
    recommend = workbook["推荐峰表"]
    headers = [cell.value for cell in next(recommend.iter_rows(min_row=1, max_row=1))]
    assert headers[0] == "物相名称"
    assert "相对强度" in headers
    guide = workbook["使用说明"]
    guide_rows = list(guide.iter_rows(min_row=1, max_row=3, values_only=True))
    assert guide_rows[0][0] == "项目"
    assert any("R_hkl" in str(row[0] or "") or "R_hkl" in str(row[1] or "") for row in guide.iter_rows(values_only=True))


def test_peak_reference_has_two_theta_cu_ka_column(tmp_path: Path) -> None:
    inputs = write_demo_inputs(tmp_path / "inputs")
    result = analyze_cifs([inputs], tmp_path / "bundle", include_excel=False)
    peak_path = result.output_dir / "peak_reference.csv"
    with peak_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    assert "two_theta_cu_ka_deg" in fieldnames
    assert "phase_relative_R_hkl_pct" in fieldnames
    assert "inverse_R_hkl" in fieldnames
    assert "r_hkl_model_note" in fieldnames
    assert rows
    first = rows[0]
    assert first["two_theta_cu_ka_deg"]
    assert float(first["two_theta_cu_ka_deg"]) > 0


def test_pattern_profiles_include_d_axis_columns(tmp_path: Path) -> None:
    inputs = write_demo_inputs(tmp_path / "inputs")
    result = analyze_cifs([inputs], tmp_path / "bundle", include_excel=False)
    pattern_path = result.output_dir / "pattern_profiles.csv"
    with pattern_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    assert "d_A" in fieldnames or "d_spacing" in fieldnames or "d_spacing_A" in fieldnames
    assert "two_theta_deg" in fieldnames
    assert "q_invA" in fieldnames
    assert "g_invA" in fieldnames
    assert "x_axis_mode" in fieldnames
    assert "x" in fieldnames
    assert "relative_intensity" in fieldnames
    assert rows
    sample = rows[len(rows) // 2]
    assert sample["d_A"]
    assert float(sample["d_A"]) > 0
    assert sample["x_axis_mode"] == "two_theta"


def test_include_patterns_false_skips_profile_export(tmp_path: Path) -> None:
    inputs = write_demo_inputs(tmp_path / "inputs")
    result = analyze_cifs(
        [inputs],
        tmp_path / "bundle",
        settings=AnalysisSettings(include_patterns=False, include_elasticity=False),
        include_excel=True,
    )
    assert not (result.output_dir / "pattern_profiles.csv").exists()
    workbook = load_workbook(result.output_dir / "results.xlsx", read_only=True)
    assert "Patterns" not in workbook.sheetnames
    assert "Peaks" in workbook.sheetnames


def test_export_lab_views_false_omits_chinese_sheets(tmp_path: Path) -> None:
    inputs = write_demo_inputs(tmp_path / "inputs")
    result = analyze_cifs(
        [inputs],
        tmp_path / "bundle",
        settings=AnalysisSettings(export_lab_views=False, include_elasticity=False),
        include_excel=True,
    )
    workbook = load_workbook(result.output_dir / "results.xlsx", read_only=True)
    assert "推荐峰表" not in workbook.sheetnames
    assert "使用说明" not in workbook.sheetnames
    assert "Peaks" in workbook.sheetnames


def test_beginner_and_guide_helpers_are_stable() -> None:
    assert BEGINNER_PEAK_HEADERS_ZH["物相名称"] == "phase_name"
    assert BEGINNER_PEAK_HEADERS_ZH["2θ_CuKa_deg"] == "two_theta_cu_ka_deg"
    mapped = beginner_peak_rows_zh(
        [{"phase_name": "Al", "normalized_intensity": 100.0, "two_theta_cu_ka_deg": 38.0}]
    )
    assert mapped[0]["物相名称"] == "Al"
    assert mapped[0]["相对强度"] == 100.0
    guide = user_guide_rows()
    assert guide[0] == ["项目", "说明"]
    joined = "\n".join(cell for row in guide for cell in row)
    assert "不是" in joined and "残差" in joined
    assert "QPA" in joined
