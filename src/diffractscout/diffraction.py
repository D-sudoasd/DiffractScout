"""Kinematic powder X-ray diffraction from CIF structures using Gemmi."""

from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
from typing import Iterable

import gemmi
import numpy as np

from .elasticity import SUPPORTED_DIRECTIONAL_FRAMES, young_modulus_hkl_normal_GPa
from .hkl import family_label_hkl, miller_bravais_i, uses_miller_bravais
from .models import AnalysisSettings, ElasticTensor, PhaseAnalysis, ReflectionRecord, StructureRecord
from .structure import structure_mass_metadata
from .utils import package_versions, utc_now_iso

ENERGY_WAVELENGTH_KEV_A = 12.398419843320026
X_RAY_SOURCES_A: dict[str, float | None] = {
    "Cu Ka": 1.5406,
    "Co Ka": 1.78897,
    "Fe Ka": 1.93604,
    "Mo Ka": 0.7093,
    "Ag Ka": 0.5594,
    "Custom": None,
}
CU_KA_WAVELENGTH_A = float(X_RAY_SOURCES_A["Cu Ka"])  # type: ignore[arg-type]
PROFILE_MODELS = frozenset({"pseudo_voigt", "gaussian", "lorentzian"})
PATTERN_AXES = frozenset({"two_theta", "d_spacing", "q", "g"})

SCIENTIFIC_BOUNDARY = (
    "The output is a kinematic theoretical powder reference. It is not phase identification, "
    "Rietveld refinement, quantitative phase analysis, absolute intensity calibration, or an "
    "instrument-resolution model. Preferred orientation, absorption, microstructure broadening, "
    "background, detector geometry, and experimental corrections are not inferred."
)

# Gemmi documents that reciprocal searches should use a slightly relaxed dmin
# because floating-point rounding can otherwise exclude a reflection exactly on
# the requested boundary. The exact 2theta interval is enforced after candidate
# generation, so this margin changes completeness without widening the output.
DMIN_SEARCH_RELATIVE_MARGIN = 1e-10
# A profile accumulation performs one vector addition per reflection and grid
# sample.  Keep that product bounded independently of the two input limits so
# a valid-but-large pair cannot allocate an impractical temporary workload.
MAX_PROFILE_WORK = 50_000_000
# A reciprocal search through a direct-cell metric this ill-conditioned is not
# numerically trustworthy.  Fail closed before handing it to Gemmi's native
# Miller-array builder.
MAX_DIRECT_METRIC_CONDITION = 1e8
# A tiny margin absorbs a final-bit rounding overshoot in lambda/(2d). Values
# farther above one are physically inaccessible and remain rejected.
BRAGG_ARGUMENT_TOLERANCE = 1e-12


def resolve_wavelength(settings: AnalysisSettings) -> tuple[float, float | None, str]:
    def validate_result(
        wavelength: float, energy: float | None, source: str
    ) -> tuple[float, float | None, str]:
        energy_valid = energy is None or (
            math.isfinite(float(energy)) and float(energy) > 0.0
        )
        if not math.isfinite(float(wavelength)) or float(wavelength) <= 0.0 or not energy_valid:
            raise ValueError(
                "Radiation input produced a non-finite or non-positive derived "
                f"wavelength/energy pair (wavelength_A={wavelength!r}, energy_keV={energy!r})."
            )
        return float(wavelength), float(energy) if energy is not None else None, source

    if settings.input_mode == "energy":
        if settings.energy_keV is None or not np.isfinite(settings.energy_keV) or settings.energy_keV <= 0:
            raise ValueError(
                "Radiation input energy_keV must be a finite positive number when "
                "input_mode='energy'."
            )
        energy = float(settings.energy_keV)
        return validate_result(ENERGY_WAVELENGTH_KEV_A / energy, energy, "energy_keV")
    if settings.input_mode == "wavelength":
        if settings.wavelength_A is None or not np.isfinite(settings.wavelength_A) or settings.wavelength_A <= 0:
            raise ValueError(
                "Radiation input wavelength_A must be a finite positive number when "
                "input_mode='wavelength'."
            )
        wavelength = float(settings.wavelength_A)
        return validate_result(
            wavelength, ENERGY_WAVELENGTH_KEV_A / wavelength, "wavelength_A"
        )
    if settings.input_mode != "source":
        raise ValueError(
            f"Unsupported input_mode: {settings.input_mode!r} (radiation input)."
        )
    if settings.source_preset not in X_RAY_SOURCES_A:
        choices = ", ".join(sorted(X_RAY_SOURCES_A))
        raise ValueError(
            f"Unknown X-ray source preset {settings.source_preset!r} in radiation input; "
            f"choose one of: {choices}."
        )
    preset = X_RAY_SOURCES_A[settings.source_preset]
    if preset is None:
        if settings.wavelength_A is None or not np.isfinite(settings.wavelength_A) or settings.wavelength_A <= 0:
            raise ValueError(
                "A finite positive wavelength_A is required for the Custom source "
                "preset (radiation input)."
            )
        wavelength = float(settings.wavelength_A)
        return validate_result(
            wavelength,
            ENERGY_WAVELENGTH_KEV_A / wavelength,
            "custom_source_wavelength",
        )
    wavelength = float(preset)
    return validate_result(
        wavelength,
        ENERGY_WAVELENGTH_KEV_A / wavelength,
        f"source_preset:{settings.source_preset}",
    )


