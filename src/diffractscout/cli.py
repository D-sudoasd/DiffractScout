from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from . import __version__
from .console import configure_cli_output
from .benchmark import run_reference_benchmarks, verify_benchmark_bundle
from .cli_presets import (
    add_analysis_options,
    resolve_cli_analysis,
    save_cli_preset,
    show_cli_preset,
)
from .demo import write_demo_inputs
from .inspection import format_inspection, inspect_bundle
from .models import AnalysisSettings, DiscoverySettings, PipelineResult
from .pipeline import analyze_cifs, export_discovery, run_pipeline
from .providers.materials_project import MaterialsProjectProvider
from .utils import to_jsonable
from .validation import verify_bundle


def _analysis_settings(args: argparse.Namespace) -> AnalysisSettings:
    return resolve_cli_analysis(args).settings


def _discovery_settings(args: argparse.Namespace) -> DiscoverySettings:
    return DiscoverySettings(
        mode=args.mode,
        e_hull_max_eV_atom=args.e_hull_max,
        max_subsystem_order=args.max_subsystem_order,
        max_subsystems=args.max_subsystems,
        max_per_subsystem=args.max_per_subsystem,
        max_total=args.max_total,
        exclude_deprecated=not args.include_deprecated,
    )


def _api_key(args: argparse.Namespace) -> str:
    value = str(getattr(args, "api_key", "") or os.environ.get("MP_API_KEY", "")).strip()
    if not value:
        raise ValueError("No Materials Project API key. Pass --api-key or set MP_API_KEY.")
    return value


def _diagnostic_lines(result: PipelineResult) -> list[tuple[str, str]]:
    """Render diagnostics with their recorded severity, retaining legacy warnings."""

    lines: list[tuple[str, str]] = []
    represented_messages: set[str] = set()
    seen: set[tuple[str, str, str]] = set()
    for item in result.diagnostics:
        level = item.level.lower()
        if level not in {"warning", "error"}:
            continue
        name = item.item or ""
        message = item.message
        key = (level, name, message)
        if key not in seen:
            seen.add(key)
            lines.append((level.upper(), f"{name}: {message}" if name else message))
        represented_messages.add(f"{name}: {message}" if name else message)

    for warning in result.warnings:
        message = str(warning)
        if message not in represented_messages:
            key = ("warning", "", message)
            if key not in seen:
                seen.add(key)
                lines.append(("WARNING", message))
            represented_messages.add(message)
    return lines


def _result_artifact_paths(
    result: PipelineResult, *, excel_path: str | Path | None = None
) -> dict[str, str]:
    output_dir = result.output_dir
    artifacts: dict[str, str] = {}
    artifacts["manifest"] = str(result.manifest_path)
    diagnostics_path = output_dir / "diagnostics.csv"
    if diagnostics_path.is_file():
        artifacts["diagnostics"] = str(diagnostics_path)
    workbook = Path(excel_path).expanduser() if excel_path is not None else output_dir / "results.xlsx"
    if workbook.is_file():
        artifacts["excel"] = str(workbook.resolve())
    return artifacts


def _print_result(
    result: PipelineResult,
    *,
    as_json: bool = False,
    excel_path: str | Path | None = None,
) -> None:
    if as_json:
        print(json.dumps(to_jsonable(result), indent=2, ensure_ascii=False))
        return
    artifact_paths = _result_artifact_paths(result, excel_path=excel_path)
    diagnostic_lines = _diagnostic_lines(result)
    warning_count = sum(1 for level, _ in diagnostic_lines if level == "WARNING")
    error_count = sum(1 for level, _ in diagnostic_lines if level == "ERROR")
    reflection_count = sum(len(item.reflections) for item in result.analyses)
    print(f"Output: {result.output_dir}")
    print(f"Manifest: {result.manifest_path}")
    if "excel" in artifact_paths:
        print(f"Excel: {artifact_paths['excel']}")
    if "diagnostics" in artifact_paths:
        print(f"Diagnostics: {artifact_paths['diagnostics']}")
    print(f"Analyzed phases: {len(result.analyses)}")
    print(f"Reflections: {reflection_count}")
    print(f"Warnings: {warning_count}")
    print(f"Errors: {error_count}")
    if result.discovery is not None:
        print(f"Discovered candidates: {len(result.discovery.candidates)}")
    if result.downloads:
        successful = sum(1 for item in result.downloads if item.status == "ok")
        print(f"Downloads: {successful}/{len(result.downloads)} successful")
    for level, message in diagnostic_lines:
        print(f"{level}: {message}", file=sys.stderr)


def _pipeline_exit_code(result: object) -> int:
    """Return a machine-actionable status for batch workflows.

    0 means at least one phase succeeded and no error diagnostics were emitted;
    3 means a usable partial bundle was produced with one or more failed items;
    2 means no phase analysis succeeded.
    """

    analyses = list(getattr(result, "analyses", []) or [])
    if not analyses:
        return 2
    diagnostics = list(getattr(result, "diagnostics", []) or [])
    return 3 if any(item.level == "error" for item in diagnostics) else 0


