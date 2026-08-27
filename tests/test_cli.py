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


def test_analyze_help_defines_pattern_export_axis_and_fixed_figure_axis(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["analyze", "--help"])
    assert exc_info.value.code == 0
    raw = capsys.readouterr().out
    raw.encode("cp936")
    assert "Angstrom" in raw
    help_text = " ".join(raw.split())
    assert "pattern_profiles.csv and Excel" in help_text
    assert "Figures remain on 2theta" in help_text


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


def test_cli_maps_oserror_to_error_exit_2(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import diffractscout.cli as cli

    def fail(*_args: object, **_kwargs: object) -> object:
        raise OSError("invalid Windows output path")

    monkeypatch.setattr(cli, "analyze_cifs", fail)
    code = main(["analyze", str(tmp_path), "-o", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.startswith("ERROR:")
    assert "Traceback" not in captured.err


def test_partial_batch_has_distinct_exit_code() -> None:
    class Result:
        analyses = [object()]
        diagnostics = [DiagnosticRecord("analysis", "bad.cif", "error", "failed")]

    assert _pipeline_exit_code(Result()) == 3


def test_gui_constructor_failure_returns_actionable_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    import diffractscout.gui as gui_module

    def fail() -> object:
        raise RuntimeError("Tkinter is unavailable in this Python installation.")

    monkeypatch.setattr(gui_module, "create_app", fail)
    assert main(["gui"]) == 2
    error = capsys.readouterr().err
    assert error.startswith("ERROR: Could not start the DiffractScout GUI:")
    assert "Traceback" not in error
