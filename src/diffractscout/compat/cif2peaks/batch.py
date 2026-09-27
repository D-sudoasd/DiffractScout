from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .constants import DEFAULT_XRD_SOURCE, XRD_SOURCE_PRESETS
from .exporters import (
    export_cif2peaks_json,
    export_cif2peaks_pattern_workbook,
    export_cif2peaks_workbook,
    export_peak_reference_csv,
)
from .models import Cif2PeaksExportPayload, Cif2PeaksSettings, XrdAxisMode
from .service import Cif2PeaksService


def collect_cif_paths(inputs: Sequence[str | Path], *, recursive: bool = True) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for item in inputs:
        path = Path(item).expanduser().resolve()
        candidates: list[Path]
        if path.is_dir():
            iterator = path.rglob("*.cif") if recursive else path.glob("*.cif")
            candidates = sorted(iterator, key=lambda value: str(value).lower())
        else:
            candidates = [path]
        for candidate in candidates:
            resolved = candidate.expanduser().resolve()
            if resolved.suffix.lower() == ".cif" and resolved not in seen:
                paths.append(resolved)
                seen.add(resolved)
    return paths


def export_output_paths(
    output_path: str | Path,
    *,
    export_peaks: bool,
    export_patterns: bool,
) -> tuple[Path | None, Path | None]:
    output = Path(output_path).expanduser().resolve()
    if output.suffix == "":
        output = output.with_suffix(".xlsx")
    if export_peaks and export_patterns:
        return output.with_name(f"{output.stem}_峰表{output.suffix}"), output.with_name(f"{output.stem}_谱线.xlsx")
    if export_patterns:
        return None, output.with_name(f"{output.stem}_谱线.xlsx")
    return output, None


def batch_export_peak_reference(
    inputs: Sequence[str | Path],
    output_path: str | Path,
    settings: Cif2PeaksSettings | None = None,
    *,
    recursive: bool = True,
    export_peaks: bool = True,
    export_patterns: bool = False,
    pattern_axis: XrdAxisMode = "two_theta",
    auto_elastic: bool = True,
) -> list:
    if not export_peaks and not export_patterns:
        raise ValueError("At least one export type must be enabled.")

    cif_paths = collect_cif_paths(inputs, recursive=recursive)
    if not cif_paths:
        raise FileNotFoundError("No CIF files were found.")

    service = Cif2PeaksService()
    resolved_settings = settings or Cif2PeaksSettings()
    phases = service.load_phases(cif_paths, auto_elastic=auto_elastic)
    service.simulate_phases(phases, resolved_settings)
    payload = Cif2PeaksExportPayload(phases, resolved_settings)

    peak_output, pattern_output = export_output_paths(output_path, export_peaks=export_peaks, export_patterns=export_patterns)
    if peak_output is not None:
        peak_output.parent.mkdir(parents=True, exist_ok=True)
        if peak_output.suffix.lower() == ".xlsx":
            export_cif2peaks_workbook(payload, peak_output)
            export_cif2peaks_json(payload, peak_output.with_suffix(".json"))
        else:
            export_peak_reference_csv(payload, peak_output)
    if pattern_output is not None:
        pattern_output.parent.mkdir(parents=True, exist_ok=True)
        export_cif2peaks_pattern_workbook(payload, pattern_output, axis_mode=pattern_axis)
    return phases


def _settings_from_args(args: argparse.Namespace) -> Cif2PeaksSettings:
    input_mode = "source"
    if args.energy_keV is not None:
        input_mode = "energy"
    elif args.wavelength_A is not None:
        input_mode = "wavelength"

    return Cif2PeaksSettings(
        input_mode=input_mode,  # type: ignore[arg-type]
        source_preset=args.source,
        wavelength_A=args.wavelength_A if args.wavelength_A is not None else XRD_SOURCE_PRESETS[DEFAULT_XRD_SOURCE],
        energy_keV=args.energy_keV if args.energy_keV is not None else Cif2PeaksSettings().energy_keV,
        two_theta_min_deg=args.two_theta_min,
        two_theta_max_deg=args.two_theta_max,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch-export theoretical powder XRD peak tables and pattern data from CIF files.",
    )
    parser.add_argument("inputs", nargs="+", help="CIF files or directories containing CIF files.")
    parser.add_argument("-o", "--output", default="cif2peaks_peak_reference.xlsx", help="Output .xlsx or .csv path.")
    parser.add_argument("--no-recursive", action="store_true", help="Do not recurse into input directories.")
    parser.add_argument("--source", default=DEFAULT_XRD_SOURCE, choices=sorted(XRD_SOURCE_PRESETS), help="X-ray source preset.")
    parser.add_argument("--energy-keV", type=float, default=None, help="Use a custom X-ray energy in keV.")
    parser.add_argument("--wavelength-A", type=float, default=None, help="Use a custom wavelength in Angstrom.")
    parser.add_argument("--two-theta-min", type=float, default=0.0, help="Minimum 2theta in degrees.")
    parser.add_argument("--two-theta-max", type=float, default=180.0, help="Maximum 2theta in degrees.")
    parser.add_argument("--export-peaks", dest="export_peaks", action="store_true", default=True, help="Export peak reference table.")
    parser.add_argument("--no-export-peaks", dest="export_peaks", action="store_false", help="Do not export peak reference table.")
    parser.add_argument("--export-patterns", action="store_true", help="Export continuous simulated XRD pattern workbook.")
    parser.add_argument("--pattern-axis", choices=("two_theta", "d_spacing", "q", "g"), default="two_theta", help="X axis for pattern workbook.")
    parser.add_argument(
        "--auto-elastic",
        dest="auto_elastic",
        action="store_true",
        default=True,
        help="Auto-load PhaseScout *_elasticity.json / elasticity_index.csv next to CIFs (default: on).",
    )
    parser.add_argument(
        "--no-auto-elastic",
        dest="auto_elastic",
        action="store_false",
        help="Do not auto-load PhaseScout elasticity sidecars.",
    )
    args = parser.parse_args(argv)

    settings = _settings_from_args(args)
    phases = batch_export_peak_reference(
        args.inputs,
        args.output,
        settings,
        recursive=not args.no_recursive,
        export_peaks=args.export_peaks,
        export_patterns=args.export_patterns,
        pattern_axis=args.pattern_axis,
        auto_elastic=args.auto_elastic,
    )
    peak_count = sum(0 if phase.result is None else len(phase.result.peaks) for phase in phases)
    elastic_n = sum(1 for phase in phases if phase.elastic_constants is not None)
    failed = [phase.cif_path.name for phase in phases if phase.error]
    peak_output, pattern_output = export_output_paths(args.output, export_peaks=args.export_peaks, export_patterns=args.export_patterns)
    outputs = "; ".join(str(path) for path in (peak_output, pattern_output) if path is not None)
    print(f"Exported {peak_count} peaks from {len(phases)} CIF files to {outputs}")
    if args.auto_elastic:
        print(f"Auto-loaded elastic constants for {elastic_n}/{len(phases)} phase(s) (PhaseScout sidecars).")
    if failed:
        print("Failed CIF files: " + ", ".join(failed))
    return 0 if peak_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
