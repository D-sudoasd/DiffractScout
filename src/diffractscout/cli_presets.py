from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .gui_settings import load_analysis_preset, save_analysis_preset
from .models import AnalysisSettings

_EXPLICIT_ATTR = "_diffractscout_explicit"


class _TrackedStore(argparse.Action):
    """Store an option and mark its destination on this parse namespace."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, values)
        explicit = set(getattr(namespace, _EXPLICIT_ATTR, ()))
        explicit.add(self.dest)
        setattr(namespace, _EXPLICIT_ATTR, explicit)


class _TrackedConst(argparse.Action):
    """Store a fixed value and mark its destination on this parse namespace."""

    def __init__(self, option_strings: list[str], dest: str, *, const: Any, **kwargs: Any) -> None:
        super().__init__(option_strings, dest, nargs=0, **kwargs)
        self.const = const

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, self.const)
        explicit = set(getattr(namespace, _EXPLICIT_ATTR, ()))
        explicit.add(self.dest)
        setattr(namespace, _EXPLICIT_ATTR, explicit)


@dataclass(frozen=True)
class ResolvedCliAnalysis:
    settings: AnalysisSettings
    include_excel: bool
    recursive: bool
    preset_values: dict[str, object]


def _tracked_value(
    parser: argparse.ArgumentParser,
    *option_strings: str,
    dest: str | None = None,
    **kwargs: Any,
) -> None:
    parser.add_argument(*option_strings, dest=dest, action=_TrackedStore, **kwargs)


def _tracked_bool(
    parser: argparse.ArgumentParser,
    *,
    positive: str,
    negative: str,
    dest: str,
    default: bool,
    positive_value: bool,
    help: str,
    negative_help: str,
) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        positive,
        dest=dest,
        action=_TrackedConst,
        const=positive_value,
        default=default,
        help=help,
    )
    group.add_argument(
        negative,
        dest=dest,
        action=_TrackedConst,
        const=not positive_value,
        help=negative_help,
    )


def add_analysis_options(
    parser: argparse.ArgumentParser,
    *,
    include_preset: bool = True,
    include_output_controls: bool = True,
    include_json: bool = True,
    include_recursive: bool = True,
) -> None:
    """Add shared analysis arguments with reliable per-parse explicit tracking."""

    if include_preset:
        parser.add_argument("--preset", help="Load analysis parameters from a DiffractScout preset JSON file.")
    _tracked_value(
        parser,
        "--source",
        choices=("Cu Ka", "Co Ka", "Fe Ka", "Mo Ka", "Ag Ka", "Custom"),
        default="Cu Ka",
    )
    radiation = parser.add_mutually_exclusive_group()
    _tracked_value(
        radiation,
        "--energy-keV",
        type=float,
        default=None,
        help="Custom X-ray energy in keV; selects energy mode.",
    )
    _tracked_value(
        radiation,
        "--wavelength-A",
        type=float,
        default=None,
        help="Custom wavelength in Angstrom; selects wavelength mode.",
    )

    float_options = (
        ("--two-theta-min", "two_theta_min", 5.0, "Minimum 2theta in degrees."),
        ("--two-theta-max", "two_theta_max", 120.0, "Maximum 2theta in degrees."),
        ("--step", "step", 0.02, "Display-profile grid spacing in degrees."),
        ("--fwhm", "fwhm", 0.15, "Display-profile FWHM in degrees."),
        ("--eta", "eta", 0.5, "Pseudo-Voigt Lorentzian fraction in [0, 1]."),
    )
    for option, dest, default, help_text in float_options:
        _tracked_value(parser, option, dest=dest, type=float, default=default, help=help_text)

    _tracked_bool(
        parser,
        positive="--elasticity",
        negative="--no-elasticity",
        dest="no_elasticity",
        default=False,
        positive_value=False,
        help="Include paired elastic data (default).",
        negative_help="Do not discover, copy, or calculate paired elastic data.",
    )
    _tracked_value(
        parser,
        "--max-profile-points",
        type=int,
        default=1_000_000,
        help="Safety limit for the generated display-profile grid.",
    )
    _tracked_value(
        parser,
        "--max-reflection-estimate",
        type=int,
        default=2_000_000,
        help="Safety limit for reciprocal-lattice candidate generation.",
    )

    for option, clear_option, dest, help_text in (
        ("--d-min", "--clear-d-min", "d_min", "Minimum d-spacing filter in Angstrom."),
        ("--d-max", "--clear-d-max", "d_max", "Maximum d-spacing filter in Angstrom."),
    ):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(option, type=float, default=None, dest=dest, action=_TrackedStore, help=help_text)
        group.add_argument(
            clear_option,
            dest=dest,
            action=_TrackedConst,
            const=None,
            help=f"Clear the {dest.replace('_', '-')} filter from the loaded preset.",
        )

    _tracked_value(
        parser,
        "--profile-model",
        choices=("pseudo_voigt", "gaussian", "lorentzian"),
        default="pseudo_voigt",
        help="Display-profile lineshape model.",
    )
    _tracked_value(
        parser,
        "--pattern-axis",
        choices=("two_theta", "d_spacing", "q", "g"),
        default="two_theta",
        help=(
            "Selected x coordinate in pattern_profiles.csv and Excel. "
            "Figures remain on 2theta in v0.4.0."
        ),
    )
    _tracked_bool(
        parser,
        positive="--figures",
        negative="--no-figures",
        dest="figures",
        default=False,
        positive_value=True,
        help="Write 2theta figures (SVG and PNG in result bundles).",
        negative_help="Skip 2theta figure files in result bundles.",
    )
    _tracked_value(
        parser,
        "--figure-preset",
        default="publication",
        help="Presentation-only figure style; this setting is not stored in analysis presets.",
    )
    _tracked_bool(
        parser,
        positive="--lab-views",
        negative="--no-lab-views",
        dest="no_lab_views",
        default=False,
        positive_value=False,
        help="Include laboratory convenience views (default).",
        negative_help="Skip laboratory convenience views in the result bundle.",
    )
    _tracked_bool(
        parser,
        positive="--patterns",
        negative="--no-patterns",
        dest="no_patterns",
        default=False,
        positive_value=False,
        help="Include continuous powder-pattern series (default).",
        negative_help="Skip continuous powder-pattern series in exports.",
    )
    _tracked_bool(
        parser,
        positive="--excel",
        negative="--no-excel",
        dest="no_excel",
        default=False,
        positive_value=False,
        help="Write results.xlsx (default).",
        negative_help="Skip results.xlsx; quick-export requires a bundle-directory output.",
    )
    if include_recursive:
        _tracked_bool(
            parser,
            positive="--recursive",
            negative="--no-recursive",
            dest="no_recursive",
            default=False,
            positive_value=False,
            help="Search input directories recursively (default).",
            negative_help="Do not search input directories recursively.",
        )
    if include_output_controls:
        parser.add_argument("--overwrite", action="store_true", help="Replace only an existing DiffractScout output bundle.")
    if include_json:
        parser.add_argument("--json", action="store_true", help="Print the final summary as JSON.")


def _default_preset_values() -> dict[str, object]:
    settings = AnalysisSettings()
    return {
        "input_mode": settings.input_mode,
        "source_preset": settings.source_preset,
        "radiation_value": None,
        "two_theta_min": settings.two_theta_min_deg,
        "two_theta_max": settings.two_theta_max_deg,
        "step": settings.step_deg,
        "fwhm": settings.fwhm_deg,
        "eta": settings.profile_eta,
        "d_min_A": settings.d_min_A,
        "d_max_A": settings.d_max_A,
        "profile_model": settings.profile_model,
        "pattern_axis": settings.pattern_axis,
        "max_profile_points": settings.max_profile_points,
        "max_reflection_estimate": settings.max_reflection_estimate,
        "include_excel": True,
        "include_elasticity": settings.include_elasticity,
        "export_lab_views": settings.export_lab_views,
        "include_patterns": settings.include_patterns,
        "include_figures": settings.include_figures,
        "local_recursive": True,
    }


def _settings_from_values(values: dict[str, object], figure_preset: str) -> AnalysisSettings:
    mode = str(values["input_mode"])
    source = str(values["source_preset"])
    radiation = values["radiation_value"]
    wavelength = None
    energy = None
    if radiation is not None:
        if mode == "energy":
            energy = float(radiation)
        elif mode == "wavelength" or (mode == "source" and source == "Custom"):
            wavelength = float(radiation)
    settings = AnalysisSettings(
        input_mode=mode,  # type: ignore[arg-type]
        source_preset=source,
        wavelength_A=wavelength,
        energy_keV=energy,
        two_theta_min_deg=float(values["two_theta_min"]),
        two_theta_max_deg=float(values["two_theta_max"]),
        step_deg=float(values["step"]),
        fwhm_deg=float(values["fwhm"]),
        profile_eta=float(values["eta"]),
        include_elasticity=bool(values["include_elasticity"]),
        max_profile_points=int(values["max_profile_points"]),
        max_reflection_estimate=int(values["max_reflection_estimate"]),
        d_min_A=values["d_min_A"],  # type: ignore[arg-type]
        d_max_A=values["d_max_A"],  # type: ignore[arg-type]
        profile_model=values["profile_model"],  # type: ignore[arg-type]
        pattern_axis=values["pattern_axis"],  # type: ignore[arg-type]
        include_figures=bool(values["include_figures"]),
        figure_preset=figure_preset,
        export_lab_views=bool(values["export_lab_views"]),
        include_patterns=bool(values["include_patterns"]),
    )
    return settings


def resolve_cli_analysis(args: argparse.Namespace) -> ResolvedCliAnalysis:
    """Apply an optional preset, then replace only explicitly supplied options."""

    explicit = set(getattr(args, _EXPLICIT_ATTR, ()))
    values = _default_preset_values()
    preset_path = getattr(args, "preset", None)
    if preset_path:
        loaded = load_analysis_preset(preset_path)
        for field in ("radiation_value", "d_min_A", "d_max_A"):
            if loaded[field] == "":
                loaded[field] = None
        values.update(loaded)

    if "energy_keV" in explicit:
        values["input_mode"] = "energy"
        values["radiation_value"] = args.energy_keV
        if "source" in explicit:
            values["source_preset"] = args.source
    elif "wavelength_A" in explicit:
        values["input_mode"] = "wavelength"
        values["radiation_value"] = args.wavelength_A
        if "source" in explicit:
            values["source_preset"] = args.source
    elif "source" in explicit:
        values["source_preset"] = args.source
        if args.source == "Custom":
            if values["input_mode"] == "wavelength" or (
                values["input_mode"] == "source" and values["source_preset"] == "Custom"
            ):
                if values["radiation_value"] is None:
                    raise ValueError(
                        "Custom source requires --wavelength-A or --energy-keV. "
                        "For a saved energy-mode preset, pass --wavelength-A to switch units."
                    )
            else:
                raise ValueError(
                    "Custom source requires a wavelength; pass --wavelength-A. "
                    "An energy-mode preset cannot be reinterpreted as Angstrom."
                )
            values["input_mode"] = "source"
        else:
            values["input_mode"] = "source"
            values["radiation_value"] = None

    scalar_fields = {
        "two_theta_min": "two_theta_min",
        "two_theta_max": "two_theta_max",
        "step": "step",
        "fwhm": "fwhm",
        "eta": "eta",
        "max_profile_points": "max_profile_points",
        "max_reflection_estimate": "max_reflection_estimate",
        "d_min": "d_min_A",
        "d_max": "d_max_A",
        "profile_model": "profile_model",
        "pattern_axis": "pattern_axis",
    }
    for dest, field in scalar_fields.items():
        if dest in explicit:
            values[field] = getattr(args, dest)

    bool_fields = {
        "no_elasticity": ("include_elasticity", lambda value: not value),
        "no_lab_views": ("export_lab_views", lambda value: not value),
        "no_patterns": ("include_patterns", lambda value: not value),
        "figures": ("include_figures", bool),
        "no_excel": ("include_excel", lambda value: not value),
        "no_recursive": ("local_recursive", lambda value: not value),
    }
    for dest, (field, convert) in bool_fields.items():
        if dest in explicit:
            values[field] = convert(getattr(args, dest))

    figure_preset = getattr(args, "figure_preset", "publication")
    if "source" not in explicit and "energy_keV" not in explicit and "wavelength_A" not in explicit:
        if values["input_mode"] == "source" and values["source_preset"] == "Custom" and values["radiation_value"] is None:
            raise ValueError("Custom source preset is missing its wavelength value.")
    settings = _settings_from_values(values, figure_preset)
    return ResolvedCliAnalysis(
        settings=settings,
        include_excel=bool(values["include_excel"]),
        recursive=bool(values["local_recursive"]),
        preset_values=values,
    )


def save_cli_preset(
    path: str | Path,
    values: dict[str, object],
    *,
    overwrite: bool = False,
) -> Path:
    """Save a CLI preset while requiring explicit permission to replace files."""

    target = Path(path).expanduser()
    if target.is_symlink():
        raise ValueError(f"Refusing to write a preset through a symbolic link: {target}")
    resolved_parent = target.parent.resolve()
    if any((directory / "manifest.json").is_file() for directory in (resolved_parent, *resolved_parent.parents)):
        raise ValueError(f"Refusing to save an analysis preset inside a result bundle: {target}")
    if target.exists():
        if not target.is_file():
            raise ValueError(f"Preset target is not a regular file: {target}")
        if not overwrite:
            raise FileExistsError(f"Preset already exists: {target}. Pass --overwrite to replace it.")
    form_values = dict(values)
    for field in ("radiation_value", "d_min_A", "d_max_A"):
        if form_values[field] is None:
            form_values[field] = ""
    return save_analysis_preset(target, form_values)


def show_cli_preset(path: str | Path) -> dict[str, object]:
    """Load and strictly validate a preset for `preset show`."""

    values = load_analysis_preset(path)
    return {key: (None if value == "" else value) for key, value in values.items()}
