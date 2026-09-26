import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from diffractscout.cli import (
    _analysis_settings,
    _diagnostic_lines,
    _pipeline_exit_code,
    _print_result,
    build_parser,
    main,
)
from diffractscout.models import DiagnosticRecord, PipelineResult
import diffractscout.cli_presets as cli_presets
from diffractscout.cli_presets import resolve_cli_analysis, save_cli_preset
from diffractscout.validation import verify_bundle


def test_demo_cli(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    assert main(["demo", "-o", str(output), "--no-excel"]) == 0
    assert verify_bundle(output)["ok"]


def test_cli_partial_batch_reports_severity_counts_and_artifact_paths(
    demo_inputs: Path, tmp_path: Path, capsys
) -> None:
    (demo_inputs / "empty.cif").write_text("", encoding="utf-8")
    output = tmp_path / "partial"

    code = main(
        ["analyze", str(demo_inputs), "-o", str(output), "--no-excel"]
    )

    captured = capsys.readouterr()
    assert code == 3
    assert "ERROR: empty.cif:" in captured.err
    assert "WARNING: empty.cif:" not in captured.err
    assert "Analyzed phases: 1" in captured.out
    reflection_line = next(
        line for line in captured.out.splitlines() if line.startswith("Reflections: ")
    )
    assert int(reflection_line.split(": ", 1)[1]) > 0
    assert "Warnings: 0" in captured.out
    assert "Errors: 1" in captured.out
    assert f"Diagnostics: {output / 'diagnostics.csv'}" in captured.out
    assert "Excel:" not in captured.out


def test_cli_json_keeps_pipeline_result_serialization_contract(
    tmp_path: Path, capsys
) -> None:
    output = tmp_path / "json-demo"
    code = main(["demo", "-o", str(output), "--no-excel", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert set(payload) == {
        "output_dir",
        "discovery",
        "downloads",
        "analyses",
        "manifest_path",
        "warnings",
        "diagnostics",
    }
    assert "summary" not in payload
    assert "artifact_paths" not in payload


def test_cli_summary_deduplicates_diagnostics_and_legacy_warnings(
    tmp_path: Path, capsys
) -> None:
    bundle = tmp_path / "summary"
    bundle.mkdir()
    (bundle / "diagnostics.csv").write_text("diagnostics", encoding="utf-8")
    (bundle / "results.xlsx").write_bytes(b"workbook")
    message = "failed to parse"
    result = PipelineResult(
        output_dir=bundle,
        discovery=None,
        downloads=[],
        analyses=[SimpleNamespace(reflections=[object(), object()])],  # type: ignore[list-item]
        manifest_path=bundle / "manifest.json",
        warnings=[f"broken.cif: {message}", "transaction cleanup", "transaction cleanup"],
        diagnostics=[
            DiagnosticRecord("analysis", "broken.cif", "error", message),
            DiagnosticRecord("analysis", "broken.cif", "error", message),
        ],
    )

    lines = _diagnostic_lines(result)
    _print_result(result)
    captured = capsys.readouterr()

    assert lines == [
        ("ERROR", f"broken.cif: {message}"),
        ("WARNING", "transaction cleanup"),
    ]
    assert f"Excel: {bundle / 'results.xlsx'}" in captured.out
    assert f"Diagnostics: {bundle / 'diagnostics.csv'}" in captured.out
    assert "Reflections: 2" in captured.out
    assert "Warnings: 1" in captured.out
    assert "Errors: 1" in captured.out
    assert captured.err.count("ERROR: broken.cif:") == 1
    assert captured.err.count("WARNING: transaction cleanup") == 1


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


def test_analysis_parser_explicit_tracking_does_not_leak_between_parses() -> None:
    parser = build_parser()
    explicit = parser.parse_args(
        ["analyze", "sample.cif", "-o", "first", "--no-excel", "--two-theta-max", "80"]
    )
    defaults = parser.parse_args(["analyze", "sample.cif", "-o", "second"])

    assert explicit._diffractscout_explicit == {"no_excel", "two_theta_max"}
    assert not getattr(defaults, "_diffractscout_explicit", set())


def test_preset_save_show_and_cli_values_override_preset(tmp_path: Path, capsys) -> None:
    preset_path = tmp_path / "analysis.json"
    assert main(
        [
            "preset",
            "save",
            "-o",
            str(preset_path),
            "--energy-keV",
            "30",
            "--two-theta-max",
            "75",
            "--d-min",
            "0.8",
            "--d-max",
            "3.2",
            "--no-excel",
            "--no-elasticity",
            "--no-lab-views",
            "--no-patterns",
            "--no-figures",
            "--no-recursive",
        ]
    ) == 0
    assert preset_path.is_file()
    assert not (tmp_path / "analysis").is_dir()

    parser = build_parser()
    args = parser.parse_args(
        [
            "analyze",
            "sample.cif",
            "-o",
            str(tmp_path / "bundle"),
            "--preset",
            str(preset_path),
            "--excel",
            "--elasticity",
            "--lab-views",
            "--patterns",
            "--figures",
            "--recursive",
            "--two-theta-max",
            "80",
            "--clear-d-min",
        ]
    )
    resolved = resolve_cli_analysis(args)
    assert resolved.settings.input_mode == "energy"
    assert resolved.settings.energy_keV == pytest.approx(30)
    assert resolved.settings.two_theta_max_deg == pytest.approx(80)
    assert resolved.settings.d_min_A is None
    assert resolved.settings.d_max_A == pytest.approx(3.2)
    assert resolved.settings.include_elasticity is True
    assert resolved.settings.export_lab_views is True
    assert resolved.settings.include_patterns is True
    assert resolved.settings.include_figures is True
    assert resolved.include_excel is True
    assert resolved.recursive is True
    assert main(["preset", "show", str(preset_path), "--json"]) == 0
    shown = json.loads(capsys.readouterr().out.split("Preset saved:", 1)[-1].split("\n", 1)[-1])
    assert shown["input_mode"] == "energy"
    assert shown["include_excel"] is False
    assert shown["local_recursive"] is False
    assert len(shown) == 20

    enabled_preset = tmp_path / "enabled.json"
    assert main(
        [
            "preset",
            "save",
            "-o",
            str(enabled_preset),
            "--excel",
            "--elasticity",
            "--lab-views",
            "--patterns",
            "--figures",
            "--recursive",
        ]
    ) == 0
    disabled = resolve_cli_analysis(
        build_parser().parse_args(
            [
                "analyze",
                "sample.cif",
                "-o",
                "out",
                "--preset",
                str(enabled_preset),
                "--no-excel",
                "--no-elasticity",
                "--no-lab-views",
                "--no-patterns",
                "--no-figures",
                "--no-recursive",
            ]
        )
    )
    assert disabled.include_excel is False
    assert disabled.recursive is False
    assert disabled.settings.include_elasticity is False
    assert disabled.settings.export_lab_views is False
    assert disabled.settings.include_patterns is False
    assert disabled.settings.include_figures is False


def test_preset_radiation_switching_uses_units_and_source_mode(tmp_path: Path) -> None:
    energy_preset = tmp_path / "energy.json"
    assert main(
        ["preset", "save", "-o", str(energy_preset), "--energy-keV", "30"]
    ) == 0
    parser = build_parser()
    builtin = resolve_cli_analysis(
        parser.parse_args(
            ["analyze", "sample.cif", "-o", "out", "--preset", str(energy_preset), "--source", "Co Ka"]
        )
    )
    assert builtin.settings.input_mode == "source"
    assert builtin.settings.source_preset == "Co Ka"
    assert builtin.settings.energy_keV is None
    assert builtin.settings.wavelength_A is None

    with pytest.raises(ValueError, match="cannot be reinterpreted as Angstrom"):
        resolve_cli_analysis(
            parser.parse_args(
                ["analyze", "sample.cif", "-o", "out", "--preset", str(energy_preset), "--source", "Custom"]
            )
        )

    custom_preset = tmp_path / "custom.json"
    assert main(
        [
            "preset",
            "save",
            "-o",
            str(custom_preset),
            "--source",
            "Custom",
            "--wavelength-A",
            "1.2",
        ]
    ) == 0
    custom = resolve_cli_analysis(
        parser.parse_args(["analyze", "sample.cif", "-o", "out", "--preset", str(custom_preset)])
    )
    assert custom.settings.input_mode == "wavelength"
    assert custom.settings.source_preset == "Custom"
    assert custom.settings.wavelength_A == pytest.approx(1.2)


def test_explicit_command_default_overrides_preset_value(tmp_path: Path) -> None:
    preset_path = tmp_path / "non-default.json"
    assert main(
        ["preset", "save", "-o", str(preset_path), "--two-theta-max", "75"]
    ) == 0
    args = build_parser().parse_args(
        [
            "analyze",
            "sample.cif",
            "-o",
            "out",
            "--preset",
            str(preset_path),
            "--two-theta-max",
            "120",
        ]
    )
    assert resolve_cli_analysis(args).settings.two_theta_max_deg == pytest.approx(120)


def test_preset_save_refuses_existing_files_and_result_bundles(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    preset_path = tmp_path / "existing.json"
    preset_path.write_text("preserve", encoding="utf-8")
    assert main(["preset", "save", "-o", str(preset_path)]) == 2
    assert preset_path.read_text(encoding="utf-8") == "preserve"
    assert main(["preset", "save", "-o", str(preset_path), "--overwrite"]) == 0

    bundle = tmp_path / "bundle"
    assert main(["demo", "-o", str(bundle), "--no-excel"]) == 0
    manifest_path = bundle / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    preset_inside_bundle = bundle / "parameters.json"
    assert main(["preset", "save", "-o", str(preset_inside_bundle), "--overwrite"]) == 2
    assert not preset_inside_bundle.exists()
    assert main(["preset", "save", "-o", str(manifest_path), "--overwrite"]) == 2
    assert manifest_path.read_bytes() == manifest_before
    assert verify_bundle(bundle)["ok"]

    target = tmp_path / "symlink.json"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(ValueError, match="symbolic link"):
        save_cli_preset(target, resolve_cli_analysis(build_parser().parse_args(
            ["analyze", "sample.cif", "-o", "unused"]
        )).preset_values)
    assert "Pass --overwrite" in capsys.readouterr().err


def test_preset_save_no_clobber_is_atomic_against_competing_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "racing-preset.json"
    analysis = resolve_cli_analysis(
        build_parser().parse_args(["analyze", "sample.cif", "-o", "unused"])
    )
    save_impl = cli_presets.save_analysis_preset

    def create_competing_target(
        path: str | Path,
        values: dict[str, object],
        *,
        overwrite: bool = True,
    ) -> Path:
        # This executes after save_cli_preset's existence check and before its
        # atomic publication attempt.
        target.write_text("created by competing process", encoding="utf-8")
        return save_impl(path, values, overwrite=overwrite)

    monkeypatch.setattr(cli_presets, "save_analysis_preset", create_competing_target)

    with pytest.raises(FileExistsError, match="Pass --overwrite"):
        save_cli_preset(target, analysis.preset_values)

    assert target.read_text(encoding="utf-8") == "created by competing process"
    assert list(tmp_path.glob(".diffractscout-preset-*.tmp")) == []


def test_invalid_preset_fails_before_analysis_or_output_creation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import diffractscout.cli as cli

    preset_path = tmp_path / "invalid.json"
    preset_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "should-not-exist"
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("analysis should not be called")

    monkeypatch.setattr(cli, "analyze_cifs", fail_if_called)
    assert main(
        ["analyze", "sample.cif", "-o", str(output), "--preset", str(preset_path)]
    ) == 2
    assert not called
    assert not output.exists()
    assert "Invalid analysis preset" in capsys.readouterr().err


def test_inspect_cli_returns_json_inspection_report(tmp_path: Path, capsys) -> None:
    bundle = tmp_path / "inspect-demo"
    assert main(["demo", "-o", str(bundle), "--no-excel"]) == 0
    capsys.readouterr()
    assert main(["inspect", str(bundle), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema"] == "diffractscout_inspection_v1"
    assert report["ok"] is True
    assert report["verification"]["ok"] is True
    assert report["counts"]["phases"] >= 1


def test_cli_empty_input_directory_returns_error_exit_2(
    tmp_path: Path, capsys
) -> None:
    empty = tmp_path / "no-cifs"
    empty.mkdir()
    output = tmp_path / "cli-empty-out"
    code = main(["analyze", str(empty), "-o", str(output), "--no-excel"])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.startswith("ERROR:")
    assert "No CIF files" in captured.err
    assert not output.exists()


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