def _bragg_argument(d_spacing_A: float, wavelength_A: float) -> float | None:
    if not np.isfinite(d_spacing_A) or not np.isfinite(wavelength_A):
        return None
    if d_spacing_A <= 0 or wavelength_A <= 0:
        return None
    argument = float(wavelength_A / (2.0 * d_spacing_A))
    if argument <= 0:
        return None
    if argument > 1.0:
        if argument <= 1.0 + BRAGG_ARGUMENT_TOLERANCE:
            return 1.0
        return None
    return argument


def two_theta_for_d(d_spacing_A: float, wavelength_A: float) -> float | None:
    """Bragg 2θ (degrees) for spacing d and wavelength λ, or None if inaccessible."""

    argument = _bragg_argument(d_spacing_A, wavelength_A)
    if argument is None:
        return None
    return float(np.rad2deg(2.0 * np.arcsin(argument)))


def _effective_two_theta_window(
    settings: AnalysisSettings,
    wavelength_A: float,
) -> tuple[float, float] | None:
    """Return the geometric intersection of the requested and *d* windows.

    The returned bounds are inclusive.  A one-point intersection is therefore
    meaningful and is retained; only ``lower > upper`` is empty.  A ``d_max``
    below the physical Bragg limit ``lambda / 2`` is always empty, even though
    it has no finite Bragg angle to use as an angular bound.
    """

    requested_min = float(settings.two_theta_min_deg)
    requested_max = float(settings.two_theta_max_deg)
    if settings.d_min_A is None and settings.d_max_A is None:
        return requested_min, requested_max

    physical_d_min = float(wavelength_A) / 2.0
    if settings.d_max_A is not None and float(settings.d_max_A) < physical_d_min:
        return None

    lower = requested_min
    upper = requested_max
    if settings.d_max_A is not None:
        d_max_angle = two_theta_for_d(float(settings.d_max_A), wavelength_A)
        if d_max_angle is None:
            return None
        lower = max(lower, d_max_angle)
    if settings.d_min_A is not None:
        d_min_angle = two_theta_for_d(float(settings.d_min_A), wavelength_A)
        if d_min_angle is not None:
            upper = min(upper, d_min_angle)
    if lower > upper:
        return None
    return lower, upper


def apply_d_range_to_settings(settings: AnalysisSettings) -> AnalysisSettings:
    """Narrow the 2θ window by intersection with Bragg angles from d bounds.

    Larger d maps to smaller 2θ. When ``d_min_A`` / ``d_max_A`` are set, the
    search window becomes the inclusive intersection of the user 2θ range with
    the Bragg interval implied by those d limits. Reflection-level d filtering
    is still applied after geometry. An empty intersection deliberately keeps
    the requested profile grid so callers can export an explicit empty-window
    result with separate effective-range metadata.
    """

    if settings.d_min_A is None and settings.d_max_A is None:
        return settings
    wavelength, _, _ = resolve_wavelength(settings)
    window = _effective_two_theta_window(settings, wavelength)
    if window is None:
        # Empty intersection: keep original angles; d filters will drop peaks.
        return settings
    tmin, tmax = window
    return replace(settings, two_theta_min_deg=tmin, two_theta_max_deg=tmax)


def _safe_inverse(value: float) -> float | None:
    if not np.isfinite(value) or value == 0.0:
        return None
    inverse = 1.0 / float(value)
    return float(inverse) if np.isfinite(inverse) else None


