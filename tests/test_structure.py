from pathlib import Path
import warnings

from diffractscout.structure import load_structure


def test_load_synthetic_fcc(demo_inputs: Path) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    assert not any("OLD_ERROR_HANDLING" in str(item.message) for item in caught)
    assert structure.formula == "Al"
    assert structure.space_group_number == 225
    assert structure.space_group_symbol.replace(" ", "") == "Fm-3m"
    assert structure.site_count_asymmetric == 1
    assert structure.site_count_unit_cell == 4
    assert not structure.has_partial_occupancy
    assert structure.small_structure.sites[0].occ == 1.0
    assert structure.structure_factor_structure.sites[0].occ == 1.0 / 48.0
    assert len(structure.cif_sha256) == 64


def test_space_group_number_is_used_when_symbol_is_absent(tmp_path: Path) -> None:
    cif = tmp_path / "number_only.cif"
    cif.write_text(
        """data_number_only
_cell_length_a 4
_cell_length_b 4
_cell_length_c 4
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_IT_number 225
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
    assert structure.space_group_number == 225
    assert structure.source_metadata["space_group_resolution_source"] == "cif_number"
