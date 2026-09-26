#!/usr/bin/env python3
"""Compare synthetic diffraction and cubic-elasticity fixtures with pymatgen.

This is an optional, offline validation tool. It does not participate in the
DiffractScout analysis path and does not modify production calculations.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import warnings
from typing import Any

import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = REPOSITORY_ROOT / "src" / "diffractscout" / "benchmark_data"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "validation_cases" / "independent_engines"
EXPECTATIONS_SCHEMA = "diffractscout_analytic_expectations_v1"
REQUIRED_BENCHMARK_CASES = {
    "simple_cubic_al": "simple_cubic_al.cif",
    "bcc_fe": "bcc_fe.cif",
    "fcc_al": "fcc_al.cif",
    "nacl": "nacl.cif",
}
FORBIDDEN_FAMILY_COUNTS = {"bcc_fe": 2, "fcc_al": 2, "nacl": 2}
WAVELENGTH_A = 1.5406
TWO_THETA_RANGE_DEG = (5.0, 120.0)
D_SPACING_TOLERANCE_A = 1e-6
TWO_THETA_TOLERANCE_DEG = 1e-5
ELASTIC_ABSOLUTE_TOLERANCE_GPA = 1e-8
ELASTIC_RELATIVE_TOLERANCE = 1e-10
CUBIC_STIFFNESS_GPA = (
    (250.0, 150.0, 150.0, 0.0, 0.0, 0.0),
    (150.0, 250.0, 150.0, 0.0, 0.0, 0.0),
    (150.0, 150.0, 250.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 100.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 0.0, 100.0, 0.0),
    (0.0, 0.0, 0.0, 0.0, 0.0, 100.0),
)
CUBIC_DIRECTIONS = ((1, 0, 0), (1, 1, 0), (1, 1, 1))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_cubic_family(hkl: Iterable[int]) -> tuple[int, int, int]:
    """Return a sign/permutation-independent cubic-family key."""

    values = tuple(abs(int(value)) for value in hkl)
    if len(values) != 3:
        raise ValueError("A Miller index must have exactly three components.")
    return tuple(sorted(values, reverse=True))  # type: ignore[return-value]


def _validated_hkl_list(
    case_name: str,
    field_name: str,
    value: Any,
    *,
    expected_count: int,
) -> set[tuple[int, int, int]]:
    if not isinstance(value, list) or len(value) != expected_count:
        raise ValueError(
            f"Benchmark case {case_name!r} must define exactly {expected_count} "
            f"{field_name} Miller-index triplets."
        )
    families: set[tuple[int, int, int]] = set()
    for index, item in enumerate(value):
        if (
            not isinstance(item, list)
            or len(item) != 3
            or any(type(component) is not int for component in item)
            or item == [0, 0, 0]
        ):
            raise ValueError(
                f"Benchmark case {case_name!r} has an invalid {field_name} entry at index {index}."
            )
        family = canonical_cubic_family(item)
        if family in families:
            raise ValueError(
                f"Benchmark case {case_name!r} repeats a cubic family in {field_name}."
            )
        families.add(family)
    return families


def _validate_expectations(expectations: Any) -> Mapping[str, Mapping[str, Any]]:
    """Reject missing or malformed packaged fixtures before any comparisons run."""

    if not isinstance(expectations, Mapping) or expectations.get("schema") != EXPECTATIONS_SCHEMA:
        raise ValueError("Unsupported analytic benchmark expectation schema.")
    cases = expectations.get("cases")
    if not isinstance(cases, Mapping):
        raise ValueError("Analytic benchmark expectations must contain a cases object.")
    expected_names = set(REQUIRED_BENCHMARK_CASES)
    observed_names = set(cases)
    if observed_names != expected_names:
        missing = sorted(expected_names - observed_names)
        extra = sorted(observed_names - expected_names)
        raise ValueError(
            "Independent engine comparison requires exactly the packaged synthetic cases "
            f"{sorted(expected_names)}; missing={missing}, extra={extra}."
        )

    for case_name, expected_file in REQUIRED_BENCHMARK_CASES.items():
        specification = cases[case_name]
        if not isinstance(specification, Mapping):
            raise ValueError(f"Benchmark case {case_name!r} must be an object.")
        required_fields = {"file", "lattice_a_A", "first_allowed", "multiplicity"}
        if case_name in FORBIDDEN_FAMILY_COUNTS:
            required_fields.add("forbidden")
        missing_fields = sorted(required_fields - set(specification))
        if missing_fields:
            raise ValueError(
                f"Benchmark case {case_name!r} is missing required fields: {missing_fields}."
            )
        if specification["file"] != expected_file:
            raise ValueError(
                f"Benchmark case {case_name!r} must use fixture {expected_file!r}."
            )
        lattice_a = specification["lattice_a_A"]
        if (
            isinstance(lattice_a, bool)
            or not isinstance(lattice_a, (int, float))
            or not math.isfinite(float(lattice_a))
            or float(lattice_a) <= 0.0
        ):
            raise ValueError(f"Benchmark case {case_name!r} has an invalid lattice_a_A.")
        allowed = _validated_hkl_list(
            case_name,
            "first_allowed",
            specification["first_allowed"],
            expected_count=3,
        )
        if case_name in FORBIDDEN_FAMILY_COUNTS:
            forbidden = _validated_hkl_list(
                case_name,
                "forbidden",
                specification["forbidden"],
                expected_count=FORBIDDEN_FAMILY_COUNTS[case_name],
            )
            if allowed & forbidden:
                raise ValueError(
                    f"Benchmark case {case_name!r} lists a cubic family as both allowed and forbidden."
                )
        elif "forbidden" in specification:
            raise ValueError(
                "The simple-cubic benchmark case must omit the forbidden field."
            )

        multiplicities = specification["multiplicity"]
        if not isinstance(multiplicities, Mapping) or not multiplicities:
            raise ValueError(
                f"Benchmark case {case_name!r} must define a non-empty multiplicity object."
            )
        multiplicity_families: set[tuple[int, int, int]] = set()
        for key, multiplicity in multiplicities.items():
            if not isinstance(key, str):
                raise ValueError(f"Benchmark case {case_name!r} has a non-string multiplicity key.")
            try:
                components = [int(part) for part in key.split()]
            except ValueError as exc:
                raise ValueError(
                    f"Benchmark case {case_name!r} has an invalid multiplicity key {key!r}."
                ) from exc
            if (
                len(components) != 3
                or key.split() != [str(component) for component in components]
                or components == [0, 0, 0]
                or isinstance(multiplicity, bool)
                or not isinstance(multiplicity, int)
                or multiplicity <= 0
            ):
                raise ValueError(
                    f"Benchmark case {case_name!r} has an invalid multiplicity entry {key!r}."
                )
            family = canonical_cubic_family(components)
            if family in multiplicity_families:
                raise ValueError(
                    f"Benchmark case {case_name!r} repeats a cubic family in multiplicity."
                )
            multiplicity_families.add(family)
    return cases


def _group_by_d_spacing(
    peaks: Sequence[Mapping[str, Any]],
    *,
    tolerance_A: float,
) -> list[dict[str, Any]]:
    """Merge coincident line families using a fixed-width d-spacing window.

    Groups are anchored to their first (largest-d) peak rather than chained
    through successive neighbors, so the total width of any group cannot
    exceed ``tolerance_A``.
    """

    if not math.isfinite(tolerance_A) or tolerance_A < 0:
        raise ValueError("d-spacing tolerance must be a finite non-negative value.")
    ordered = sorted(peaks, key=lambda peak: float(peak["d_A"]), reverse=True)
    groups: list[list[Mapping[str, Any]]] = []
    for peak in ordered:
        d_value = float(peak["d_A"])
        if not math.isfinite(d_value) or d_value <= 0:
            raise ValueError("Peak d-spacing values must be finite and positive.")
        if not groups or abs(d_value - float(groups[-1][0]["d_A"])) > tolerance_A:
            groups.append([peak])
        else:
            groups[-1].append(peak)

    merged: list[dict[str, Any]] = []
    for group in groups:
        d_values = [float(peak["d_A"]) for peak in group]
        theta_values = [float(peak["two_theta_deg"]) for peak in group]
        hkls = [tuple(int(component) for component in hkl) for peak in group for hkl in peak["hkls"]]
        merged.append(
            {
                "d_A": float(sum(d_values) / len(d_values)),
                "two_theta_deg": float(sum(theta_values) / len(theta_values)),
                "intensity": float(sum(float(peak["intensity"]) for peak in group)),
                "hkls": [list(hkl) for hkl in sorted(set(hkls))],
                "family_count": sum(int(peak.get("family_count", 1)) for peak in group),
            }
        )
    return merged


def match_d_spacing_groups(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
    *,
    tolerance_A: float,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Match two d-sorted peak-group lists one-to-one, without using hkl labels."""

    if not math.isfinite(tolerance_A) or tolerance_A < 0:
        raise ValueError("d-spacing tolerance must be a finite non-negative value.")
    left_order = sorted(range(len(left)), key=lambda index: float(left[index]["d_A"]), reverse=True)
    right_order = sorted(range(len(right)), key=lambda index: float(right[index]["d_A"]), reverse=True)
    matches: list[tuple[int, int]] = []
    unmatched_left: list[int] = []
    unmatched_right: list[int] = []
    li = 0
    ri = 0
    while li < len(left_order) and ri < len(right_order):
        left_index = left_order[li]
        right_index = right_order[ri]
        delta = float(left[left_index]["d_A"]) - float(right[right_index]["d_A"])
        if abs(delta) <= tolerance_A:
            matches.append((left_index, right_index))
            li += 1
            ri += 1
        elif delta > 0:
            unmatched_left.append(left_index)
            li += 1
        else:
            unmatched_right.append(right_index)
            ri += 1
    unmatched_left.extend(left_order[li:])
    unmatched_right.extend(right_order[ri:])
    return matches, unmatched_left, unmatched_right