def validate_analysis_settings(settings: AnalysisSettings) -> None:
    """Validate run-wide diffraction settings before any input or provider work.

    This is intentionally structure-independent so callers can fail fast before
    copying local inputs or downloading provider records.
    """

    values = (
        settings.two_theta_min_deg,
        settings.two_theta_max_deg,
        settings.step_deg,
        settings.fwhm_deg,
        settings.profile_eta,
    )
    if not all(np.isfinite(value) for value in values):
        raise ValueError("Diffraction settings must be finite numbers.")
    if not (0 <= settings.two_theta_min_deg < settings.two_theta_max_deg <= 180):
        raise ValueError("2theta range must satisfy 0 <= minimum < maximum <= 180 degrees.")
    if settings.step_deg <= 0 or settings.fwhm_deg <= 0:
        raise ValueError("step_deg and fwhm_deg must be positive.")
    if not 0 <= settings.profile_eta <= 1:
        raise ValueError("profile_eta must lie in [0, 1].")
    if settings.profile_model not in PROFILE_MODELS:
        raise ValueError(
            f"Unknown profile_model {settings.profile_model!r}; "
            f"choose one of: {', '.join(sorted(PROFILE_MODELS))}."
        )
    if settings.pattern_axis not in PATTERN_AXES:
        raise ValueError(
            f"Unknown pattern_axis {settings.pattern_axis!r}; "
            f"choose one of: {', '.join(sorted(PATTERN_AXES))}."
        )
    for name in ("d_min_A", "d_max_A"):
        value = getattr(settings, name)
        if value is None:
            continue
        if not np.isfinite(value) or float(value) <= 0:
            raise ValueError(f"{name} must be a finite positive number when set.")
    if (
        settings.d_min_A is not None
        and settings.d_max_A is not None
        and float(settings.d_min_A) > float(settings.d_max_A)
    ):
        raise ValueError("d_min_A must be <= d_max_A when both are set.")
    for name in ("max_profile_points", "max_reflection_estimate"):
        value = getattr(settings, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer.")
    if settings.input_mode == "energy" and settings.wavelength_A is not None:
        raise ValueError(
            "wavelength_A is inactive when input_mode='energy'; clear it or use "
            "input_mode='wavelength'."
        )
    if settings.input_mode == "wavelength" and settings.energy_keV is not None:
        raise ValueError(
            "energy_keV is inactive when input_mode='wavelength'; clear it or use "
            "input_mode='energy'."
        )
    if settings.input_mode == "source":
        if settings.source_preset == "Custom" and settings.energy_keV is not None:
            raise ValueError(
                "energy_keV is inactive for the Custom source; provide wavelength_A instead."
            )
        if settings.source_preset != "Custom" and (
            settings.wavelength_A is not None or settings.energy_keV is not None
        ):
            raise ValueError(
                "Numeric radiation fields are inactive for a built-in source preset; "
                "clear wavelength_A and energy_keV."
            )
    # Validate the mode-specific radiation value as part of the same preflight.
    resolve_wavelength(settings)
    if settings.include_figures:
        from .plotting import FIGURE_EXPORT_PRESETS

        preset = settings.figure_preset or "publication"
        if preset not in FIGURE_EXPORT_PRESETS:
            raise ValueError(
                f"Unknown figure export preset: {preset}. Valid presets: "
                + ", ".join(sorted(FIGURE_EXPORT_PRESETS))
            )


def _profile_point_count(settings: AnalysisSettings) -> int:
    span = settings.two_theta_max_deg - settings.two_theta_min_deg
    return int(math.ceil(span / settings.step_deg)) + 1


def _reflection_search_estimate(cell: gemmi.UnitCell, d_min_A: float) -> int:
    """Return a conservative integer box bound for Gemmi's Miller search.

    For a reciprocal quadratic form ``q(h) = hᵀ G* h`` and radius
    ``R = 1 / d_min``, minimizing over the other two indices gives
    ``|h_i| <= R * sqrt(G_ii)`` because ``(G*)⁻¹ = G`` is the direct-cell
    metric.  The product of the three inclusive integer intervals therefore
    bounds every reciprocal-lattice candidate before native array generation.
    """

    if not np.isfinite(d_min_A) or d_min_A <= 0:
        raise ValueError("Calculated d_min must be finite and positive.")
    try:
        direct_metric = np.asarray(cell.metric_tensor().as_mat33(), dtype=float)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Unit-cell direct metric could not be evaluated safely.") from exc
    if direct_metric.shape != (3, 3) or not np.all(np.isfinite(direct_metric)):
        raise ValueError("Unit-cell direct metric is non-finite.")
    try:
        eigenvalues = np.linalg.eigvalsh(direct_metric)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Unit-cell direct metric could not be evaluated safely.") from exc
    smallest = float(np.min(eigenvalues))
    largest = float(np.max(eigenvalues))
    if smallest <= 0.0 or largest <= 0.0:
        raise ValueError("Unit-cell direct metric is not positive definite.")
    condition_number = largest / smallest
    if not np.isfinite(condition_number) or condition_number > MAX_DIRECT_METRIC_CONDITION:
        raise ValueError(
            "Unit-cell direct metric is near-singular; reciprocal reflection search was stopped "
            f"(condition number={condition_number:.3g})."
        )
    radius = 1.0 / float(d_min_A)
    limits = radius * np.sqrt(np.diag(direct_metric))
    if not np.all(np.isfinite(limits)) or np.any(limits < 0.0):
        raise ValueError("Unit-cell reciprocal index bounds are non-finite.")
    counts = [
        2 * math.ceil(float(np.nextafter(limit, math.inf))) + 1
        for limit in limits
    ]
    return int(math.prod(counts))


def _equivalent_hkls(space_group: gemmi.SpaceGroup, hkl: Iterable[int]) -> set[tuple[int, int, int]]:
    base = tuple(int(value) for value in hkl)
    equivalents: set[tuple[int, int, int]] = set()
    for operation in space_group.operations().sym_ops:
        transformed = tuple(int(value) for value in operation.apply_to_hkl(base))
        equivalents.add(transformed)
        equivalents.add(tuple(-value for value in transformed))
    return equivalents


def _first_nonzero_positive(hkl: tuple[int, int, int]) -> tuple[int, int, int]:
    for value in hkl:
        if value < 0:
            return tuple(-item for item in hkl)
        if value > 0:
            return hkl
    return hkl


def canonical_hkl_family(space_group: gemmi.SpaceGroup, hkl: Iterable[int]) -> tuple[tuple[int, int, int], int]:
    equivalents = {_first_nonzero_positive(item) for item in _equivalent_hkls(space_group, hkl)}

    def key(item: tuple[int, int, int]) -> tuple[int, int, int, int, int, int, int]:
        # Prefer non-negative, conventional-looking representatives with large leading indices.
        return (
            sum(value < 0 for value in item),
            -item[0],
            -item[1],
            -item[2],
            -abs(item[0]),
            -abs(item[1]),
            -abs(item[2]),
        )

    representative = min(equivalents, key=key)
    return representative, len(_equivalent_hkls(space_group, hkl))


def _lp_factor(theta_rad: float) -> float | None:
    denominator = np.sin(theta_rad) ** 2 * np.cos(theta_rad)
    if abs(float(denominator)) < 1e-14:
        return None
    return float((1.0 + np.cos(2.0 * theta_rad) ** 2) / denominator)


def _gaussian(grid: np.ndarray, center: float, fwhm: float) -> np.ndarray:
    sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    return np.exp(-0.5 * ((grid - center) / sigma) ** 2)


def _lorentzian(grid: np.ndarray, center: float, fwhm: float) -> np.ndarray:
    gamma = fwhm / 2.0
    return gamma**2 / ((grid - center) ** 2 + gamma**2)


def _pseudo_voigt(grid: np.ndarray, center: float, fwhm: float, eta: float) -> np.ndarray:
    return eta * _lorentzian(grid, center, fwhm) + (1.0 - eta) * _gaussian(grid, center, fwhm)


def _peak_profile(
    grid: np.ndarray,
    center: float,
    fwhm: float,
    settings: AnalysisSettings,
) -> np.ndarray:
    if settings.profile_model == "gaussian":
        return _gaussian(grid, center, fwhm)
    if settings.profile_model == "lorentzian":
        return _lorentzian(grid, center, fwhm)
    return _pseudo_voigt(grid, center, fwhm, settings.profile_eta)


def _rank_desc(values: list[float]) -> list[int]:
    ordered = sorted(
        enumerate(values),
        key=lambda pair: pair[1] if np.isfinite(pair[1]) else float("-inf"),
        reverse=True,
    )
    result = [0] * len(values)
    for rank, (index, _value) in enumerate(ordered, start=1):
        result[index] = rank
    return result


def _elastic_annotation(
    tensor: ElasticTensor | None,
    structure: StructureRecord,
    hkl: tuple[int, int, int],
    *,
    requested: bool,
) -> tuple[float | None, str, str]:
    if not requested:
        return None, "not_requested", "Elasticity evaluation was disabled for this run."
    if tensor is None:
        return None, "not_available", "No paired numerical 6x6 elastic tensor was found."
    if tensor.status == "invalid":
        return None, "invalid", " | ".join(tensor.warnings)
    if tensor.status == "frame_transform_required":
        note = (
            "A coordinate-frame transform is required before hkl-normal modulus calculation."
        )
        return None, "frame_transform_required", " | ".join(
            dict.fromkeys([*tensor.warnings, note])
        )
    if tensor.coordinate_frame not in SUPPORTED_DIRECTIONAL_FRAMES:
        note = (
            f"Tensor frame '{tensor.coordinate_frame}' is not coupled to the CIF Cartesian frame; "
            "an explicit rotation is required before hkl-normal modulus calculation."
        )
        return None, "frame_transform_required", " | ".join(dict.fromkeys([*tensor.warnings, note]))
    modulus = young_modulus_hkl_normal_GPa(tensor, structure.small_structure.cell, hkl)
    note_parts = [*tensor.warnings]
    if tensor.coordinate_frame == "materials_project_conventional_cif_cartesian":
        note_parts.append(
            "Cij uses the Materials Project raw/POSCAR tensor frame; no verified transform to "
            "the emitted CIF Cartesian frame is available."
        )
    elif tensor.coordinate_frame != "crystal_cartesian_from_cif_lattice":
        note_parts.append(f"Coordinate-frame declaration: {tensor.coordinate_frame}.")
    if modulus is None:
        note_parts.append("The hkl-normal modulus could not be evaluated.")
    return modulus, tensor.status, " | ".join(dict.fromkeys(note_parts))


def simulate_powder_pattern(
    structure: StructureRecord,
    settings: AnalysisSettings,
    *,
    elastic_tensor: ElasticTensor | None = None,
) -> PhaseAnalysis:
    validate_analysis_settings(settings)
    wavelength, energy, wavelength_source = resolve_wavelength(settings)
    requested_two_theta_range = [
        float(settings.two_theta_min_deg),
        float(settings.two_theta_max_deg),
    ]
    effective_window = _effective_two_theta_window(settings, wavelength)
    effective_window_empty = (
        settings.d_min_A is not None or settings.d_max_A is not None
    ) and effective_window is None
    # Narrow 2θ by Bragg intersection with optional d bounds, then filter by d.
    settings = apply_d_range_to_settings(settings)
    point_count = _profile_point_count(settings)
    if point_count > settings.max_profile_points:
        raise ValueError(
            f"Profile grid would contain {point_count:,} points, exceeding max_profile_points="
            f"{settings.max_profile_points:,}. Increase step_deg or the explicit safety limit."
        )

    theta_max = np.deg2rad(settings.two_theta_max_deg / 2.0)
    d_min = wavelength / (2.0 * np.sin(theta_max))
    d_min_search = min(
        float(np.nextafter(d_min, 0.0)),
        float(d_min) * (1.0 - DMIN_SEARCH_RELATIVE_MARGIN),
    )
    # If user d_min is stricter (larger) than Bragg d_min, still search to Bragg
    # d_min but filter reflections; if user d_min is smaller, Bragg already limits.
    cell = structure.small_structure.cell
    cell_volume = float(cell.volume)
    if effective_window_empty:
        # The geometric intersection is authoritative. Do not let the
        # reflection-level comparison tolerances admit a boundary reflection
        # into a window already classified as empty (notably just below
        # d=lambda/2, where 2theta=180 degrees makes the LP factor singular).
        reflection_estimate = 0
        miller_array = []
    else:
        reflection_estimate = _reflection_search_estimate(cell, float(d_min_search))
        if reflection_estimate > settings.max_reflection_estimate:
            raise ValueError(
                f"Reciprocal search is estimated at {reflection_estimate:,} points, exceeding "
                f"max_reflection_estimate={settings.max_reflection_estimate:,}. Reduce 2theta_max, "
                "use a longer wavelength, or raise the explicit safety limit after reviewing memory use."
            )
        miller_array = gemmi.make_miller_array(
            cell,
            structure.space_group_object,
            float(d_min_search),
            0.0,
            True,
        )
        if len(miller_array) > settings.max_reflection_estimate:
            raise ValueError(
                f"Gemmi generated {len(miller_array):,} reciprocal candidates, exceeding "
                f"max_reflection_estimate={settings.max_reflection_estimate:,}."
            )
    calculator = gemmi.StructureFactorCalculatorX(structure.small_structure.cell)
    four_index = uses_miller_bravais(structure.space_group_object)
    reflections: list[ReflectionRecord] = []

    for raw_hkl in miller_array:
        hkl = tuple(int(value) for value in raw_hkl)
        if hkl == (0, 0, 0) or structure.space_group_object.operations().is_systematically_absent(hkl):
            continue
        d_spacing = float(structure.small_structure.cell.calculate_d(hkl))
        if not np.isfinite(d_spacing) or d_spacing <= 0:
            continue
        if settings.d_min_A is not None and d_spacing < float(settings.d_min_A) - 1e-12:
            continue
        if settings.d_max_A is not None and d_spacing > float(settings.d_max_A) + 1e-12:
            continue
        argument = _bragg_argument(d_spacing, wavelength)
        if argument is None:
            continue
        theta_rad = float(np.arcsin(argument))
        two_theta = float(np.rad2deg(2.0 * theta_rad))
        if two_theta < settings.two_theta_min_deg - 1e-9 or two_theta > settings.two_theta_max_deg + 1e-9:
            continue

        representative, multiplicity = canonical_hkl_family(structure.space_group_object, hkl)
        sf_structure = structure.structure_factor_structure or structure.small_structure
        structure_factor = calculator.calculate_sf_from_small_structure(sf_structure, hkl)
        structure_factor_sq = float(abs(structure_factor) ** 2)
        no_lp = float(multiplicity * structure_factor_sq)
        lp = _lp_factor(theta_rad)
        if lp is None:
            raise ValueError(
                "Lorentz-polarization factor is singular for a reflection at "
                "2theta=180 degrees; reduce two_theta_max_deg below 180."
            )
        with_lp = float(no_lp * lp) if np.isfinite(lp) else float("nan")
        if not np.isfinite(with_lp):
            raise ValueError(
                "Lorentz-polarization intensity became non-finite for a reflection; "
                "the profile was not exported."
            )
        q_invA = float(2.0 * np.pi / d_spacing)
        g_invA = float(1.0 / d_spacing)
        r_with_lp = float(with_lp / cell_volume**2) if cell_volume > 0 and np.isfinite(with_lp) else float("nan")
        r_no_lp = float(no_lp / cell_volume**2) if cell_volume > 0 else float("nan")
        modulus, elastic_status, elastic_note = _elastic_annotation(
            elastic_tensor if settings.include_elasticity else None,
            structure,
            representative,
            requested=settings.include_elasticity,
        )
        sin_theta = float(np.sin(theta_rad))
        cos_theta = float(np.cos(theta_rad))
        sin_over_lambda = float(sin_theta / wavelength) if wavelength > 0 else float("nan")
        sin2_over_lambda2 = float(sin_over_lambda**2) if np.isfinite(sin_over_lambda) else float("nan")
        mean_sf_sq = structure_factor_sq
        mean_sf_abs = float(math.sqrt(mean_sf_sq)) if mean_sf_sq >= 0 and np.isfinite(mean_sf_sq) else float("nan")
        index_i = miller_bravais_i(representative[0], representative[1]) if four_index else None
        cu_ka_two_theta = two_theta_for_d(d_spacing, CU_KA_WAVELENGTH_A)
        reflections.append(
            ReflectionRecord(
                h=representative[0],
                k=representative[1],
                l=representative[2],
                family_label=family_label_hkl(
                    representative[0],
                    representative[1],
                    representative[2],
                    use_four_index=four_index,
                    i=index_i,
                ),
                multiplicity=multiplicity,
                d_spacing_A=d_spacing,
                theta_deg=float(np.rad2deg(theta_rad)),
                two_theta_deg=two_theta,
                q_invA=q_invA,
                g_invA=g_invA,
                structure_factor_sq=structure_factor_sq,
                intensity_no_lp=no_lp,
                lp_factor=lp,
                intensity_with_lp=with_lp,
                normalized_intensity=0.0,
                material_scattering_factor_R_hkl=r_with_lp,
                material_scattering_factor_R_hkl_no_lp=r_no_lp,
                young_modulus_hkl_normal_GPa=modulus,
                elastic_status=elastic_status,
                elastic_note=elastic_note,
                i=index_i,
                two_theta_cu_ka_deg=(
                    float(cu_ka_two_theta) if cu_ka_two_theta is not None else None
                ),
                inverse_R_hkl=_safe_inverse(r_with_lp),
                inverse_R_hkl_no_lp=_safe_inverse(r_no_lp),
                sin_theta=sin_theta,
                cos_theta=cos_theta,
                sin_theta_over_lambda=sin_over_lambda,
                sin2_theta_over_lambda2=sin2_over_lambda2,
                mean_structure_factor_sq_per_multiplicity=mean_sf_sq,
                mean_structure_factor_abs_per_multiplicity=mean_sf_abs,
                r_hkl_model_note="R_hkl := I / V_cell^2 (project-defined; not a residual factor)",
            )
        )

    reflections.sort(key=lambda item: (item.two_theta_deg, item.h, item.k, item.l))

    # Mark coincident families that share the same peak position within 1e-8 deg.
    if reflections:
        groups: dict[float, list[int]] = {}
        for index, item in enumerate(reflections):
            key = round(item.two_theta_deg, 8)
            groups.setdefault(key, []).append(index)
        for indices in groups.values():
            count = len(indices)
            if count <= 1:
                continue
            for index in indices:
                reflections[index] = replace(
                    reflections[index],
                    is_multi_family_peak=True,
                    coincident_hkl_family_count=count,
                )

    finite_intensities = [item.intensity_with_lp for item in reflections if np.isfinite(item.intensity_with_lp)]
    maximum = max(finite_intensities) if finite_intensities else 0.0
    intensity_ranks = _rank_desc([item.intensity_with_lp for item in reflections])
    r_ranks = _rank_desc([item.material_scattering_factor_R_hkl for item in reflections])
    r_no_lp_ranks = _rank_desc([item.material_scattering_factor_R_hkl_no_lp for item in reflections])
    finite_r = [
        item.material_scattering_factor_R_hkl
        for item in reflections
        if np.isfinite(item.material_scattering_factor_R_hkl)
    ]
    finite_r_no_lp = [
        item.material_scattering_factor_R_hkl_no_lp
        for item in reflections
        if np.isfinite(item.material_scattering_factor_R_hkl_no_lp)
    ]
    max_r = max(finite_r) if finite_r else 0.0
    max_r_no_lp = max(finite_r_no_lp) if finite_r_no_lp else 0.0
    reflections = [
        replace(
            item,
            normalized_intensity=(100.0 * item.intensity_with_lp / maximum)
            if maximum > 0 and np.isfinite(item.intensity_with_lp)
            else 0.0,
            rank_by_intensity=intensity_ranks[index],
            rank_by_R_hkl=r_ranks[index],
            rank_by_R_hkl_no_lp=r_no_lp_ranks[index],
            phase_relative_R_hkl_pct=(
                100.0 * item.material_scattering_factor_R_hkl / max_r
                if max_r > 0 and np.isfinite(item.material_scattering_factor_R_hkl)
                else 0.0
            ),
            phase_relative_R_hkl_no_lp_pct=(
                100.0 * item.material_scattering_factor_R_hkl_no_lp / max_r_no_lp
                if max_r_no_lp > 0 and np.isfinite(item.material_scattering_factor_R_hkl_no_lp)
                else 0.0
            ),
        )
        for index, item in enumerate(reflections)
    ]

    grid = settings.two_theta_min_deg + np.arange(point_count, dtype=float) * settings.step_deg
    # Do not use a half-step tolerance here: it can emit samples above the
    # user-requested upper bound when the span is not an integer number of
    # steps.
    grid = grid[grid <= settings.two_theta_max_deg]
    sampled_two_theta_range = (
        [float(grid[0]), float(grid[-1])] if grid.size else None
    )
    profile_work = len(reflections) * int(grid.size)
    if profile_work > MAX_PROFILE_WORK:
        raise ValueError(
            "Reflection-by-profile accumulation would require "
            f"{profile_work:,} sample operations, exceeding MAX_PROFILE_WORK="
            f"{MAX_PROFILE_WORK:,}. Reduce the 2theta range/step or review the "
            "explicit resource limits."
        )
    profile = np.zeros_like(grid)
    for item in reflections:
        if np.isfinite(item.intensity_with_lp):
            profile += item.intensity_with_lp * _peak_profile(
                grid,
                item.two_theta_deg,
                settings.fwhm_deg,
                settings,
            )
    if profile.size and float(np.max(profile)) > 0:
        profile = profile / float(np.max(profile)) * 100.0

    warnings = list(structure.warnings)
    if effective_window_empty:
        warnings.append(
            "Requested 2theta and d-spacing filter do not overlap; "
            "the emitted profile grid is retained for compatibility and the "
            "effective window is empty."
        )
    elif not reflections:
        warnings.append("No theoretical reflections fall inside the selected 2theta window.")
    if settings.step_deg > 0.05:
        warnings.append("The profile grid is coarse; use step_deg <= 0.02 for peak-position plots.")
    active_elastic_tensor = elastic_tensor if settings.include_elasticity else None
    if active_elastic_tensor is not None:
        warnings.extend(item for item in active_elastic_tensor.warnings if item not in warnings)

    mass_meta = structure_mass_metadata(structure)
    metadata = {
        "generated_at_utc": utc_now_iso(),
        "cif_sha256": structure.cif_sha256,
        "wavelength_A": wavelength,
        "energy_keV": energy,
        "wavelength_source": wavelength_source,
        "two_theta_range_deg": [settings.two_theta_min_deg, settings.two_theta_max_deg],
        "profile_sampled_two_theta_range_deg": sampled_two_theta_range,
        "requested_two_theta_range_deg": requested_two_theta_range,
        "effective_two_theta_range_deg": (
            list(effective_window) if effective_window is not None else None
        ),
        "effective_window_empty": effective_window_empty,
        "step_deg": settings.step_deg,
        "fwhm_deg": settings.fwhm_deg,
        "profile_model": settings.profile_model,
        "profile_eta": settings.profile_eta,
        "pattern_axis": settings.pattern_axis,
        "profile_point_count": int(grid.size),
        "max_profile_points": settings.max_profile_points,
        # Geometric Bragg d-min from the configured analysis upper bound. This
        # governs the reflection search and is distinct from both the last
        # sampled profile coordinate and the optional filter d_min_A below.
        "geometric_d_min_A": float(d_min),
        "d_min_A": float(d_min),
        "d_min_search_A": float(d_min_search),
        "d_min_search_relative_margin": DMIN_SEARCH_RELATIVE_MARGIN,
        "filter_d_min_A": settings.d_min_A,
        "filter_d_max_A": settings.d_max_A,
        "d_max_A": settings.d_max_A,
        "cell_volume_A3": mass_meta["cell_volume_A3"],
        "formula_weight_g_mol": mass_meta["formula_weight_g_mol"],
        "density_g_cm3": mass_meta["density_g_cm3"],
        "cu_ka_wavelength_A": CU_KA_WAVELENGTH_A,
        "reflection_search_estimate": reflection_estimate,
        "miller_candidates_generated": len(miller_array),
        "max_reflection_estimate": settings.max_reflection_estimate,
        "intensity_model": "multiplicity * |F_xray|^2 * Lorentz-polarization",
        "volume_normalized_intensity_with_lp_definition": "I_with_LP / V_cell^2",
        "volume_normalized_intensity_no_lp_definition": "I_no_LP / V_cell^2",
        "legacy_R_hkl_alias_note": (
            "R_hkl field names are compatibility aliases for project-defined volume-normalized "
            "theoretical intensities; they are not crystallographic residual factors or standardized QPA coefficients."
        ),
        "q_definition": "2*pi/d = 4*pi*sin(theta)/lambda",
        "elasticity_requested": settings.include_elasticity,
        "include_figures": settings.include_figures,
        "figure_preset": settings.figure_preset,
        "export_lab_views": settings.export_lab_views,
        "include_patterns": settings.include_patterns,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "software_versions": package_versions(),
    }
    return PhaseAnalysis(
        phase_name=Path(structure.cif_path).stem,
        structure=structure,
        reflections=reflections,
        two_theta_grid=grid,
        intensity_profile=profile,
        wavelength_A=wavelength,
        energy_keV=energy,
        wavelength_source=wavelength_source,
        elastic_tensor=active_elastic_tensor,
        warnings=list(dict.fromkeys(warnings)),
        metadata=metadata,
    )
