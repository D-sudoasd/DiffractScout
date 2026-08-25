"""One-shot local CIF analysis with lab-friendly defaults.

``quick_export`` wraps :func:`analyze_cifs` and optionally places
``results.xlsx`` at a user-chosen path while keeping a verifiable bundle.
"""

from __future__ import annotations

import argparse
import errno
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Sequence

from .models import AnalysisSettings, PipelineResult, XrayInputMode
from .pipeline import _acquire_transaction_lock, _release_transaction_lock, analyze_cifs
from .utils import sha256_file, to_jsonable

# Keyword names accepted as AnalysisSettings fields when building defaults.
_SETTINGS_KEYS = frozenset(AnalysisSettings.__dataclass_fields__)


def _normalize_radiation_settings(settings: AnalysisSettings) -> AnalysisSettings:
    """Clear radiation fields that the selected mode does not consume."""

    if settings.input_mode == "energy":
        return replace(settings, wavelength_A=None)
    if settings.input_mode == "wavelength":
        return replace(settings, energy_keV=None)
    if settings.input_mode == "source":
        if settings.source_preset == "Custom":
            return replace(settings, energy_keV=None)
        return replace(settings, wavelength_A=None, energy_keV=None)
    return settings


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


def _file_identity(stat_result: os.stat_result) -> tuple[int, int]:
    return (
        int(getattr(stat_result, "st_dev", 0)),
        int(getattr(stat_result, "st_ino", 0)),
    )


def _remove_owned_excel_target(
    target: Path,
    identity: tuple[int, int] | None,
) -> None:
    """Remove only the fallback file descriptor's exact target object."""

    if identity is None or identity == (0, 0):
        return
    try:
        current = target.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        return
    if _file_identity(current) != identity:
        # Another writer replaced the path; preserving it is mandatory.
        return
    try:
        target.unlink()
    except OSError:
        # Cleanup is best effort and must not mask the primary copy error.
        return


def _copy_excel_atomic(source: Path, target: Path, *, overwrite: bool) -> None:
    """Copy a completed bundle workbook without exposing a partial target."""

    _validate_excel_target(target, overwrite=overwrite)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    fallback_identity: tuple[int, int] | None = None
    source_digest = sha256_file(source)
    source_size = source.stat().st_size
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        shutil.copy2(source, temporary)
        if (
            sha256_file(temporary) != source_digest
            or temporary.stat().st_size != source_size
            or sha256_file(source) != source_digest
            or source.stat().st_size != source_size
        ):
            raise OSError(f"Excel source changed while exporting: {source}")
        if overwrite:
            temporary.replace(target)
        else:
            try:
                # Publish the completed file atomically without replacing a
                # target created after the preflight check.
                os.link(temporary, target)
            except FileExistsError as exc:
                raise FileExistsError(
                    f"Excel output was created while exporting: {target}. "
                    "The new file was preserved; rerun with overwrite=True only if intended."
                ) from exc
            except OSError as exc:
                unsupported = isinstance(exc, PermissionError) or exc.errno in {
                    value
                    for value in (
                        getattr(errno, "EOPNOTSUPP", None),
                        getattr(errno, "ENOTSUP", None),
                        getattr(errno, "EXDEV", None),
                        getattr(errno, "EPERM", None),
                        getattr(errno, "ENOSYS", None),
                    )
                    if value is not None
                }
                if not unsupported:
                    raise
                descriptor: int | None = None
                try:
                    descriptor = os.open(
                        os.fspath(target),
                        os.O_CREAT
                        | os.O_EXCL
                        | os.O_WRONLY
                        | getattr(os, "O_BINARY", 0),
                        0o600,
                    )
                    fallback_identity = _file_identity(os.fstat(descriptor))
                    with os.fdopen(descriptor, "wb") as destination:
                        descriptor = None
                        with temporary.open("rb") as input_file:
                            shutil.copyfileobj(input_file, destination)
                        destination.flush()
                        os.fsync(destination.fileno())
                    try:
                        target_stat = target.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise OSError(
                            f"Could not verify published Excel output: {target}"
                        ) from exc
                    if _file_identity(target_stat) != fallback_identity:
                        raise FileExistsError(
                            f"Excel output changed during fallback publication: {target}"
                        )
                    if (
                        target_stat.st_size != source_size
                        or sha256_file(target) != source_digest
                    ):
                        raise OSError(
                            f"Published Excel output failed integrity verification: {target}"
                        )
                except FileExistsError as exists:
                    raise FileExistsError(
                        f"Excel output was created while exporting: {target}. "
                        "The new file was preserved; rerun with overwrite=True only if intended."
                    ) from exists
                finally:
                    if descriptor is not None:
                        try:
                            os.close(descriptor)
                        except OSError:
                            pass
    except Exception:
        _remove_owned_excel_target(target, fallback_identity)
        raise
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # Cleanup must not replace the primary copy/publication error.
                pass


