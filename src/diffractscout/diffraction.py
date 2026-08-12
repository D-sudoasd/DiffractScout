"""Kinematic powder X-ray diffraction from CIF structures using Gemmi."""

from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
from typing import Iterable

import gemmi
import numpy as np

from .elasticity import SUPPORTED_DIRECTIONAL_FRAMES, young_modulus_hkl_normal_GPa
from .models import AnalysisSettings, ElasticTensor, PhaseAnalysis, ReflectionRecord, StructureRecord
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


def resolve_wavelength(settings: AnalysisSettings) -> tuple[float, float | None, str]:
    if settings.input_mode == "energy":
        if settings.energy_keV is None or not np.isfinite(settings.energy_keV) or settings.energy_keV <= 0:
            raise ValueError("energy_keV must be a finite positive number when input_mode='energy'.")
        energy = float(settings.energy_keV)
        return ENERGY_WAVELENGTH_KEV_A / energy, energy, "energy_keV"
    if settings.input_mode == "wavelength":
        if settings.wavelength_A is None or not np.isfinite(settings.wavelength_A) or settings.wavelength_A <= 0:
            raise ValueError("wavelength_A must be a finite positive number when input_mode='wavelength'.")
        wavelength = float(settings.wavelength_A)
        return wavelength, ENERGY_WAVELENGTH_KEV_A / wavelength, "wavelength_A"
    if settings.input_mode != "source":
        raise ValueError(f"Unsupported input_mode: {settings.input_mode!r}.")
    if settings.source_preset not in X_RAY_SOURCES_A:
        choices = ", ".join(sorted(X_RAY_SOURCES_A))
        raise ValueError(f"Unknown X-ray source preset {settings.source_preset!r}; choose one of: {choices}.")
    preset = X_RAY_SOURCES_A[settings.source_preset]
    if preset is None:
        if settings.wavelength_A is None or not np.isfinite(settings.wavelength_A) or settings.wavelength_A <= 0:
            raise ValueError("A finite positive wavelength_A is required for the Custom source preset.")
        wavelength = float(settings.wavelength_A)
        return wavelength, ENERGY_WAVELENGTH_KEV_A / wavelength, "custom_source_wavelength"
    wavelength = float(preset)
    return wavelength, ENERGY_WAVELENGTH_KEV_A / wavelength, f"source_preset:{settings.source_preset}"


