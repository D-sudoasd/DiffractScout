from pathlib import Path
import json
import shutil

import pytest
from openpyxl import load_workbook

from diffractscout.elasticity_input import parse_cubic_cij
from diffractscout.models import AnalysisSettings
from diffractscout.pipeline import analyze_cifs
from diffractscout.quick_export import build_parser as build_quick_export_parser
from diffractscout.quick_export import main as quick_export_main
from diffractscout.quick_export import _copy_excel_atomic, quick_export
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


def test_atomic_excel_copy_preserves_target_created_during_export(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.xlsx"
    target = tmp_path / "result.xlsx"
    source.write_bytes(b"completed-workbook")

    real_copy2 = shutil.copy2

    def racing_copy(source_path: Path, temporary_path: Path) -> Path:
        copied = real_copy2(source_path, temporary_path)
        target.write_bytes(b"external-file")
        return copied

    monkeypatch.setattr("diffractscout.quick_export.shutil.copy2", racing_copy)

    with pytest.raises(FileExistsError, match="created while exporting"):
        _copy_excel_atomic(source, target, overwrite=False)

    assert target.read_bytes() == b"external-file"
    assert not list(tmp_path.glob(".result.xlsx.*.tmp"))


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


@pytest.mark.parametrize(
    ("radiation_option", "radiation_value", "expected_mode", "expected_wavelength", "expected_energy"),
    [
        ("--wavelength-A", "1.2", "wavelength", pytest.approx(1.2), None),
        ("--energy-keV", "20", "energy", None, pytest.approx(20.0)),
    ],
)
def test_standalone_quick_export_custom_radiation_modes(
    demo_inputs: Path,
    tmp_path: Path,
    radiation_option: str,
    radiation_value: str,
    expected_mode: str,
    expected_wavelength: object,
    expected_energy: object,
) -> None:
    output = tmp_path / f"custom-{expected_mode}"
    code = quick_export_main(
        [
            str(demo_inputs),
            "-o",
            str(output),
            "--source",
            "Custom",
            radiation_option,
            radiation_value,
            "--no-elasticity",
            "--no-excel",
        ]
    )

    assert code == 0
    provenance = json.loads(
        (output / "provenance.json").read_text(encoding="utf-8")
    )
    settings = provenance["analysis_settings"]
    assert settings["input_mode"] == expected_mode
    assert settings["wavelength_A"] == expected_wavelength
    assert settings["energy_keV"] == expected_energy


def test_standalone_quick_export_custom_source_requires_explicit_radiation(
    demo_inputs: Path, tmp_path: Path, capsys
) -> None:
    code = quick_export_main(
        [
            str(demo_inputs),
            "-o",
            str(tmp_path / "missing-custom"),
            "--source",
            "Custom",
            "--no-elasticity",
            "--no-excel",
        ]
    )

    assert code == 2
    assert "Custom source requires --wavelength-A or --energy-keV" in capsys.readouterr().err


def test_standalone_quick_export_radiation_options_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_quick_export_parser().parse_args(
            [
                "sample.cif",
                "-o",
                "out",
                "--wavelength-A",
                "1.2",
                "--energy-keV",
                "20",
            ]
        )
    assert exc_info.value.code == 2


def test_standalone_quick_export_help_is_legacy_windows_console_safe() -> None:
    help_text = build_quick_export_parser().format_help()
    assert "K-alpha" in help_text
    help_text.encode("cp936")


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
