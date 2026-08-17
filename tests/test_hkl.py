"""Unit tests for Miller–Bravais helpers."""

from __future__ import annotations

import gemmi

from diffractscout.hkl import family_label_hkl, miller_bravais_i, uses_miller_bravais


def test_miller_bravais_i() -> None:
    assert miller_bravais_i(1, 0) == -1
    assert miller_bravais_i(1, 1) == -2
    assert miller_bravais_i(2, -1) == -1


def test_family_label_three_and_four_index() -> None:
    assert family_label_hkl(1, 1, 1) == "{1 1 1}"
    assert family_label_hkl(1, 0, 0, use_four_index=True) == "{1 0 -1 0}"
    assert family_label_hkl(1, 1, 0, use_four_index=True, i=-2) == "{1 1 -2 0}"


def test_uses_miller_bravais_crystal_systems() -> None:
    assert uses_miller_bravais(gemmi.find_spacegroup_by_name("P 63/m m c"))
    assert uses_miller_bravais(gemmi.find_spacegroup_by_name("P -3 m 1"))
    assert not uses_miller_bravais(gemmi.find_spacegroup_by_name("F m -3 m"))
    assert not uses_miller_bravais(None)


def test_rhombohedral_setting_uses_three_index_labels() -> None:
    assert not uses_miller_bravais(gemmi.find_spacegroup_by_name("R -3:R"))
