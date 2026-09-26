from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from compare_reference_engines import (  # noqa: E402
    _group_by_d_spacing,
    _validate_expectations,
    canonical_cubic_family,
    match_d_spacing_groups,
)

EXPECTATIONS_PATH = ROOT / "src" / "diffractscout" / "benchmark_data" / "expectations.json"


def _expectations() -> dict[str, object]:
    return json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))


def _peak(d_A: float, intensity: float, hkl: tuple[int, int, int]) -> dict[str, object]:
    return {
        "d_A": d_A,
        "two_theta_deg": 12.0,
        "intensity": intensity,
        "hkls": [hkl],
    }


def test_grouping_merges_coincident_d_values_and_sums_intensity() -> None:
    grouped = _group_by_d_spacing(
        [_peak(2.0, 3.0, (2, 0, 0)), _peak(2.0 + 4e-7, 7.0, (1, 1, 0))],
        tolerance_A=1e-6,
    )

    assert len(grouped) == 1
    assert grouped[0]["d_A"] == pytest.approx(2.0000002)
    assert grouped[0]["intensity"] == pytest.approx(10.0)
    assert grouped[0]["family_count"] == 2
    assert grouped[0]["hkls"] == [[1, 1, 0], [2, 0, 0]]


def test_grouping_does_not_chain_peaks_beyond_the_declared_window() -> None:
    grouped = _group_by_d_spacing(
        [
            _peak(3.0, 1.0, (3, 0, 0)),
            _peak(3.0 - 0.6e-6, 1.0, (2, 2, 0)),
            _peak(3.0 - 1.2e-6, 1.0, (2, 1, 1)),
        ],
        tolerance_A=1e-6,
    )

    assert len(grouped) == 2
    assert [group["family_count"] for group in grouped] == [2, 1]


def test_d_spacing_matching_is_one_to_one_and_reports_unmatched_groups() -> None:
    left = [{"d_A": 3.0}, {"d_A": 2.0}]
    right = [{"d_A": 3.0 + 0.5e-6}, {"d_A": 1.9}]

    matches, unmatched_left, unmatched_right = match_d_spacing_groups(
        left,
        right,
        tolerance_A=1e-6,
    )

    assert matches == [(0, 0)]
    assert unmatched_left == [1]
    assert unmatched_right == [1]


@pytest.mark.parametrize(
    ("hkl", "expected"),
    [
        ((1, 0, 0), (1, 0, 0)),
        ((-1, 1, 0), (1, 1, 0)),
        ((0, -2, 1), (2, 1, 0)),
    ],
)
def test_cubic_family_key_ignores_sign_and_permutation(
    hkl: tuple[int, int, int],
    expected: tuple[int, int, int],
) -> None:
    assert canonical_cubic_family(hkl) == expected


@pytest.mark.parametrize("hkl", [(1, 0), (1, 0, 0, 0)])
def test_cubic_family_key_requires_three_indices(hkl: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="exactly three"):
        canonical_cubic_family(hkl)


def test_current_benchmark_expectations_define_all_four_required_cases() -> None:
    cases = _validate_expectations(_expectations())

    assert set(cases) == {"simple_cubic_al", "bcc_fe", "fcc_al", "nacl"}


@pytest.mark.parametrize("case_name", ["simple_cubic_al", "bcc_fe", "fcc_al", "nacl"])
def test_missing_benchmark_case_fails_validation(case_name: str) -> None:
    expectations = _expectations()
    cases = expectations["cases"]
    assert isinstance(cases, dict)
    cases.pop(case_name)

    with pytest.raises(ValueError, match="requires exactly the packaged synthetic cases"):
        _validate_expectations(expectations)


def test_empty_case_set_fails_validation() -> None:
    expectations = _expectations()
    expectations["cases"] = {}

    with pytest.raises(ValueError, match="requires exactly the packaged synthetic cases"):
        _validate_expectations(expectations)


@pytest.mark.parametrize("field_name", ["first_allowed", "forbidden"])
def test_required_reflection_list_cannot_be_empty(field_name: str) -> None:
    expectations = _expectations()
    cases = expectations["cases"]
    assert isinstance(cases, dict)
    specification = cases["bcc_fe"]
    assert isinstance(specification, dict)
    specification[field_name] = []

    with pytest.raises(ValueError, match="must define exactly"):
        _validate_expectations(expectations)


def test_required_forbidden_reflection_field_cannot_be_missing() -> None:
    expectations = _expectations()
    cases = expectations["cases"]
    assert isinstance(cases, dict)
    specification = cases["nacl"]
    assert isinstance(specification, dict)
    specification.pop("forbidden")

    with pytest.raises(ValueError, match="missing required fields.*forbidden"):
        _validate_expectations(expectations)


@pytest.mark.parametrize(
    ("case_name", "field_name", "value"),
    [
        ("bcc_fe", "first_allowed", [[1, 1]]),
        ("fcc_al", "forbidden", [[0, 0, 0], [1, 0, 0]]),
        ("nacl", "first_allowed", [[1, 1, 1], [1, 1, 1], [2, 0, 0]]),
    ],
)
def test_malformed_or_duplicate_reflection_families_fail_validation(
    case_name: str,
    field_name: str,
    value: list[list[int]],
) -> None:
    expectations = _expectations()
    cases = expectations["cases"]
    assert isinstance(cases, dict)
    specification = cases[case_name]
    assert isinstance(specification, dict)
    specification[field_name] = value

    with pytest.raises(ValueError):
        _validate_expectations(expectations)