def _validate_settings(settings: AnalysisSettings) -> None:
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
    for name in ("max_profile_points", "max_reflection_estimate"):
        value = getattr(settings, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer.")


def _profile_point_count(settings: AnalysisSettings) -> int:
    span = settings.two_theta_max_deg - settings.two_theta_min_deg
    return int(math.ceil(span / settings.step_deg)) + 1


def _reflection_search_estimate(cell_volume_A3: float, d_min_A: float) -> int:
    """Estimate reciprocal-lattice points inside the 1/d sphere.

    Reciprocal-space point density is the direct-cell volume when reciprocal
    vectors are expressed without the 2π factor. The estimate intentionally
    counts both Friedel mates and therefore serves as a conservative resource
    guard, not as a crystallographic reflection count.
    """

    if not np.isfinite(cell_volume_A3) or cell_volume_A3 <= 0:
        raise ValueError("Unit-cell volume must be finite and positive.")
    if not np.isfinite(d_min_A) or d_min_A <= 0:
        raise ValueError("Calculated d_min must be finite and positive.")
    return int(math.ceil((4.0 * math.pi / 3.0) * cell_volume_A3 / d_min_A**3))


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


def _lp_factor(theta_rad: float) -> float:
    denominator = np.sin(theta_rad) ** 2 * np.cos(theta_rad)
    if abs(float(denominator)) < 1e-14:
        return float("nan")
    return float((1.0 + np.cos(2.0 * theta_rad) ** 2) / denominator)


def _gaussian(grid: np.ndarray, center: float, fwhm: float) -> np.ndarray:
    sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    return np.exp(-0.5 * ((grid - center) / sigma) ** 2)


def _lorentzian(grid: np.ndarray, center: float, fwhm: float) -> np.ndarray:
    gamma = fwhm / 2.0
    return gamma**2 / ((grid - center) ** 2 + gamma**2)


def _pseudo_voigt(grid: np.ndarray, center: float, fwhm: float, eta: float) -> np.ndarray:
    return eta * _lorentzian(grid, center, fwhm) + (1.0 - eta) * _gaussian(grid, center, fwhm)


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
    if tensor.coordinate_frame not in SUPPORTED_DIRECTIONAL_FRAMES:
        note = (
            f"Tensor frame '{tensor.coordinate_frame}' is not coupled to the CIF Cartesian frame; "
            "an explicit rotation is required before hkl-normal modulus calculation."
        )
        return None, "frame_unverified", " | ".join(dict.fromkeys([*tensor.warnings, note]))
    modulus = young_modulus_hkl_normal_GPa(tensor, structure.small_structure.cell, hkl)
    note_parts = [*tensor.warnings]
    if tensor.coordinate_frame == "materials_project_conventional_cif_cartesian":
        note_parts.append(
            "Cij uses the Materials Project conventional-CIF Cartesian frame documented for the raw tensor."
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
    _validate_settings(settings)
    wavelength, energy, wavelength_source = resolve_wavelength(settings)
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
    cell_volume = float(structure.small_structure.cell.volume)
    reflection_estimate = _reflection_search_estimate(cell_volume, float(d_min_search))
    if reflection_estimate > settings.max_reflection_estimate:
        raise ValueError(
            f"Reciprocal search is estimated at {reflection_estimate:,} points, exceeding "
            f"max_reflection_estimate={settings.max_reflection_estimate:,}. Reduce 2theta_max, "
            "use a longer wavelength, or raise the explicit safety limit after reviewing memory use."
        )
    miller_array = gemmi.make_miller_array(
        structure.small_structure.cell,
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
    reflections: list[ReflectionRecord] = []

    for raw_hkl in miller_array:
        hkl = tuple(int(value) for value in raw_hkl)
        if hkl == (0, 0, 0) or structure.space_group_object.operations().is_systematically_absent(hkl):
            continue
        d_spacing = float(structure.small_structure.cell.calculate_d(hkl))
        if not np.isfinite(d_spacing) or d_spacing <= 0:
            continue
        argument = wavelength / (2.0 * d_spacing)
        if argument <= 0 or argument > 1:
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
        with_lp = float(no_lp * lp) if np.isfinite(lp) else float("nan")
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
        reflections.append(
            ReflectionRecord(
                h=representative[0],
                k=representative[1],
                l=representative[2],
                family_label="{" + " ".join(str(value) for value in representative) + "}",
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
            )
        )

    reflections.sort(key=lambda item: (item.two_theta_deg, item.h, item.k, item.l))
    finite_intensities = [item.intensity_with_lp for item in reflections if np.isfinite(item.intensity_with_lp)]
    maximum = max(finite_intensities) if finite_intensities else 0.0
    intensity_ranks = _rank_desc([item.intensity_with_lp for item in reflections])
    r_ranks = _rank_desc([item.material_scattering_factor_R_hkl for item in reflections])
    r_no_lp_ranks = _rank_desc([item.material_scattering_factor_R_hkl_no_lp for item in reflections])
    reflections = [
        replace(
            item,
            normalized_intensity=(100.0 * item.intensity_with_lp / maximum)
            if maximum > 0 and np.isfinite(item.intensity_with_lp)
            else 0.0,
            rank_by_intensity=intensity_ranks[index],
            rank_by_R_hkl=r_ranks[index],
            rank_by_R_hkl_no_lp=r_no_lp_ranks[index],
        )
        for index, item in enumerate(reflections)
    ]

    grid = settings.two_theta_min_deg + np.arange(point_count, dtype=float) * settings.step_deg
    grid = grid[grid <= settings.two_theta_max_deg + settings.step_deg * 0.5]
    profile = np.zeros_like(grid)
    for item in reflections:
        if np.isfinite(item.intensity_with_lp):
            profile += item.intensity_with_lp * _pseudo_voigt(
                grid,
                item.two_theta_deg,
                settings.fwhm_deg,
                settings.profile_eta,
            )
    if profile.size and float(np.max(profile)) > 0:
        profile = profile / float(np.max(profile)) * 100.0

    warnings = list(structure.warnings)
    if not reflections:
        warnings.append("No theoretical reflections fall inside the selected 2theta window.")
    if settings.step_deg > 0.05:
        warnings.append("The profile grid is coarse; use step_deg <= 0.02 for peak-position plots.")
    active_elastic_tensor = elastic_tensor if settings.include_elasticity else None
    if active_elastic_tensor is not None:
        warnings.extend(item for item in active_elastic_tensor.warnings if item not in warnings)

    metadata = {
        "generated_at_utc": utc_now_iso(),
        "cif_sha256": structure.cif_sha256,
        "wavelength_A": wavelength,
        "energy_keV": energy,
        "wavelength_source": wavelength_source,
        "two_theta_range_deg": [settings.two_theta_min_deg, settings.two_theta_max_deg],
        "step_deg": settings.step_deg,
        "fwhm_deg": settings.fwhm_deg,
        "profile_model": "pseudo_voigt",
        "profile_eta": settings.profile_eta,
        "profile_point_count": int(grid.size),
        "max_profile_points": settings.max_profile_points,
        "d_min_A": float(d_min),
        "d_min_search_A": float(d_min_search),
        "d_min_search_relative_margin": DMIN_SEARCH_RELATIVE_MARGIN,
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