def _add_analysis_options(
    parser: argparse.ArgumentParser,
    *,
    include_preset: bool = True,
    include_output_controls: bool = True,
    include_json: bool = True,
    include_recursive: bool = True,
) -> None:
    add_analysis_options(
        parser,
        include_preset=include_preset,
        include_output_controls=include_output_controls,
        include_json=include_json,
        include_recursive=include_recursive,
    )


def _add_discovery_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=("possible_phases", "near_stable", "single_chemsys", "mpids_only"),
        default="possible_phases",
    )
    parser.add_argument("--e-hull-max", type=float, default=None, help="Maximum energy above hull in eV/atom.")
    parser.add_argument("--max-subsystem-order", type=int, default=None)
    parser.add_argument(
        "--max-subsystems",
        type=int,
        default=4096,
        help="Safety limit for the number of chemical-subsystem queries.",
    )
    parser.add_argument("--max-per-subsystem", type=int, default=None)
    parser.add_argument("--max-total", type=int, default=None)
    parser.add_argument("--include-deprecated", action="store_true")
    parser.add_argument("--api-key", default="", help="Materials Project API key; MP_API_KEY is preferred for shell use.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffractscout",
        description="Phase discovery, CIF validation, theoretical powder XRD, and hkl-resolved elasticity with provenance.",
    )
    parser.add_argument("--version", action="version", version=f"diffractscout {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze local CIF files or directories.")
    analyze.add_argument("inputs", nargs="+", help="CIF files or directories.")
    analyze.add_argument("-o", "--output", required=True)
    _add_analysis_options(analyze)

    discover = subparsers.add_parser("discover", help="Query candidate phases without downloading structures.")
    discover.add_argument("composition", help="Alloy grade, formula, chemical system, or mp-IDs.")
    discover.add_argument("-o", "--output", required=True)
    _add_discovery_options(discover)
    discover.add_argument("--no-excel", action="store_true")
    discover.add_argument("--overwrite", action="store_true")
    discover.add_argument("--json", action="store_true")

    run = subparsers.add_parser("run", help="Discover, download, validate, simulate, and export one traceable bundle.")
    run.add_argument("composition", help="Alloy grade, formula, chemical system, or mp-IDs.")
    run.add_argument("-o", "--output", required=True)
    _add_discovery_options(run)
    _add_analysis_options(run, include_recursive=False)
    run.add_argument(
        "--primitive",
        action="store_true",
        help="Request primitive/final cells. Requires --no-elasticity because tensor rotation is not inferred.",
    )
    run.add_argument("--confirm-above", type=int, default=200)
    run.add_argument("--yes", action="store_true", help="Authorize downloads above --confirm-above.")

    demo = subparsers.add_parser("demo", help="Run the complete offline synthetic validation example.")
    demo.add_argument("-o", "--output", required=True)
    demo.add_argument("--no-excel", action="store_true")
    demo.add_argument("--overwrite", action="store_true")
    demo.add_argument("--json", action="store_true")

    verify = subparsers.add_parser("verify", help="Recalculate every SHA-256 entry in a result bundle.")
    verify.add_argument("bundle")
    verify.add_argument("--json", action="store_true")

    benchmark = subparsers.add_parser(
        "benchmark",
        help="Run deterministic analytic diffraction and elasticity benchmarks.",
    )
    benchmark.add_argument("-o", "--output", required=True)
    benchmark.add_argument("--overwrite", action="store_true")
    benchmark.add_argument("--json", action="store_true")

    quick = subparsers.add_parser(
        "quick-export",
        help="One-shot local CIF analysis with lab-friendly defaults (Excel + verifiable bundle).",
    )
    quick.add_argument("inputs", nargs="+", help="CIF files or directories.")
    quick.add_argument("-o", "--output", required=True, help="Bundle directory or .xlsx path.")
    _add_analysis_options(quick)

    inspect = subparsers.add_parser("inspect", help="Verify a result bundle and summarize its contents.")
    inspect.add_argument("bundle", help="Result bundle directory to inspect.")
    inspect.add_argument("--json", action="store_true", help="Print the inspection report as JSON.")

    preset = subparsers.add_parser("preset", help="Create or inspect reusable analysis presets.")
    preset_commands = preset.add_subparsers(dest="preset_command", required=True)
    preset_save = preset_commands.add_parser("save", help="Save merged analysis options without running an analysis.")
    preset_save.add_argument("-o", "--output", required=True, help="Preset JSON file to create.")
    _add_analysis_options(preset_save, include_output_controls=False, include_json=False)
    preset_save.add_argument("--overwrite", action="store_true", help="Replace an existing preset file.")
    preset_show = preset_commands.add_parser("show", help="Validate and display a preset file.")
    preset_show.add_argument("file", help="Preset JSON file.")
    preset_show.add_argument("--json", action="store_true", help="Print the normalized preset values as JSON.")

    subparsers.add_parser("gui", help="Launch the optional Tk desktop interface.")
    subparsers.add_parser("compat", help="Run built-in CIF2Peaks/PhaseScout workflows; use compat --help.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_cli_output()
    effective = list(sys.argv[1:] if argv is None else argv)
    if effective and effective[0] == "compat":
        from .compat.launcher import main as compat_main

        return compat_main(effective[1:])
    parser = build_parser()
    args = parser.parse_args(effective)
    try:
        if args.command == "analyze":
            analysis = resolve_cli_analysis(args)
            result = analyze_cifs(
                args.inputs,
                args.output,
                settings=analysis.settings,
                recursive=analysis.recursive,
                include_excel=analysis.include_excel,
                overwrite=args.overwrite,
            )
            _print_result(result, as_json=args.json)
            return _pipeline_exit_code(result)

        if args.command == "discover":
            provider = MaterialsProjectProvider(_api_key(args))
            result = export_discovery(
                args.composition,
                provider,
                args.output,
                discovery_settings=_discovery_settings(args),
                include_excel=not args.no_excel,
                overwrite=args.overwrite,
            )
            _print_result(result, as_json=args.json)
            return 0 if result.discovery and result.discovery.candidates else 2

        if args.command == "run":
            analysis = resolve_cli_analysis(args)
            provider = MaterialsProjectProvider(_api_key(args))
            result = run_pipeline(
                args.composition,
                provider,
                args.output,
                discovery_settings=_discovery_settings(args),
                analysis_settings=analysis.settings,
                conventional_unit_cell=not args.primitive,
                include_elasticity=analysis.settings.include_elasticity,
                include_excel=analysis.include_excel,
                overwrite=args.overwrite,
                confirm_above=args.confirm_above,
                authorize_large_download=args.yes,
            )
            _print_result(result, as_json=args.json)
            return _pipeline_exit_code(result)

        if args.command == "demo":
            with tempfile.TemporaryDirectory(prefix="diffractscout_demo_") as temporary:
                inputs = write_demo_inputs(Path(temporary) / "inputs")
                result = analyze_cifs(
                    [inputs],
                    args.output,
                    include_excel=not args.no_excel,
                    overwrite=args.overwrite,
                )
            _print_result(result, as_json=args.json)
            return _pipeline_exit_code(result)

        if args.command == "verify":
            report = verify_bundle(args.bundle)
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
            else:
                print(f"Manifest: {report['manifest']}")
                print("PASS" if report["ok"] else "FAIL")
                for error in report["errors"]:
                    print(f"ERROR: {error}", file=sys.stderr)
            return 0 if report["ok"] else 2

        if args.command == "inspect":
            report = inspect_bundle(args.bundle)
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
            else:
                print(format_inspection(report))
            return 0 if report.get("ok") else 2

        if args.command == "benchmark":
            report = run_reference_benchmarks(
                args.output,
                overwrite=args.overwrite,
            )
            verification = verify_benchmark_bundle(args.output)
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
            else:
                print(f"Output: {report['output_dir']}")
                print(f"Checks: {report['passed_checks']}/{report['total_checks']} passed")
                print(f"Manifest: {report['manifest_path']}")
                print("PASS" if report["all_passed"] and verification["ok"] else "FAIL")
            return 0 if report["all_passed"] and verification["ok"] else 2

        if args.command == "quick-export":
            from .quick_export import quick_export

            excel_path = args.output if Path(args.output).suffix.lower() == ".xlsx" else None
            analysis = resolve_cli_analysis(args)
            result = quick_export(
                args.inputs,
                args.output,
                settings=analysis.settings,
                recursive=analysis.recursive,
                include_excel=analysis.include_excel,
                overwrite=args.overwrite,
            )
            _print_result(result, as_json=args.json, excel_path=excel_path)
            return _pipeline_exit_code(result)

        if args.command == "preset":
            if args.preset_command == "save":
                analysis = resolve_cli_analysis(args)
                target = save_cli_preset(
                    args.output,
                    analysis.preset_values,
                    overwrite=args.overwrite,
                )
                print(f"Preset saved: {target}")
                return 0
            if args.preset_command == "show":
                values = show_cli_preset(args.file)
                if args.json:
                    print(json.dumps(values, indent=2, ensure_ascii=False))
                else:
                    print(f"Preset: {Path(args.file).expanduser()}")
                    for key, value in sorted(values.items()):
                        print(f"{key}: {value}")
                return 0

        if args.command == "gui":
            from .gui import main as gui_main

            return int(gui_main() or 0)
    except (
        ValueError,
        FileNotFoundError,
        FileExistsError,
        PermissionError,
        RuntimeError,
        OSError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