def _two_theta_from_d(d_A: float, wavelength_A: float) -> float:
    argument = wavelength_A / (2.0 * d_A)
    if argument < 0 or argument > 1:
        raise ValueError(f"d-spacing {d_A} A is inaccessible at {wavelength_A} A.")
    return float(np.degrees(2.0 * np.arcsin(argument)))


def _selection_rule(case_name: str, hkl: tuple[int, int, int]) -> bool:
    first, second, third = (abs(int(value)) for value in hkl)
    if first == second == third == 0:
        return False
    if case_name == "bcc_fe":
        return (first + second + third) % 2 == 0
    if case_name in {"fcc_al", "nacl"}:
        return first % 2 == second % 2 == third % 2
    return True


def _peak_rows_from_diffractscout(reflections: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {
            "d_A": float(reflection.d_spacing_A),
            "two_theta_deg": float(reflection.two_theta_deg),
            "intensity": float(reflection.intensity_with_lp),
            "hkls": [tuple(int(value) for value in reflection.hkl)],
            "family_count": 1,
        }
        for reflection in reflections
    ]


def _peak_rows_from_pymatgen(pattern: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for two_theta, d_A, intensity, family_entries in zip(
        pattern.x, pattern.d_hkls, pattern.y, pattern.hkls, strict=True
    ):
        hkls = [tuple(int(value) for value in entry["hkl"]) for entry in family_entries]
        rows.append(
            {
                "d_A": float(d_A),
                "two_theta_deg": float(two_theta),
                "intensity": float(intensity),
                "hkls": hkls,
                "family_count": len(hkls),
            }
        )
    return rows


def _all_peak_hkls(groups: Sequence[Mapping[str, Any]]) -> set[tuple[int, int, int]]:
    return {
        tuple(int(component) for component in hkl)
        for group in groups
        for hkl in group["hkls"]
    }


def _normalized_intensity(groups: Sequence[Mapping[str, Any]], index: int) -> float:
    maximum = max(float(group["intensity"]) for group in groups)
    if maximum <= 0:
        return 0.0
    return 100.0 * float(groups[index]["intensity"]) / maximum


def _compare_case(
    case_name: str,
    specification: Mapping[str, Any],
    cif_path: Path,
    *,
    xrd_calculator_type: Any,
    structure_type: Any,
    load_structure_fn: Any,
    simulate_powder_pattern_fn: Any,
    analysis_settings_type: Any,
) -> dict[str, Any]:
    from diffractscout.diffraction import CU_KA_WAVELENGTH_A

    if not math.isclose(CU_KA_WAVELENGTH_A, WAVELENGTH_A, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(
            f"The reference wavelength ({WAVELENGTH_A} A) does not match the project's Cu Ka "
            f"preset ({CU_KA_WAVELENGTH_A} A)."
        )
    gemmi_structure = load_structure_fn(cif_path)
    gemmi_result = simulate_powder_pattern_fn(
        gemmi_structure,
        analysis_settings_type(
            source_preset="Cu Ka",
            two_theta_min_deg=TWO_THETA_RANGE_DEG[0],
            two_theta_max_deg=TWO_THETA_RANGE_DEG[1],
            include_elasticity=False,
        ),
    )
    # Disable primitive-cell reduction so reported pymatgen HKLs refer to the
    # conventional cells encoded by the packaged benchmark CIFs.
    pymatgen_structure = structure_type.from_file(str(cif_path), primitive=False)
    pymatgen_calculator = xrd_calculator_type(wavelength=CU_KA_WAVELENGTH_A, symprec=0)
    pymatgen_pattern = pymatgen_calculator.get_pattern(
        pymatgen_structure,
        scaled=False,
        two_theta_range=TWO_THETA_RANGE_DEG,
    )
    gemmi_groups = _group_by_d_spacing(
        _peak_rows_from_diffractscout(gemmi_result.reflections),
        tolerance_A=D_SPACING_TOLERANCE_A,
    )
    pymatgen_groups = _group_by_d_spacing(
        _peak_rows_from_pymatgen(pymatgen_pattern),
        tolerance_A=D_SPACING_TOLERANCE_A,
    )
    matches, missing_from_pymatgen, missing_from_gemmi = match_d_spacing_groups(
        gemmi_groups,
        pymatgen_groups,
        tolerance_A=D_SPACING_TOLERANCE_A,
    )

    peak_comparisons: list[dict[str, Any]] = []
    max_abs_delta_d = 0.0
    max_abs_delta_two_theta = 0.0
    max_abs_delta_relative_intensity = 0.0
    for gemmi_index, pymatgen_index in matches:
        gemmi_group = gemmi_groups[gemmi_index]
        pymatgen_group = pymatgen_groups[pymatgen_index]
        delta_d = abs(float(gemmi_group["d_A"]) - float(pymatgen_group["d_A"]))
        delta_two_theta = abs(
            float(gemmi_group["two_theta_deg"]) - float(pymatgen_group["two_theta_deg"])
        )
        gemmi_relative = _normalized_intensity(gemmi_groups, gemmi_index)
        pymatgen_relative = _normalized_intensity(pymatgen_groups, pymatgen_index)
        delta_relative = abs(gemmi_relative - pymatgen_relative)
        max_abs_delta_d = max(max_abs_delta_d, delta_d)
        max_abs_delta_two_theta = max(max_abs_delta_two_theta, delta_two_theta)
        max_abs_delta_relative_intensity = max(max_abs_delta_relative_intensity, delta_relative)
        peak_comparisons.append(
            {
                "d_A_gemmi": float(gemmi_group["d_A"]),
                "d_A_pymatgen": float(pymatgen_group["d_A"]),
                "abs_delta_d_A": delta_d,
                "two_theta_deg_gemmi": float(gemmi_group["two_theta_deg"]),
                "two_theta_deg_pymatgen": float(pymatgen_group["two_theta_deg"]),
                "abs_delta_two_theta_deg": delta_two_theta,
                "gemmi_hkl_families": gemmi_group["hkls"],
                "pymatgen_hkl_families": pymatgen_group["hkls"],
                "gemmi_relative_intensity_max_100": gemmi_relative,
                "pymatgen_relative_intensity_max_100": pymatgen_relative,
                "abs_delta_relative_intensity_percentage_points": delta_relative,
            }
        )

    gemmi_hkls = _all_peak_hkls(gemmi_groups)
    pymatgen_hkls = _all_peak_hkls(pymatgen_groups)
    expected_allowed = {
        canonical_cubic_family(hkl)
        for hkl in specification["first_allowed"]
    }
    expected_forbidden = {
        canonical_cubic_family(hkl)
        for hkl in specification.get("forbidden", [])
    }
    gemmi_families = {canonical_cubic_family(hkl) for hkl in gemmi_hkls}
    pymatgen_families = {canonical_cubic_family(hkl) for hkl in pymatgen_hkls}
    gemmi_rule_violations = sorted(
        canonical_cubic_family(hkl)
        for hkl in gemmi_hkls
        if not _selection_rule(case_name, hkl)
    )
    pymatgen_rule_violations = sorted(
        canonical_cubic_family(hkl)
        for hkl in pymatgen_hkls
        if not _selection_rule(case_name, hkl)
    )
    forbidden_present_gemmi = sorted(expected_forbidden & gemmi_families)
    forbidden_present_pymatgen = sorted(expected_forbidden & pymatgen_families)
    allowed_missing_gemmi = sorted(expected_allowed - gemmi_families)
    allowed_missing_pymatgen = sorted(expected_allowed - pymatgen_families)

    position_passed = (
        not missing_from_gemmi
        and not missing_from_pymatgen
        and max_abs_delta_d <= D_SPACING_TOLERANCE_A
        and max_abs_delta_two_theta <= TWO_THETA_TOLERANCE_DEG
    )
    selection_passed = not (
        gemmi_rule_violations
        or pymatgen_rule_violations
        or forbidden_present_gemmi
        or forbidden_present_pymatgen
        or allowed_missing_gemmi
        or allowed_missing_pymatgen
    )
    return {
        "input_cif": cif_path.relative_to(REPOSITORY_ROOT).as_posix(),
        "input_sha256": sha256_file(cif_path),
        "pymatgen_structure_site_count": len(pymatgen_structure),
        "gemmi_reflection_family_count": len(gemmi_result.reflections),
        "pymatgen_pattern_peak_count": len(pymatgen_pattern.x),
        "gemmi_d_spacing_group_count": len(gemmi_groups),
        "pymatgen_d_spacing_group_count": len(pymatgen_groups),
        "matched_d_spacing_group_count": len(matches),
        "unmatched_gemmi_group_indices": missing_from_pymatgen,
        "unmatched_pymatgen_group_indices": missing_from_gemmi,
        "position_max_abs_delta_d_A": max_abs_delta_d,
        "position_max_abs_delta_two_theta_deg": max_abs_delta_two_theta,
        "position_passed": position_passed,
        "selection_rules": {
            "expected_allowed_families": [list(item) for item in sorted(expected_allowed)],
            "expected_forbidden_families": [list(item) for item in sorted(expected_forbidden)],
            "gemmi_forbidden_present": [list(item) for item in forbidden_present_gemmi],
            "pymatgen_forbidden_present": [list(item) for item in forbidden_present_pymatgen],
            "gemmi_allowed_missing": [list(item) for item in allowed_missing_gemmi],
            "pymatgen_allowed_missing": [list(item) for item in allowed_missing_pymatgen],
            "gemmi_rule_violations": [list(item) for item in gemmi_rule_violations],
            "pymatgen_rule_violations": [list(item) for item in pymatgen_rule_violations],
            "passed": selection_passed,
        },
        "intensity_comparison": {
            "interpretation": "diagnostic_only_no_acceptance_threshold",
            "max_abs_delta_relative_intensity_percentage_points": max_abs_delta_relative_intensity,
            "peaks": peak_comparisons,
        },
    }


def _cubic_elasticity_comparison(
    *,
    pymatgen_elastic_tensor_type: Any,
    validate_elastic_tensor_fn: Any,
    project_young_modulus_fn: Any,
) -> dict[str, Any]:
    from diffractscout.structure import load_structure

    cif_path = BENCHMARK_ROOT / "fcc_al.cif"
    structure = load_structure(cif_path)
    stiffness = np.asarray(CUBIC_STIFFNESS_GPA, dtype=float)
    project_tensor = validate_elastic_tensor_fn(stiffness, nature_of_data="synthetic_test_fixture")
    reference_tensor = pymatgen_elastic_tensor_type.from_voigt(stiffness)
    reference_compliance = reference_tensor.compliance_tensor
    rows: list[dict[str, Any]] = []
    passed = True
    for hkl in CUBIC_DIRECTIONS:
        gemmi_modulus = project_young_modulus_fn(
            project_tensor,
            structure.small_structure.cell,
            hkl,
        )
        # Contract the 4th-rank compliance tensor to obtain Young's modulus.
        # ElasticTensor.directional_elastic_mod instead contracts stiffness
        # and returns a longitudinal modulus, so it is not the target quantity.
        direction = np.asarray(hkl, dtype=float)
        direction /= np.linalg.norm(direction)
        inverse_modulus = float(reference_compliance.einsum_sequence([direction] * 4))
        pymatgen_modulus = 1.0 / inverse_modulus
        if gemmi_modulus is None:
            passed = False
            delta = None
            check = False
        else:
            delta = abs(float(gemmi_modulus) - pymatgen_modulus)
            check = delta <= max(
                ELASTIC_ABSOLUTE_TOLERANCE_GPA,
                ELASTIC_RELATIVE_TOLERANCE * abs(pymatgen_modulus),
            )
            passed = passed and check
        rows.append(
            {
                "hkl_normal": list(hkl),
                "gemmi_project_modulus_GPa": (
                    float(gemmi_modulus) if gemmi_modulus is not None else None
                ),
                "pymatgen_modulus_GPa": pymatgen_modulus,
                "abs_delta_GPa": delta,
                "passed": check,
            }
        )
    return {
        "input_cif": cif_path.relative_to(REPOSITORY_ROOT).as_posix(),
        "input_sha256": sha256_file(cif_path),
        "synthetic_stiffness_GPa": [list(row) for row in CUBIC_STIFFNESS_GPA],
        "voigt_order": ["11", "22", "33", "23", "13", "12"],
        "shear_convention": "engineering shear strain",
        "comparison_tolerances": {
            "absolute_GPa": ELASTIC_ABSOLUTE_TOLERANCE_GPA,
            "relative": ELASTIC_RELATIVE_TOLERANCE,
            "acceptance": "abs(delta) <= max(absolute_GPa, relative * abs(pymatgen))",
        },
        "directions": rows,
        "passed": passed,
    }


def _markdown_report(report: Mapping[str, Any]) -> str:
    lines = [
        "# Independent pymatgen reference comparison",
        "",
        f"Generated: `{report['generated_at_utc']}`",
        "",
        f"Overall acceptance: **{'PASS' if report['all_acceptance_checks_passed'] else 'FAIL'}**",
        "",
        "This receipt records independent software comparisons on explicitly synthetic benchmark fixtures. "
        "It is not experimental validation, a real-material property claim, or external-user evidence.",
        "",
        "## Software and settings",
        "",
        f"- Python: `{report['software']['python']}`",
        f"- Comparison script SHA-256: `{report['software']['comparison_script_sha256']}`",
        f"- Gemmi: `{report['software']['gemmi']}`",
        f"- pymatgen: `{report['software']['pymatgen']}`",
        f"- Radiation: Cu Kα effective wavelength `{WAVELENGTH_A} Å`",
        f"- 2θ range: `{TWO_THETA_RANGE_DEG[0]}–{TWO_THETA_RANGE_DEG[1]}°`",
        f"- Peak grouping/matching: `|Δd| ≤ {D_SPACING_TOLERANCE_A:g} Å`; geometry acceptance also requires "
        f"`|Δ2θ| ≤ {TWO_THETA_TOLERANCE_DEG:g}°`.",
        "- Diffraction intensities use each engine's unscaled theoretical pattern, are grouped at coincident d, "
        "and are separately normalized to a per-case maximum of 100; differences are diagnostic only.",
        "",
        "## Diffraction peak positions and selection rules",
        "",
        "| Synthetic CIF | Gemmi families | pymatgen groups | Matched d groups | max abs Δd (Å) | max abs Δ2θ (°) | position | selection | max intensity difference (points) |",
        "|---|---:|---:|---:|---:|---:|:---:|:---:|---:|",
    ]
    for name, case in report["diffraction_cases"].items():
        lines.append(
            f"| `{case['input_cif']}` ({name}) | {case['gemmi_reflection_family_count']} | "
            f"{case['pymatgen_d_spacing_group_count']} | {case['matched_d_spacing_group_count']} | "
            f"{case['position_max_abs_delta_d_A']:.3g} | "
            f"{case['position_max_abs_delta_two_theta_deg']:.3g} | "
            f"{'PASS' if case['position_passed'] else 'FAIL'} | "
            f"{'PASS' if case['selection_rules']['passed'] else 'FAIL'} | "
            f"{case['intensity_comparison']['max_abs_delta_relative_intensity_percentage_points']:.4g} |"
        )
    lines.extend(
        [
            "",
            "The comparison groups lines by d-spacing rather than requiring identical representative hkl labels. "
            "Pymatgen may return a single pattern peak containing several hkl families where DiffractScout "
            "returns separate family rows; the comparison therefore sums coincident-family intensities before "
            "per-case normalization.",
            "",
            "## Cubic directional Young's modulus",
            "",
            f"The same synthetic stiffness matrix in GPa is interpreted with Voigt order `{report['elasticity']['voigt_order']}` "
            f"and {report['elasticity']['shear_convention']}. Acceptance is "
            f"`|ΔE| ≤ max({ELASTIC_ABSOLUTE_TOLERANCE_GPA:g} GPa, "
            f"{ELASTIC_RELATIVE_TOLERANCE:g} × |E_pymatgen|)`.",
            "",
            "| Plane normal | DiffractScout (GPa) | pymatgen (GPa) | abs ΔE (GPa) | Result |",
            "|---|---:|---:|---:|:---:|",
        ]
    )
    for row in report["elasticity"]["directions"]:
        lines.append(
            f"| `{row['hkl_normal']}` | {row['gemmi_project_modulus_GPa']:.12g} | "
            f"{row['pymatgen_modulus_GPa']:.12g} | {row['abs_delta_GPa']:.3g} | "
            f"{'PASS' if row['passed'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "Install the optional Materials Project dependencies, then run from the repository root:",
            "",
            "```sh",
            "python scripts/compare_reference_engines.py --output validation_cases/independent_engines",
            "```",
            "",
            "The tracked JSON receipt records relative CIF paths and SHA-256 hashes, software versions, "
            "thresholds, per-peak results, selection-rule outcomes, and tensor results. The script exits "
            "nonzero if peak geometry/selection or elastic acceptance checks fail. Intensity differences do "
            "not affect the exit status.",
            "",
        ]
    )
    return "\n".join(lines)


def run_comparison(output_dir: str | Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    """Run all synthetic cross-engine comparisons and write JSON/Markdown receipts."""

    if str(REPOSITORY_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
    try:
        from diffractscout import __version__ as diffractscout_version
        from diffractscout.diffraction import simulate_powder_pattern
        from diffractscout.elasticity import validate_elastic_tensor, young_modulus_hkl_normal_GPa
        from diffractscout.models import AnalysisSettings
        from diffractscout.structure import load_structure
        from pymatgen.analysis.diffraction.xrd import XRDCalculator
        from pymatgen.core import Structure
        from pymatgen.core.elasticity import ElasticTensor
    except ImportError as exc:
        raise RuntimeError(
            "The independent comparison needs pymatgen. Install the project's optional "
            "Materials Project dependencies with `pip install -e '.[mp]'`."
        ) from exc

    expectations_path = BENCHMARK_ROOT / "expectations.json"
    expectations = json.loads(expectations_path.read_text(encoding="utf-8"))
    cases = _validate_expectations(expectations)

    diffraction_cases: dict[str, Any] = {}
    for case_name, specification in cases.items():
        cif_path = BENCHMARK_ROOT / str(specification["file"])
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            case = _compare_case(
                case_name,
                specification,
                cif_path,
                xrd_calculator_type=XRDCalculator,
                structure_type=Structure,
                load_structure_fn=load_structure,
                simulate_powder_pattern_fn=simulate_powder_pattern,
                analysis_settings_type=AnalysisSettings,
            )
        case["pymatgen_parse_warnings"] = list(
            dict.fromkeys(str(item.message) for item in caught_warnings)
        )
        diffraction_cases[case_name] = case

    elasticity = _cubic_elasticity_comparison(
        pymatgen_elastic_tensor_type=ElasticTensor,
        validate_elastic_tensor_fn=validate_elastic_tensor,
        project_young_modulus_fn=young_modulus_hkl_normal_GPa,
    )
    all_acceptance_checks_passed = (
        all(case["position_passed"] and case["selection_rules"]["passed"] for case in diffraction_cases.values())
        and elasticity["passed"]
    )
    try:
        gemmi_version = importlib.metadata.version("gemmi")
    except importlib.metadata.PackageNotFoundError:
        gemmi_version = "unknown"
    try:
        pymatgen_version = importlib.metadata.version("pymatgen")
    except importlib.metadata.PackageNotFoundError:
        pymatgen_version = "unknown"
    report: dict[str, Any] = {
        "schema": "diffractscout_independent_reference_engine_comparison_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "all_acceptance_checks_passed": all_acceptance_checks_passed,
        "synthetic_inputs_only": True,
        "software": {
            "diffractscout": diffractscout_version,
            "comparison_script_sha256": sha256_file(Path(__file__).resolve()),
            "python": ".".join(str(value) for value in sys.version_info[:3]),
            "gemmi": gemmi_version,
            "pymatgen": pymatgen_version,
        },
        "settings": {
            "radiation": "Cu Kα effective single wavelength",
            "wavelength_A": WAVELENGTH_A,
            "two_theta_range_deg": list(TWO_THETA_RANGE_DEG),
            "d_spacing_merge_and_match_tolerance_A": D_SPACING_TOLERANCE_A,
            "two_theta_acceptance_tolerance_deg": TWO_THETA_TOLERANCE_DEG,
            "intensity_comparison": "unscaled calculated peaks summed at coincident d then normalized per case to maximum 100; diagnostic only",
        },
        "expectations": {
            "path": expectations_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": sha256_file(expectations_path),
        },
        "diffraction_cases": diffraction_cases,
        "elasticity": elasticity,
    }

    output = Path(output_dir)
    if not output.is_absolute():
        output = (REPOSITORY_ROOT / output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "reference_engine_comparison.json"
    markdown_path = output / "reference_engine_comparison.md"
    report["output_files"] = [
        json_path.relative_to(REPOSITORY_ROOT).as_posix()
        if json_path.is_relative_to(REPOSITORY_ROOT)
        else json_path.name,
        markdown_path.relative_to(REPOSITORY_ROOT).as_posix()
        if markdown_path.is_relative_to(REPOSITORY_ROOT)
        else markdown_path.name,
    ]
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="directory for the JSON and Markdown receipts (default: %(default)s)",
    )
    arguments = parser.parse_args(argv)
    try:
        report = run_comparison(arguments.output)
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(
        f"Independent reference comparison: "
        f"{'PASS' if report['all_acceptance_checks_passed'] else 'FAIL'}; "
        f"{len(report['diffraction_cases'])} diffraction fixtures and cubic elasticity."
    )
    for relative_path in report["output_files"]:
        print(f"  {relative_path}")
    return 0 if report["all_acceptance_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