def _default_settings(**overrides: object) -> AnalysisSettings:
    """Cu Kα, 5–120°, lab views on; other fields match AnalysisSettings defaults."""

    unknown = sorted(str(key) for key in overrides if key not in _SETTINGS_KEYS)
    if unknown:
        raise TypeError(
            "Unexpected keyword arguments for quick_export: " + ", ".join(unknown)
        )

    energy = overrides.get("energy_keV")
    wavelength = overrides.get("wavelength_A")
    has_energy = energy is not None
    has_wavelength = wavelength is not None
    if has_energy and has_wavelength:
        raise ValueError(
            "quick_export radiation overrides conflict: energy_keV and wavelength_A "
            "cannot be supplied together."
        )

    source_preset = str(overrides.get("source_preset", "Cu Ka") or "Cu Ka")
    explicit_mode = overrides.get("input_mode")
    if explicit_mode is not None:
        explicit_mode = str(explicit_mode).strip().lower()
    if has_energy:
        inferred_mode = "energy"
    elif has_wavelength:
        # Python quick-export preserves the public source + Custom wavelength
        # contract when the caller explicitly chooses that source.  For all
        # other cases a wavelength keyword is the wavelength input mode.
        inferred_mode = "source" if source_preset == "Custom" and explicit_mode in {None, "source"} else "wavelength"
    else:
        inferred_mode = None
    if inferred_mode is not None and explicit_mode is not None and explicit_mode != inferred_mode:
        raise ValueError(
            "quick_export radiation override conflicts with explicit input_mode: "
            f"input_mode={explicit_mode!r} cannot be used with "
            f"{('energy_keV' if has_energy else 'wavelength_A')}."
        )

    base: dict[str, object] = {
        "input_mode": "source",
        "source_preset": "Cu Ka",
        "two_theta_min_deg": 5.0,
        "two_theta_max_deg": 120.0,
        "export_lab_views": True,
    }
    for key, value in overrides.items():
        base[key] = value
    if inferred_mode is not None:
        base["input_mode"] = inferred_mode
        if inferred_mode == "energy":
            base["wavelength_A"] = None
        elif inferred_mode == "wavelength":
            base["energy_keV"] = None
        else:
            base["energy_keV"] = None
    return _normalize_radiation_settings(AnalysisSettings(**base))  # type: ignore[arg-type]


