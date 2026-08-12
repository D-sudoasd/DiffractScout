from pathlib import Path

import gemmi
import numpy as np
import pytest

from diffractscout.diffraction import simulate_powder_pattern
from diffractscout.elasticity import discover_elastic_tensor
from diffractscout.models import AnalysisSettings
from diffractscout.structure import load_structure


def test_fcc_reflections_and_systematic_absences(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    tensor = discover_elastic_tensor(structure.cif_path)
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(two_theta_min_deg=5, two_theta_max_deg=100),
        elastic_tensor=tensor,
    )
    hkls = [reflection.hkl for reflection in result.reflections]
    assert hkls[:5] == [(1, 1, 1), (2, 0, 0), (2, 2, 0), (3, 1, 1), (2, 2, 2)]
    assert (1, 0, 0) not in hkls
    assert (1, 1, 0) not in hkls
    assert result.reflections[0].multiplicity == 8
    assert result.reflections[1].multiplicity == 6


def test_peak_geometry_and_normalization(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(two_theta_min_deg=5, two_theta_max_deg=100),
    )
    first = result.reflections[0]
    assert first.d_spacing_A == pytest.approx(4 / np.sqrt(3), rel=1e-12)
    assert first.q_invA == pytest.approx(2 * np.pi / first.d_spacing_A, rel=1e-12)
    assert max(item.normalized_intensity for item in result.reflections) == pytest.approx(100.0)
    assert float(np.max(result.intensity_profile)) == pytest.approx(100.0)


def test_fcc_structure_factor_uses_crystallographic_occupancy(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(two_theta_min_deg=5, two_theta_max_deg=100),
    )
    reflection_111 = result.reflections[0]
    # Monoatomic FCC: F_111 = 4 f_Al. Gemmi IT92 uses (sin(theta)/lambda)^2 = 1/(4d^2).
    form_factor = gemmi.Element("Al").it92.calculate_sf(
        1.0 / (4.0 * reflection_111.d_spacing_A**2)
    )
    assert reflection_111.structure_factor_sq == pytest.approx((4.0 * form_factor) ** 2, rel=1e-7)


def test_profile_resource_guard_rejects_extreme_grid(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    with pytest.raises(ValueError, match="Profile grid would contain"):
        simulate_powder_pattern(
            structure,
            AnalysisSettings(step_deg=1e-6, max_profile_points=1000),
        )


def test_unknown_source_preset_is_rejected(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    with pytest.raises(ValueError, match="Unknown X-ray source preset"):
        simulate_powder_pattern(
            structure,
            AnalysisSettings(source_preset="not-a-source"),
        )


def test_exact_upper_boundary_reflection_is_retained(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    broad = simulate_powder_pattern(
        structure,
        AnalysisSettings(two_theta_min_deg=5, two_theta_max_deg=100),
    )
    boundary = next(item.two_theta_deg for item in broad.reflections if item.hkl == (2, 0, 0))
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(two_theta_min_deg=5, two_theta_max_deg=boundary),
    )
    assert (2, 0, 0) in [item.hkl for item in result.reflections]
    assert result.metadata["d_min_search_A"] < result.metadata["d_min_A"]
