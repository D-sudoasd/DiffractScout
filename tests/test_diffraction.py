from pathlib import Path

import gemmi
import numpy as np
import pytest

import diffractscout.diffraction as diffraction
from diffractscout.diffraction import simulate_powder_pattern, two_theta_for_d
from diffractscout.elasticity import MP_IEEE_CONVENTIONAL_FRAME, discover_elastic_tensor, validate_elastic_tensor
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


def test_two_theta_for_d_tolerates_only_roundoff_above_bragg_limit() -> None:
    wavelength = 1.0
    exact_d = wavelength / 2.0
    barely_over_limit = exact_d / (1.0 + 5e-13)
    genuinely_inaccessible = exact_d / (1.0 + 2e-12)

    assert two_theta_for_d(exact_d, wavelength) == pytest.approx(180.0)
    assert two_theta_for_d(barely_over_limit, wavelength) == pytest.approx(180.0)
    assert two_theta_for_d(genuinely_inaccessible, wavelength) is None


def test_exact_backscatter_reflection_reaches_explicit_lp_singularity_error(
    tmp_path: Path,
) -> None:
    cif = tmp_path / "backscatter_p1.cif"
    cif.write_text(
        """data_backscatter_p1
_cell_length_a 2
_cell_length_b 3
_cell_length_c 4
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_IT_number 1
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al1 Al 0 0 0 1
""",
        encoding="utf-8",
    )
    structure = load_structure(cif)
    with pytest.raises(ValueError, match="Lorentz-polarization factor is singular"):
        simulate_powder_pattern(
            structure,
            AnalysisSettings(
                input_mode="wavelength",
                wavelength_A=4.0,
                two_theta_min_deg=5.0,
                two_theta_max_deg=180.0,
                step_deg=1.0,
                include_elasticity=False,
            ),
        )


def test_profile_grid_never_exceeds_requested_upper_bound(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(
            two_theta_min_deg=5.0,
            two_theta_max_deg=5.05,
            step_deg=0.03,
            include_elasticity=False,
        ),
    )
    assert result.two_theta_grid.size == 2
    assert float(np.max(result.two_theta_grid)) <= 5.05


def test_lorentz_polarization_singularity_is_not_nan() -> None:
    assert diffraction._lp_factor(np.pi / 2.0) is None


def test_reflection_profile_workload_guard_runs_before_profile_loop(
    demo_inputs: Path, monkeypatch
) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    monkeypatch.setattr(diffraction, "MAX_PROFILE_WORK", 1)
    with pytest.raises(ValueError, match="Reflection-by-profile accumulation"):
        simulate_powder_pattern(
            structure,
            AnalysisSettings(include_elasticity=False),
        )


def test_frame_transform_required_propagates_to_peak_without_modulus(
    demo_inputs: Path,
) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    tensor = validate_elastic_tensor(
        np.eye(6) * 100.0,
        coordinate_frame=MP_IEEE_CONVENTIONAL_FRAME,
    )
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(include_elasticity=True),
        elastic_tensor=tensor,
    )
    assert tensor.status == "frame_transform_required"
    assert result.reflections
    assert {
        reflection.elastic_status for reflection in result.reflections
    } == {"frame_transform_required"}
    assert all(
        reflection.young_modulus_hkl_normal_GPa is None
        for reflection in result.reflections
    )
