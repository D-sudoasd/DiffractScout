"""Unit tests for Miller–Bravais helpers."""

from __future__ import annotations

import gemmi
import numpy as np
import pytest

from diffractscout.hkl import (
    family_label_hkl,
    label_hkl_for_crystal_system,
    miller_bravais_i,
    normalize_hkl,
    plane_hkl_for_normal,
    uses_miller_bravais,
)


def test_miller_bravais_i() -> None:
    assert miller_bravais_i(1, 0) == -1
    assert miller_bravais_i(1, 1) == -2
    assert miller_bravais_i(2, -1) == -1


@pytest.mark.parametrize("value", [1.9, True, float("nan"), float("inf")])
def test_miller_bravais_i_rejects_non_integer_inputs(value: object) -> None:
    with pytest.raises(ValueError):
        miller_bravais_i(value, 0)


def test_family_label_three_and_four_index() -> None:
    assert family_label_hkl(1, 1, 1) == "{1 1 1}"
    assert family_label_hkl(1, 0, 0, use_four_index=True) == "{1 0 -1 0}"
    assert family_label_hkl(1, 1, 0, use_four_index=True, i=-2) == "{1 1 -2 0}"
    assert family_label_hkl(1, 0, 0, i=999) == "{1 0 0}"
    assert family_label_hkl(1, 0, 0, i=1.9) == "{1 0 0}"


@pytest.mark.parametrize("value", [1.9, True, float("nan"), float("inf")])
def test_family_label_rejects_non_integer_inputs(value: object) -> None:
    with pytest.raises(ValueError):
        family_label_hkl(value, 0, 0)
    with pytest.raises(ValueError):
        family_label_hkl(1, 0, 0, use_four_index=True, i=value)


def test_uses_miller_bravais_crystal_systems() -> None:
    assert uses_miller_bravais(gemmi.find_spacegroup_by_name("P 63/m m c"))
    assert uses_miller_bravais(gemmi.find_spacegroup_by_name("P -3 m 1"))
    assert not uses_miller_bravais(gemmi.find_spacegroup_by_name("F m -3 m"))
    assert not uses_miller_bravais(None)


def test_rhombohedral_setting_uses_three_index_labels() -> None:
    assert not uses_miller_bravais(gemmi.find_spacegroup_by_name("R -3:R"))


@pytest.mark.parametrize("value", [1.9, True, float("nan"), float("inf")])
def test_crystal_system_label_rejects_non_integer_inputs(value: object) -> None:
    with pytest.raises(ValueError):
        label_hkl_for_crystal_system(value, 0, 0, "hexagonal")


def test_normalize_hkl_accepts_integer_numpy_scalars() -> None:
    assert normalize_hkl((np.int64(1), np.int32(0), 1.0)) == (1, 0, 1)


@pytest.mark.parametrize(
    "values",
    [
        (True, 0, 0),
        (1.9, 0, 0),
        (float("nan"), 0, 0),
        (float("inf"), 0, 0),
        ("1", 0, 0),
    ],
)
def test_normalize_hkl_rejects_bool_fractional_and_nonfinite_values(values: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        normalize_hkl(values)


def test_valid_four_index_plane_routes_to_three_index_normal() -> None:
    assert plane_hkl_for_normal((1, 0, -1, 0)) == (1, 0, 0)


def test_invalid_four_index_plane_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"i = -\(h \+ k\)"):
        plane_hkl_for_normal((1, 0, 0, 0))