def _merge_settings_overrides(
    settings: AnalysisSettings,
    overrides: Mapping[str, object],
) -> AnalysisSettings:
    """Merge quick-export keywords while keeping radiation provenance coherent.

    An explicit radiation keyword cannot be ignored merely because a supplied
    settings object uses another mode.  The exception is the documented
    ``source_preset='Custom'`` + ``wavelength_A`` source-mode contract.
    """

    unknown = sorted(str(key) for key in overrides if key not in _SETTINGS_KEYS)
    if unknown:
        raise TypeError(
            "Unexpected keyword arguments for quick_export: " + ", ".join(unknown)
        )

    energy = overrides.get("energy_keV")
    wavelength = overrides.get("wavelength_A")
    has_energy = energy is not None
    has_wavelength = wavelength is not None
    if has_energy and has_wavelength:
        raise ValueError(
            "quick_export radiation overrides conflict: energy_keV and wavelength_A "
            "cannot be supplied together."
        )

    explicit_mode = overrides.get("input_mode")
    if explicit_mode is not None:
        explicit_mode = str(explicit_mode).strip().lower()
    effective_source = str(
        overrides.get("source_preset", settings.source_preset) or settings.source_preset
    )
    baseline_custom_source = (
        settings.input_mode == "source"
        and settings.source_preset == "Custom"
        and effective_source == "Custom"
    )
    explicit_custom_source = (
        "source_preset" in overrides
        and str(overrides.get("source_preset") or "") == "Custom"
    )
    if has_energy:
        inferred_mode = "energy"
        if explicit_mode is not None and explicit_mode != inferred_mode:
            raise ValueError(
                "quick_export radiation override conflicts with explicit input_mode: "
                f"input_mode={explicit_mode!r} cannot be used with energy_keV."
            )
        merged = dict(overrides)
        merged["input_mode"] = inferred_mode
        merged["wavelength_A"] = None
        return _normalize_radiation_settings(replace(settings, **merged))
    if has_wavelength:
        custom_source_selected = baseline_custom_source or explicit_custom_source
        if explicit_mode == "wavelength":
            inferred_mode = "wavelength"
        elif explicit_mode == "source":
            inferred_mode = "source" if custom_source_selected else "wavelength"
        else:
            inferred_mode = "source" if custom_source_selected else "wavelength"
        if explicit_mode is not None and explicit_mode != inferred_mode:
            raise ValueError(
                "quick_export radiation override conflicts with explicit input_mode: "
                f"input_mode={explicit_mode!r} cannot be used with wavelength_A."
            )
        merged = dict(overrides)
        merged["input_mode"] = inferred_mode
        merged["energy_keV"] = None
        return _normalize_radiation_settings(replace(settings, **merged))

    return _normalize_radiation_settings(replace(settings, **overrides))


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
        settings = _merge_settings_overrides(settings, kwargs)
    settings = _normalize_radiation_settings(settings)

    if elastic_overrides is not None and not isinstance(elastic_overrides, Mapping):
        raise TypeError("elastic_overrides must be a mapping of name -> ElasticTensor.")

    if output is None:
        output_path = Path("diffractscout_quick_export").resolve()
    else:
        output_path = Path(output).expanduser()

    excel_target: Path | None = None
    if output_path.suffix.lower() == ".xlsx":
        excel_target = output_path if output_path.is_absolute() else output_path.resolve()
        bundle_dir = excel_target.with_name(f"{excel_target.stem}_bundle")
        # Excel shortcut always materializes the workbook in the bundle first.
        include_excel = True
    else:
        bundle_dir = output_path if output_path.is_absolute() else output_path.resolve()

    if excel_target is not None:
        # Keep target preflight, bundle generation, and external workbook
        # publication in one fail-closed logical transaction.
        warning_sink: list[str] = []
        lock_path = _acquire_transaction_lock(excel_target, warning_sink=warning_sink)
        try:
            _validate_excel_target(excel_target, overwrite=overwrite)
            result = analyze_cifs(
                inputs,
                bundle_dir,
                settings=settings,
                recursive=recursive,
                include_excel=include_excel,
                overwrite=overwrite,
                elastic_overrides=elastic_overrides,  # type: ignore[arg-type]
            )
            source_xlsx = result.output_dir / "results.xlsx"
            if not source_xlsx.is_file():
                raise RuntimeError(
                    f"Expected results.xlsx in bundle {result.output_dir}, but it is missing."
                )
            _copy_excel_atomic(source_xlsx, excel_target, overwrite=overwrite)
            return result
        finally:
            _release_transaction_lock(lock_path, warning_sink=warning_sink)

    return analyze_cifs(
        inputs,
        bundle_dir,
        settings=settings,
        recursive=recursive,
        include_excel=include_excel,
        overwrite=overwrite,
        elastic_overrides=elastic_overrides,  # type: ignore[arg-type]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffractscout-quick-export",
        description=(
            "One-shot DiffractScout export: Cu K-alpha defaults, optional .xlsx path, "
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
    radiation = parser.add_mutually_exclusive_group()
    radiation.add_argument(
        "--wavelength-A",
        type=float,
        default=None,
        help="Explicit X-ray wavelength in Angstrom (selects wavelength mode).",
    )
    radiation.add_argument(
        "--energy-keV",
        type=float,
        default=None,
        help="Explicit photon energy in keV (selects energy mode).",
    )
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
        help=(
            "Selected x coordinate in pattern_profiles.csv and Excel. "
            "Figures remain on 2theta in v0.4.0."
        ),
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
        input_mode: XrayInputMode
        if args.wavelength_A is not None:
            input_mode = "wavelength"
            wavelength_A = args.wavelength_A
            energy_keV = None
        elif args.energy_keV is not None:
            input_mode = "energy"
            wavelength_A = None
            energy_keV = args.energy_keV
        else:
            input_mode = "source"
            wavelength_A = None
            energy_keV = None
            if args.source == "Custom":
                raise ValueError(
                    "Custom source requires --wavelength-A or --energy-keV."
                )
        settings = AnalysisSettings(
            input_mode=input_mode,
            source_preset=args.source,
            wavelength_A=wavelength_A,
            energy_keV=energy_keV,
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
    except (
        ValueError,
        FileNotFoundError,
        FileExistsError,
        PermissionError,
        RuntimeError,
        TypeError,
        OSError,
    ) as exc:
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
