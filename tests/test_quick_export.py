from pathlib import Path

import pytest
from openpyxl import load_workbook

from diffractscout.elasticity_input import parse_cubic_cij
from diffractscout.models import AnalysisSettings
from diffractscout.pipeline import analyze_cifs
from diffractscout.quick_export import main as quick_export_main
from diffractscout.quick_export import quick_export
from diffractscout.validation import verify_bundle


def test_quick_export_xlsx_writes_excel_and_bundle(demo_inputs: Path, tmp_path: Path) -> None:
    excel = tmp_path / "report.xlsx"
    result = quick_export([demo_inputs], excel)
    assert excel.is_file()
    bundle = tmp_path / "report_bundle"
    assert result.output_dir == bundle.resolve()
    assert (bundle / "manifest.json").is_file()
    assert (bundle / "results.xlsx").is_file()
    assert verify_bundle(bundle)["ok"]
    workbook = load_workbook(excel, read_only=True)
    assert "Peaks" in workbook.sheetnames


def test_quick_export_does_not_replace_existing_excel_without_authorization(
    demo_inputs: Path, tmp_path: Path
) -> None:
    excel = tmp_path / "existing.xlsx"
    excel.write_bytes(b"user workbook")

    with pytest.raises(FileExistsError, match="already exists"):
        quick_export([demo_inputs], excel)

    assert excel.read_bytes() == b"user workbook"
    assert not (tmp_path / "existing_bundle").exists()


def test_quick_export_can_atomically_replace_existing_excel_when_authorized(
    demo_inputs: Path, tmp_path: Path
) -> None:
    excel = tmp_path / "existing.xlsx"
    excel.write_bytes(b"old workbook")

    result = quick_export([demo_inputs], excel, overwrite=True)

    assert result.output_dir == (tmp_path / "existing_bundle").resolve()
    assert excel.read_bytes() != b"old workbook"
    assert load_workbook(excel, read_only=True).sheetnames


def test_quick_export_directory_mode(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "lab_bundle"
    result = quick_export([demo_inputs], output)
    assert result.output_dir == output.resolve()
    assert (output / "results.xlsx").is_file()
    assert result.analyses[0].metadata.get("export_lab_views") is True


def test_quick_export_keyword_overrides_apply_to_explicit_settings(
    demo_inputs: Path, tmp_path: Path
) -> None:
    result = quick_export(
        [demo_inputs],
        tmp_path / "overrides",
        settings=AnalysisSettings(step_deg=0.02),
        step_deg=0.05,
        include_excel=False,
    )
    assert result.analyses[0].metadata["step_deg"] == pytest.approx(0.05)


def test_quick_export_cli_entry(demo_inputs: Path, tmp_path: Path) -> None:
    excel = tmp_path / "cli_out.xlsx"
    code = quick_export_main([str(demo_inputs), "-o", str(excel)])
    assert code == 0
    assert excel.is_file()
    assert (tmp_path / "cli_out_bundle" / "manifest.json").is_file()


def test_elastic_override_replaces_sidecar(demo_inputs: Path, tmp_path: Path) -> None:
    """Override keyed by stem must be used instead of the demo sidecar."""

    override = parse_cubic_cij(250.0, 100.0, 50.0, source="override_test")
    output = tmp_path / "override_bundle"
    result = analyze_cifs(
        [demo_inputs],
        output,
        include_excel=False,
        elastic_overrides={"synthetic_fcc_al": override},
    )
    tensor = result.analyses[0].elastic_tensor
    assert tensor is not None
    assert tensor.stiffness_GPa[0, 0] == pytest.approx(250.0)
    assert tensor.source_provider == "user_input"
