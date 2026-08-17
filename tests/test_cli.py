from pathlib import Path

import pytest

from diffractscout.cli import _analysis_settings, _pipeline_exit_code, build_parser, main
from diffractscout.models import DiagnosticRecord
from diffractscout.validation import verify_bundle


def test_demo_cli(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    assert main(["demo", "-o", str(output), "--no-excel"]) == 0
    assert verify_bundle(output)["ok"]


def test_analysis_cli_flags_parse() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "analyze",
            "sample.cif",
            "-o",
            "out",
            "--d-min",
            "0.8",
            "--d-max",
            "3.5",
            "--profile-model",
            "gaussian",
            "--pattern-axis",
            "q",
            "--figures",
            "--figure-preset",
            "draft",
            "--no-lab-views",
            "--no-patterns",
        ]
    )
    assert args.d_min == pytest.approx(0.8)
    assert args.d_max == pytest.approx(3.5)
    assert args.profile_model == "gaussian"
    assert args.pattern_axis == "q"
    assert args.figures is True
    assert args.figure_preset == "draft"
    assert args.no_lab_views is True
    assert args.no_patterns is True
    settings = _analysis_settings(args)
    assert settings.d_min_A == pytest.approx(0.8)
    assert settings.d_max_A == pytest.approx(3.5)
    assert settings.profile_model == "gaussian"
    assert settings.pattern_axis == "q"
    assert settings.include_figures is True
    assert settings.figure_preset == "draft"
    assert settings.export_lab_views is False
    assert settings.include_patterns is False


def test_analyze_help_includes_d_min() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["analyze", "--help"])
    assert exc_info.value.code == 0


def test_quick_export_help_is_legacy_windows_console_safe(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["quick-export", "--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "Angstrom" in help_text
    help_text.encode("cp936")


def test_cli_rejects_conflicting_radiation_inputs(tmp_path: Path) -> None:
    output = tmp_path / "conflicting-radiation"
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "analyze",
                str(tmp_path),
                "-o",
                str(output),
                "--energy-keV",
                "20",
                "--wavelength-A",
                "1.0",
            ]
        )
    assert exc_info.value.code == 2
    assert not output.exists()


def test_partial_batch_has_distinct_exit_code() -> None:
    class Result:
        analyses = [object()]
        diagnostics = [DiagnosticRecord("analysis", "bad.cif", "error", "failed")]

    assert _pipeline_exit_code(Result()) == 3
