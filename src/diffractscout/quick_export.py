"""One-shot local CIF analysis with lab-friendly defaults.

``quick_export`` wraps :func:`analyze_cifs` and optionally places
``results.xlsx`` at a user-chosen path while keeping a verifiable bundle.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Sequence

from .models import AnalysisSettings, PipelineResult
from .pipeline import analyze_cifs
from .utils import to_jsonable

# Keyword names accepted as AnalysisSettings fields when building defaults.
_SETTINGS_KEYS = frozenset(AnalysisSettings.__dataclass_fields__)


def _validate_excel_target(path: Path, *, overwrite: bool) -> None:
    """Protect a user-selected workbook before the bundle run starts."""

    if path.is_symlink():
        raise FileExistsError(f"Refusing to replace a symbolic-link Excel target: {path}")
    if not path.exists():
        return
    if not path.is_file():
        raise FileExistsError(f"Excel output exists and is not a file: {path}")
    if not overwrite:
        raise FileExistsError(
            f"Excel output already exists: {path}. Choose a new path or pass overwrite=True."
        )


def _copy_excel_atomic(source: Path, target: Path, *, overwrite: bool) -> None:
    """Copy a completed bundle workbook without exposing a partial target."""

    _validate_excel_target(target, overwrite=overwrite)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
        temporary = Path(temporary_name)
        shutil.copy2(source, temporary)
        temporary.replace(target)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _default_settings(**overrides: object) -> AnalysisSettings:
    """Cu Kα, 5–120°, lab views on; other fields match AnalysisSettings defaults."""

    base: dict[str, object] = {
        "input_mode": "source",
        "source_preset": "Cu Ka",
        "two_theta_min_deg": 5.0,
        "two_theta_max_deg": 120.0,
        "export_lab_views": True,
    }
    for key, value in overrides.items():
        if key in _SETTINGS_KEYS:
            base[key] = value
    unknown = sorted(str(key) for key in overrides if key not in _SETTINGS_KEYS)
    if unknown:
        raise TypeError(
            "Unexpected keyword arguments for quick_export: " + ", ".join(unknown)
        )
    return AnalysisSettings(**base)  # type: ignore[arg-type]


def quick_export(
    inputs: Sequence[str | Path],
    output: Path | str | None = None,
    **kwargs: object,
) -> PipelineResult:
    """Analyze CIFs with lab defaults and optional Excel path shortcut.

    Output policy:

    * ``-o path/to/out.xlsx`` writes Excel to that path **and** a full bundle to
      ``path/to/out_bundle/``.
    * ``-o path/to/dir`` is treated as a normal analyze bundle directory.
    * ``output is None`` uses ``./diffractscout_quick_export``.
    """

    include_excel = bool(kwargs.pop("include_excel", True))
    overwrite = bool(kwargs.pop("overwrite", False))
    recursive = bool(kwargs.pop("recursive", True))
    elastic_overrides = kwargs.pop("elastic_overrides", None)
    settings = kwargs.pop("settings", None)

    if settings is not None and not isinstance(settings, AnalysisSettings):
        raise TypeError("settings must be an AnalysisSettings instance or None.")
    if settings is None:
        settings = _default_settings(**kwargs)
    elif kwargs:
        leftover = {key: kwargs[key] for key in kwargs if key not in _SETTINGS_KEYS}
        if leftover:
            raise TypeError(
                "Unexpected keyword arguments for quick_export: "
                + ", ".join(sorted(map(str, leftover)))
            )
        settings = replace(settings, **kwargs)

    if elastic_overrides is not None and not isinstance(elastic_overrides, Mapping):
        raise TypeError("elastic_overrides must be a mapping of name -> ElasticTensor.")

    if output is None:
        output_path = Path("diffractscout_quick_export").resolve()
    else:
        output_path = Path(output).expanduser()

    excel_target: Path | None = None
    if output_path.suffix.lower() == ".xlsx":
        excel_target = output_path if output_path.is_absolute() else output_path.resolve()
        _validate_excel_target(excel_target, overwrite=overwrite)
        bundle_dir = excel_target.with_name(f"{excel_target.stem}_bundle")
        # Excel shortcut always materializes the workbook in the bundle first.
        include_excel = True
    else:
        bundle_dir = output_path if output_path.is_absolute() else output_path.resolve()

    result = analyze_cifs(
        inputs,
        bundle_dir,
        settings=settings,
        recursive=recursive,
        include_excel=include_excel,
        overwrite=overwrite,
        elastic_overrides=elastic_overrides,  # type: ignore[arg-type]
    )

    if excel_target is not None:
        source_xlsx = result.output_dir / "results.xlsx"
        if not source_xlsx.is_file():
            raise RuntimeError(
                f"Expected results.xlsx in bundle {result.output_dir}, but it is missing."
            )
        _copy_excel_atomic(source_xlsx, excel_target, overwrite=overwrite)

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffractscout-quick-export",
        description=(
            "One-shot DiffractScout export: Cu Kα defaults, optional .xlsx path, "
            "verifiable result bundle."
        ),
    )
    parser.add_argument("inputs", nargs="+", help="CIF files or directories.")
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Bundle directory, or an .xlsx path (bundle becomes <stem>_bundle/).",
    )
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--no-excel", action="store_true", help="Skip Excel (bundle dir mode only).")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--source", default="Cu Ka")
    parser.add_argument("--two-theta-min", type=float, default=5.0)
    parser.add_argument("--two-theta-max", type=float, default=120.0)
    parser.add_argument("--step", type=float, default=0.02)
    parser.add_argument("--fwhm", type=float, default=0.15)
    parser.add_argument("--eta", type=float, default=0.5)
    parser.add_argument("--no-elasticity", action="store_true")
    parser.add_argument("--d-min", type=float, default=None, dest="d_min")
    parser.add_argument("--d-max", type=float, default=None, dest="d_max")
    parser.add_argument(
        "--profile-model",
        choices=("pseudo_voigt", "gaussian", "lorentzian"),
        default="pseudo_voigt",
    )
    parser.add_argument(
        "--pattern-axis",
        choices=("two_theta", "d_spacing", "q", "g"),
        default="two_theta",
    )
    parser.add_argument("--figures", action="store_true")
    parser.add_argument("--figure-preset", default="publication")
    parser.add_argument("--no-lab-views", action="store_true")
    parser.add_argument("--no-patterns", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = AnalysisSettings(
            input_mode="source",
            source_preset=args.source,
            two_theta_min_deg=args.two_theta_min,
            two_theta_max_deg=args.two_theta_max,
            step_deg=args.step,
            fwhm_deg=args.fwhm,
            profile_eta=args.eta,
            include_elasticity=not args.no_elasticity,
            d_min_A=args.d_min,
            d_max_A=args.d_max,
            profile_model=args.profile_model,
            pattern_axis=args.pattern_axis,
            include_figures=bool(args.figures),
            figure_preset=args.figure_preset,
            export_lab_views=not args.no_lab_views,
            include_patterns=not args.no_patterns,
        )
        result = quick_export(
            args.inputs,
            args.output,
            settings=settings,
            recursive=not args.no_recursive,
            include_excel=not args.no_excel,
            overwrite=args.overwrite,
        )
    except (ValueError, FileNotFoundError, FileExistsError, PermissionError, RuntimeError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        import json

        print(json.dumps(to_jsonable(result), indent=2, ensure_ascii=False))
    else:
        print(f"Output: {result.output_dir}")
        print(f"Manifest: {result.manifest_path}")
        print(f"Analyzed phases: {len(result.analyses)}")
        if str(args.output).lower().endswith(".xlsx"):
            print(f"Excel: {Path(args.output).expanduser().resolve()}")
        for warning in result.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)

    if not result.analyses:
        return 2
    if any(item.level == "error" for item in result.diagnostics):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
