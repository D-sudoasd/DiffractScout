from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from . import __version__
from .benchmark import run_reference_benchmarks, verify_benchmark_bundle
from .demo import write_demo_inputs
from .models import AnalysisSettings, DiscoverySettings
from .pipeline import analyze_cifs, export_discovery, run_pipeline
from .providers.materials_project import MaterialsProjectProvider
from .utils import to_jsonable
from .validation import verify_bundle


def _analysis_settings(args: argparse.Namespace) -> AnalysisSettings:
    if args.energy_keV is not None:
        mode = "energy"
    elif args.wavelength_A is not None:
        mode = "wavelength"
    else:
        mode = "source"
    return AnalysisSettings(
        input_mode=mode,  # type: ignore[arg-type]
        source_preset=args.source,
        wavelength_A=args.wavelength_A,
        energy_keV=args.energy_keV,
        two_theta_min_deg=args.two_theta_min,
        two_theta_max_deg=args.two_theta_max,
        step_deg=args.step,
        fwhm_deg=args.fwhm,
        profile_eta=args.eta,
        include_elasticity=not args.no_elasticity,
        max_profile_points=args.max_profile_points,
        max_reflection_estimate=args.max_reflection_estimate,
        d_min_A=args.d_min,
        d_max_A=args.d_max,
        profile_model=args.profile_model,
        pattern_axis=args.pattern_axis,
        include_figures=bool(args.figures),
        figure_preset=args.figure_preset,
        export_lab_views=not args.no_lab_views,
        include_patterns=not args.no_patterns,
    )


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


def _print_result(result: object, *, as_json: bool = False) -> None:
    payload = to_jsonable(result)
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if hasattr(result, "output_dir"):
        print(f"Output: {result.output_dir}")
        print(f"Manifest: {result.manifest_path}")
        print(f"Analyzed phases: {len(result.analyses)}")
        if result.discovery is not None:
            print(f"Discovered candidates: {len(result.discovery.candidates)}")
        if result.downloads:
            successful = sum(1 for item in result.downloads if item.status == "ok")
            print(f"Downloads: {successful}/{len(result.downloads)} successful")
        for warning in result.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
    else:
        print(payload)


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


def _add_analysis_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", default="Cu Ka", choices=("Cu Ka", "Co Ka", "Fe Ka", "Mo Ka", "Ag Ka", "Custom"))
    radiation = parser.add_mutually_exclusive_group()
    radiation.add_argument("--energy-keV", type=float, default=None, help="Custom X-ray energy in keV.")
    radiation.add_argument("--wavelength-A", type=float, default=None, help="Custom wavelength in Angstrom.")
    parser.add_argument("--two-theta-min", type=float, default=5.0)
    parser.add_argument("--two-theta-max", type=float, default=120.0)
    parser.add_argument("--step", type=float, default=0.02, help="Display-profile grid spacing in degrees.")
    parser.add_argument("--fwhm", type=float, default=0.15, help="Display-profile FWHM in degrees.")
    parser.add_argument("--eta", type=float, default=0.5, help="Pseudo-Voigt Lorentzian fraction in [0, 1].")
    parser.add_argument("--no-elasticity", action="store_true", help="Do not discover, copy, or calculate paired elastic data.")
    parser.add_argument("--max-profile-points", type=int, default=1_000_000, help="Safety limit for the generated display-profile grid.")
    parser.add_argument("--max-reflection-estimate", type=int, default=2_000_000, help="Safety limit for reciprocal-lattice candidate generation.")
    parser.add_argument("--d-min", type=float, default=None, dest="d_min", help="Minimum d-spacing filter in Å.")
    parser.add_argument("--d-max", type=float, default=None, dest="d_max", help="Maximum d-spacing filter in Å.")
    parser.add_argument(
        "--profile-model",
        choices=("pseudo_voigt", "gaussian", "lorentzian"),
        default="pseudo_voigt",
        help="Display-profile lineshape model.",
    )
    parser.add_argument(
        "--pattern-axis",
        choices=("two_theta", "d_spacing", "q", "g"),
        default="two_theta",
        help="Primary axis label for continuous pattern exports.",
    )
    parser.add_argument("--figures", action="store_true", help="Request figure generation when exporters support it.")
    parser.add_argument("--figure-preset", default="publication", help="Named figure style preset.")
    parser.add_argument(
        "--no-lab-views",
        action="store_true",
        help="Skip laboratory convenience views in the result bundle.",
    )
    parser.add_argument(
        "--no-patterns",
        action="store_true",
        help="Skip continuous powder-pattern series in exports.",
    )
    parser.add_argument("--no-excel", action="store_true", help="Skip results.xlsx; CSV and JSON remain enabled.")
    parser.add_argument("--overwrite", action="store_true", help="Replace only an existing DiffractScout output bundle.")
    parser.add_argument("--json", action="store_true", help="Print the final summary as JSON.")


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
    analyze.add_argument("--no-recursive", action="store_true")
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
    _add_analysis_options(run)
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
    quick.add_argument("--no-recursive", action="store_true")
    _add_analysis_options(quick)

    subparsers.add_parser("gui", help="Launch the optional Tk desktop interface.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            result = analyze_cifs(
                args.inputs,
                args.output,
                settings=_analysis_settings(args),
                recursive=not args.no_recursive,
                include_excel=not args.no_excel,
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
            provider = MaterialsProjectProvider(_api_key(args))
            result = run_pipeline(
                args.composition,
                provider,
                args.output,
                discovery_settings=_discovery_settings(args),
                analysis_settings=_analysis_settings(args),
                conventional_unit_cell=not args.primitive,
                include_elasticity=not args.no_elasticity,
                include_excel=not args.no_excel,
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

            result = quick_export(
                args.inputs,
                args.output,
                settings=_analysis_settings(args),
                recursive=not args.no_recursive,
                include_excel=not args.no_excel,
                overwrite=args.overwrite,
            )
            _print_result(result, as_json=args.json)
            return _pipeline_exit_code(result)

        if args.command == "gui":
            from .gui import main as gui_main

            gui_main()
            return 0
    except (ValueError, FileNotFoundError, FileExistsError, PermissionError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
