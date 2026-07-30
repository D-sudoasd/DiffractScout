"""Synthetic, self-identifying fixtures for installation and numerical smoke tests."""

from __future__ import annotations

from pathlib import Path

from .utils import write_json

SYNTHETIC_FCC_CIF = """data_synthetic_fcc_al
_audit_creation_method 'DiffractScout synthetic validation fixture; not experimental data'
_chemical_formula_sum 'Al'
_cell_length_a 4.000000
_cell_length_b 4.000000
_cell_length_c 4.000000
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_name_H-M_alt 'F m -3 m'
_space_group_IT_number 225
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al1 Al 0 0 0 1
"""

SYNTHETIC_ISOTROPIC_CIJ = [
    [200.0, 120.0, 120.0, 0.0, 0.0, 0.0],
    [120.0, 200.0, 120.0, 0.0, 0.0, 0.0],
    [120.0, 120.0, 200.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 40.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 0.0, 40.0, 0.0],
    [0.0, 0.0, 0.0, 0.0, 0.0, 40.0],
]


def write_demo_inputs(directory: str | Path) -> Path:
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    cif = root / "synthetic_fcc_al.cif"
    cif.write_text(SYNTHETIC_FCC_CIF, encoding="utf-8")
    write_json(
        root / "synthetic_fcc_al_elasticity.json",
        {
            "schema": "diffractscout_elasticity_v1",
            "status": "ok",
            "formula": "Al",
            "cif_filename": cif.name,
            "stiffness_GPa": SYNTHETIC_ISOTROPIC_CIJ,
            "provenance": {
                "provider": "DiffractScout test fixture",
                "material_id": "synthetic-isotropic-cubic",
                "nature_of_data": "synthetic_test_fixture",
                "numerical_cij": True,
                "not_experimental": True,
                "coordinate_frame": "crystal_cartesian_from_cif_lattice",
                "paired_cif": cif.name,
            },
            "diffractscout": {
                "stiffness_GPa": SYNTHETIC_ISOTROPIC_CIJ,
                "coordinate_frame": "crystal_cartesian_from_cif_lattice",
                "paired_cif": cif.name,
            },
        },
    )
    return root
