from pathlib import Path
import math

import gemmi
import numpy as np
import pytest

import diffractscout.diffraction as diffraction
from diffractscout.diffraction import (
    apply_d_range_to_settings,
    simulate_powder_pattern,
    two_theta_for_d,
)
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


def test_energy_input_rejects_nonfinite_derived_wavelength() -> None:
    with pytest.raises(ValueError, match="Radiation input"):
        diffraction.resolve_wavelength(
            AnalysisSettings(input_mode="energy", energy_keV=1e-323)
        )


@pytest.mark.parametrize(
    "settings",
    [
        AnalysisSettings(input_mode="energy", energy_keV=20.0, wavelength_A=1.0),
        AnalysisSettings(input_mode="wavelength", wavelength_A=1.0, energy_keV=20.0),
        AnalysisSettings(source_preset="Custom", wavelength_A=1.0, energy_keV=20.0),
        AnalysisSettings(source_preset="Cu Ka", wavelength_A=1.0),
        AnalysisSettings(source_preset="Cu Ka", energy_keV=20.0),
    ],
)
def test_analysis_settings_reject_inactive_radiation_fields(
    settings: AnalysisSettings,
) -> None:
    with pytest.raises(ValueError, match="inactive"):
        diffraction.validate_analysis_settings(settings)


def test_analysis_settings_accept_documented_radiation_modes() -> None:
    for settings in (
        AnalysisSettings(source_preset="Cu Ka"),
        AnalysisSettings(input_mode="wavelength", wavelength_A=1.0),
        AnalysisSettings(input_mode="energy", energy_keV=20.0),
        AnalysisSettings(source_preset="Custom", wavelength_A=1.0),
    ):
        diffraction.validate_analysis_settings(settings)


def test_empty_d_and_two_theta_intersection_is_explicit_and_keeps_grid(
    demo_inputs: Path,
) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(
            two_theta_min_deg=5.0,
            two_theta_max_deg=20.0,
            d_max_A=1.0,
            step_deg=1.0,
            include_elasticity=False,
        ),
    )

    assert result.metadata["two_theta_range_deg"] == [5.0, 20.0]
    assert result.metadata["profile_sampled_two_theta_range_deg"] == [5.0, 20.0]
    assert result.metadata["requested_two_theta_range_deg"] == [5.0, 20.0]
    assert result.metadata["effective_two_theta_range_deg"] is None
    assert result.metadata["effective_window_empty"] is True
    assert not result.reflections
    assert any(
        "requested 2theta and d-spacing filter do not overlap" in warning.lower()
        for warning in result.warnings
    )
    assert not any(
        "no theoretical reflections" in warning.lower() for warning in result.warnings
    )


def test_equal_d_and_two_theta_boundary_is_a_nonempty_single_point() -> None:
    wavelength = 1.5406
    d_at_20 = wavelength / (2.0 * np.sin(np.deg2rad(20.0 / 2.0)))
    settings = AnalysisSettings(
        two_theta_min_deg=5.0,
        two_theta_max_deg=20.0,
        d_max_A=d_at_20,
    )

    narrowed = apply_d_range_to_settings(settings)

    assert narrowed.two_theta_min_deg == pytest.approx(20.0, abs=1e-12)
    assert narrowed.two_theta_max_deg == 20.0


def test_physically_impossible_d_max_is_an_empty_intersection(
    demo_inputs: Path,
) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(
            two_theta_min_deg=5.0,
            two_theta_max_deg=20.0,
            d_max_A=0.7,
            step_deg=1.0,
            include_elasticity=False,
        ),
    )

    assert result.metadata["effective_window_empty"] is True
    assert result.metadata["effective_two_theta_range_deg"] is None
    assert result.metadata["two_theta_range_deg"] == [5.0, 20.0]
    assert result.metadata["reflection_search_estimate"] == 0
    assert result.metadata["miller_candidates_generated"] == 0


def test_just_below_lambda_over_two_cannot_reenter_through_filter_tolerance(
    demo_inputs: Path,
) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    backscatter_d = float(structure.small_structure.cell.calculate_d((2, 0, 0)))
    wavelength = 2.0 * backscatter_d

    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(
            input_mode="wavelength",
            wavelength_A=wavelength,
            two_theta_min_deg=170.0,
            two_theta_max_deg=180.0,
            d_max_A=backscatter_d - 5e-13,
            step_deg=1.0,
            include_elasticity=False,
        ),
    )

    assert result.metadata["effective_window_empty"] is True
    assert result.metadata["effective_two_theta_range_deg"] is None
    assert result.metadata["reflection_search_estimate"] == 0
    assert result.metadata["miller_candidates_generated"] == 0
    assert not result.reflections


def test_profile_metadata_distinguishes_configured_and_sampled_endpoints(
    demo_inputs: Path,
) -> None:
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

    assert result.metadata["two_theta_range_deg"] == [5.0, 5.05]
    assert result.metadata["profile_sampled_two_theta_range_deg"] == pytest.approx(
        [5.0, 5.03]
    )
    expected_geometric_d_min = result.wavelength_A / (
        2.0 * np.sin(np.deg2rad(5.05 / 2.0))
    )
    assert result.metadata["geometric_d_min_A"] == pytest.approx(
        expected_geometric_d_min
    )


def test_reflection_search_estimate_bounds_highly_skewed_cell() -> None:
    cell = gemmi.UnitCell(1.0, 1.0, 1.0, 119.99, 119.99, 119.99)
    d_min = 0.200764
    old_volume_estimate = math.ceil(
        (4.0 * np.pi / 3.0) * cell.volume / d_min**3
    )
    actual_candidates = len(
        gemmi.make_miller_array(
            cell,
            gemmi.find_spacegroup_by_number(1),
            d_min,
            0.0,
            True,
        )
    )
    estimate = diffraction._reflection_search_estimate(cell, d_min)
    assert old_volume_estimate == 14
    assert actual_candidates == 30
    assert estimate >= actual_candidates
    assert estimate > old_volume_estimate


def test_reflection_search_estimate_fails_closed_for_near_singular_cell() -> None:
    cell = gemmi.UnitCell(1.0, 1.0, 1.0, 120.0, 120.0, 120.0)
    with pytest.raises(ValueError, match="near-singular"):
        diffraction._reflection_search_estimate(cell, 0.2)


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
