from pathlib import Path

from diffractscout.structure import load_structure


def test_load_synthetic_fcc(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    assert structure.formula == "Al"
    assert structure.space_group_number == 225
    assert structure.space_group_symbol.replace(" ", "") == "Fm-3m"
    assert structure.site_count_asymmetric == 1
    assert structure.site_count_unit_cell == 4
    assert not structure.has_partial_occupancy
    assert structure.small_structure.sites[0].occ == 1.0
    assert structure.structure_factor_structure.sites[0].occ == 1.0 / 48.0
    assert len(structure.cif_sha256) == 64
