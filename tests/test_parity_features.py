"""Phase-1 parity features: d-range filter, profile models, Cu Kα 2θ, hex labels."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from diffractscout.diffraction import CU_KA_WAVELENGTH_A, simulate_powder_pattern, two_theta_for_d
from diffractscout.models import AnalysisSettings
from diffractscout.structure import density_g_cm3, load_structure, unit_cell_formula_weight_g_mol


HEX_MG_CIF = """data_synthetic_hex_mg
_audit_creation_method 'DiffractScout synthetic hexagonal fixture'
_chemical_formula_sum 'Mg'
_cell_length_a 3.200000
_cell_length_b 3.200000
_cell_length_c 5.200000
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_space_group_name_H-M_alt 'P 63/m m c'
_space_group_IT_number 194
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Mg1 Mg 0.333333 0.666667 0.250000 1
"""


def test_d_range_filters_peaks(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    broad = simulate_powder_pattern(
        structure,
        AnalysisSettings(two_theta_min_deg=5, two_theta_max_deg=100),
    )
    assert len(broad.reflections) >= 3
    # Keep only the first peak's d-window around (111).
    first = broad.reflections[0]
    d_lo = first.d_spacing_A - 0.02
    d_hi = first.d_spacing_A + 0.02
    narrow = simulate_powder_pattern(
        structure,
        AnalysisSettings(
            two_theta_min_deg=5,
            two_theta_max_deg=100,
            d_min_A=d_lo,
            d_max_A=d_hi,
        ),
    )
    assert narrow.reflections
    for item in narrow.reflections:
        assert d_lo - 1e-9 <= item.d_spacing_A <= d_hi + 1e-9
    assert all(item.d_spacing_A <= d_hi + 1e-9 for item in narrow.reflections)
    assert len(narrow.reflections) < len(broad.reflections)
    assert narrow.metadata["filter_d_min_A"] == pytest.approx(d_lo)
    assert narrow.metadata["filter_d_max_A"] == pytest.approx(d_hi)


def test_profile_model_gaussian_runs(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(
            two_theta_min_deg=5,
            two_theta_max_deg=80,
            profile_model="gaussian",
        ),
    )
    assert result.metadata["profile_model"] == "gaussian"
    assert result.intensity_profile.size > 0
    assert float(np.max(result.intensity_profile)) == pytest.approx(100.0)
    assert result.reflections


def test_two_theta_cu_ka_present_and_finite(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(two_theta_min_deg=5, two_theta_max_deg=100),
    )
    first = result.reflections[0]
    assert first.two_theta_cu_ka_deg > 0
    assert np.isfinite(first.two_theta_cu_ka_deg)
    expected = two_theta_for_d(first.d_spacing_A, CU_KA_WAVELENGTH_A)
    assert expected is not None
    assert first.two_theta_cu_ka_deg == pytest.approx(expected, rel=1e-12)
    assert first.sin_theta == pytest.approx(np.sin(np.deg2rad(first.theta_deg)), rel=1e-12)
    assert first.phase_relative_R_hkl_pct == pytest.approx(100.0)
    assert first.mean_structure_factor_sq_per_multiplicity == pytest.approx(first.structure_factor_sq)
    assert result.metadata["density_g_cm3"] is not None
    assert result.metadata["density_g_cm3"] > 0
    fw = unit_cell_formula_weight_g_mol(structure.small_structure)
    assert fw is not None
    assert result.metadata["formula_weight_g_mol"] == pytest.approx(fw)
    dens = density_g_cm3(fw, float(structure.small_structure.cell.volume))
    assert dens is not None
    assert result.metadata["density_g_cm3"] == pytest.approx(dens)


def test_cu_ka_convenience_angle_is_missing_when_reflection_is_inaccessible(
    demo_inputs: Path,
) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(
            source_preset="Ag Ka",
            two_theta_min_deg=5.0,
            two_theta_max_deg=170.0,
        ),
    )
    inaccessible = [
        item for item in result.reflections if item.d_spacing_A < CU_KA_WAVELENGTH_A / 2.0
    ]
    assert inaccessible
    assert all(item.two_theta_cu_ka_deg is None for item in inaccessible)


def test_hexagonal_miller_bravais_labeling(tmp_path: Path) -> None:
    cif_path = tmp_path / "synthetic_hex_mg.cif"
    cif_path.write_text(HEX_MG_CIF, encoding="utf-8")
    structure = load_structure(cif_path)
    result = simulate_powder_pattern(
        structure,
        AnalysisSettings(two_theta_min_deg=5, two_theta_max_deg=90, include_elasticity=False),
    )
    assert result.reflections
    for item in result.reflections:
        assert item.i is not None
        assert item.i == -(item.h + item.k)
        assert item.family_label == "{" + f"{item.h} {item.k} {item.i} {item.l}" + "}"
