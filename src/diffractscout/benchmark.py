"""Deterministic analytic benchmarks for diffraction and directional elasticity.

The benchmark suite uses synthetic structures with closed-form selection rules,
plane spacings, multiplicities, structure factors, and cubic-elasticity
solutions. It is intended to detect scientific regressions independently of
the end-to-end demonstration bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any, Iterable
from uuid import uuid4

import gemmi
import numpy as np

from .diffraction import simulate_powder_pattern
from .elasticity import validate_elastic_tensor, young_modulus_hkl_normal_GPa
from .models import AnalysisSettings, ReflectionRecord
from .structure import load_structure
from .utils import package_versions, runtime_environment, sha256_file, utc_now_iso, write_json

BENCHMARK_SCHEMA = "diffractscout_analytic_benchmark_v1"
BENCHMARK_MANIFEST_SCHEMA = "diffractscout_benchmark_manifest_v1"


@dataclass(frozen=True)
class BenchmarkCheck:
    case: str
    check: str
    passed: bool
    observed: Any
    expected: Any
    tolerance: str = "exact"
    note: str = ""


def _hkl_key(hkl: Iterable[int]) -> str:
    return " ".join(str(int(value)) for value in hkl)


def _reflection_map(reflections: Iterable[ReflectionRecord]) -> dict[tuple[int, int, int], ReflectionRecord]:
    return {item.hkl: item for item in reflections}


def _close(observed: float, expected: float, *, rtol: float, atol: float = 0.0) -> bool:
    return bool(np.isclose(observed, expected, rtol=rtol, atol=atol))


def _add_exact(
    checks: list[BenchmarkCheck],
    case: str,
    name: str,
    observed: Any,
    expected: Any,
    *,
    note: str = "",
) -> None:
    checks.append(
        BenchmarkCheck(case, name, observed == expected, observed, expected, "exact", note)
    )


def _add_close(
    checks: list[BenchmarkCheck],
    case: str,
    name: str,
    observed: float,
    expected: float,
    *,
    rtol: float,
    atol: float = 0.0,
    note: str = "",
) -> None:
    checks.append(
        BenchmarkCheck(
            case,
            name,
            _close(observed, expected, rtol=rtol, atol=atol),
            float(observed),
            float(expected),
            f"rtol={rtol:g}, atol={atol:g}",
            note,
        )
    )


def _copy_benchmark_data(destination: Path) -> dict[str, dict[str, Any]]:
    resource_root = files("diffractscout").joinpath("benchmark_data")
    expectations = json.loads(resource_root.joinpath("expectations.json").read_text(encoding="utf-8"))
    if expectations.get("schema") != "diffractscout_analytic_expectations_v1":
        raise RuntimeError("Unknown analytic benchmark expectation schema.")
    destination.mkdir(parents=True, exist_ok=True)
    destination.joinpath("expectations.json").write_text(
        json.dumps(expectations, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for case in expectations["cases"].values():
        filename = str(case["file"])
        destination.joinpath(filename).write_text(
            resource_root.joinpath(filename).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return expectations["cases"]


def _xray_form_factor(symbol: str, d_spacing_A: float) -> float:
    return float(
        gemmi.Element(symbol).it92.calculate_sf(1.0 / (4.0 * d_spacing_A**2))
    )


def _check_crystal_case(
    case_name: str,
    specification: dict[str, Any],
    fixture_dir: Path,
) -> list[BenchmarkCheck]:
    checks: list[BenchmarkCheck] = []
    structure = load_structure(fixture_dir / str(specification["file"]))
    analysis = simulate_powder_pattern(
        structure,
        AnalysisSettings(
            two_theta_min_deg=5.0,
            two_theta_max_deg=120.0,
            step_deg=0.02,
            include_elasticity=False,
        ),
    )
    reflection_by_hkl = _reflection_map(analysis.reflections)
    observed_first = [list(item.hkl) for item in analysis.reflections[:3]]
    _add_exact(
        checks,
        case_name,
        "first three allowed reflection families",
        observed_first,
        specification["first_allowed"],
    )
    for forbidden in specification.get("forbidden", []):
        hkl = tuple(int(value) for value in forbidden)
        _add_exact(
            checks,
            case_name,
            f"systematic absence {_hkl_key(hkl)}",
            hkl in reflection_by_hkl,
            False,
        )
    for key, expected in specification["multiplicity"].items():
        hkl = tuple(int(value) for value in key.split())
        observed = reflection_by_hkl[hkl].multiplicity
        _add_exact(
            checks,
            case_name,
            f"powder multiplicity {key}",
            observed,
            int(expected),
        )

    first_hkl = tuple(int(value) for value in specification["first_allowed"][0])
    first = reflection_by_hkl[first_hkl]
    lattice_a = float(specification["lattice_a_A"])
    expected_d = lattice_a / math.sqrt(sum(value * value for value in first_hkl))
    _add_close(
        checks,
        case_name,
        f"cubic d spacing {_hkl_key(first_hkl)}",
        first.d_spacing_A,
        expected_d,
        rtol=1e-12,
    )
    _add_close(
        checks,
        case_name,
        f"q=2pi/d {_hkl_key(first_hkl)}",
        first.q_invA,
        2.0 * math.pi / expected_d,
        rtol=1e-12,
    )

    # The formulas below are analytic lattice sums for the synthetic bases.
    if case_name == "simple_cubic_al":
        expected_f = _xray_form_factor("Al", first.d_spacing_A)
        expected_sq = expected_f**2
        target = first
    elif case_name == "bcc_fe":
        target = reflection_by_hkl[(1, 1, 0)]
        expected_f = _xray_form_factor("Fe", target.d_spacing_A)
        expected_sq = (2.0 * expected_f) ** 2
    elif case_name == "fcc_al":
        target = reflection_by_hkl[(1, 1, 1)]
        expected_f = _xray_form_factor("Al", target.d_spacing_A)
        expected_sq = (4.0 * expected_f) ** 2
    elif case_name == "nacl":
        for hkl, sign in (((1, 1, 1), -1.0), ((2, 0, 0), 1.0)):
            target = reflection_by_hkl[hkl]
            f_na = _xray_form_factor("Na", target.d_spacing_A)
            f_cl = _xray_form_factor("Cl", target.d_spacing_A)
            expected_sq = (4.0 * (f_na + sign * f_cl)) ** 2
            _add_close(
                checks,
                case_name,
                f"NaCl analytic |F|^2 {_hkl_key(hkl)}",
                target.structure_factor_sq,
                expected_sq,
                rtol=1e-7,
                note="F=4(f_Na-f_Cl) for all-odd and F=4(f_Na+f_Cl) for all-even reflections.",
            )
        target = None
        expected_sq = 0.0
    else:  # pragma: no cover - protected by the packaged expectation schema
        raise RuntimeError(f"Unknown benchmark case: {case_name}")

    if target is not None:
        _add_close(
            checks,
            case_name,
            f"analytic |F|^2 {_hkl_key(target.hkl)}",
            target.structure_factor_sq,
            expected_sq,
            rtol=1e-7,
        )

    if case_name == "bcc_fe":
        all_obey = all((item.h + item.k + item.l) % 2 == 0 for item in analysis.reflections)
        _add_exact(checks, case_name, "all BCC reflections obey h+k+l even", all_obey, True)
    if case_name in {"fcc_al", "nacl"}:
        all_obey = all(
            (abs(item.h) % 2 == abs(item.k) % 2 == abs(item.l) % 2)
            for item in analysis.reflections
        )
        _add_exact(
            checks,
            case_name,
            "all F-centred reflections have unmixed parity",
            all_obey,
            True,
        )
    _add_close(
        checks,
        case_name,
        "normalized profile maximum",
        float(np.max(analysis.intensity_profile)),
        100.0,
        rtol=1e-12,
    )
    return checks


def _cubic_directional_modulus(
    c11: float,
    c12: float,
    c44: float,
    direction: tuple[float, float, float],
) -> float:
    denominator = (c11 - c12) * (c11 + 2.0 * c12)
    s11 = (c11 + c12) / denominator
    s12 = -c12 / denominator
    s44 = 1.0 / c44
    l_dir, m_dir, n_dir = direction
    invariant = (
        l_dir * l_dir * m_dir * m_dir
        + m_dir * m_dir * n_dir * n_dir
        + n_dir * n_dir * l_dir * l_dir
    )
    inverse_modulus = s11 - 2.0 * (s11 - s12 - 0.5 * s44) * invariant
    return 1.0 / inverse_modulus


def _check_cubic_elasticity() -> list[BenchmarkCheck]:
    c11, c12, c44 = 250.0, 150.0, 100.0
    matrix = np.asarray(
        [
            [c11, c12, c12, 0, 0, 0],
            [c12, c11, c12, 0, 0, 0],
            [c12, c12, c11, 0, 0, 0],
            [0, 0, 0, c44, 0, 0],
            [0, 0, 0, 0, c44, 0],
            [0, 0, 0, 0, 0, c44],
        ],
        dtype=float,
    )
    tensor = validate_elastic_tensor(matrix, nature_of_data="analytic_test_fixture")
    cell = gemmi.UnitCell(4.0, 4.0, 4.0, 90.0, 90.0, 90.0)
    checks: list[BenchmarkCheck] = []
    for hkl in ((1, 0, 0), (1, 1, 0), (1, 1, 1)):
        direction = np.asarray(hkl, dtype=float)
        direction /= np.linalg.norm(direction)
        expected = _cubic_directional_modulus(
            c11,
            c12,
            c44,
            tuple(float(value) for value in direction),
        )
        observed = young_modulus_hkl_normal_GPa(tensor, cell, hkl)
        if observed is None:
            checks.append(
                BenchmarkCheck(
                    "cubic_elasticity",
                    f"Young modulus {_hkl_key(hkl)}",
                    False,
                    None,
                    expected,
                    "rtol=1e-12",
                )
            )
        else:
            _add_close(
                checks,
                "cubic_elasticity",
                f"Young modulus {_hkl_key(hkl)}",
                observed,
                expected,
                rtol=1e-12,
            )
    return checks


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# DiffractScout analytic benchmark report",
        "",
        f"- Generated: `{payload['generated_at_utc']}`",
        f"- Result: **{'PASS' if payload['all_passed'] else 'FAIL'}**",
        f"- Checks: {payload['passed_checks']}/{payload['total_checks']} passed",
        "- Data: synthetic analytic fixtures; no experimental performance claim",
        "",
        "| Case | Check | Result | Observed | Expected | Tolerance |",
        "|---|---|:---:|---:|---:|---|",
    ]
    for check in payload["checks"]:
        observed = json.dumps(check["observed"], ensure_ascii=False)
        expected = json.dumps(check["expected"], ensure_ascii=False)
        label = str(check["check"]).replace("|", "\\|")
        lines.append(
            f"| {check['case']} | {label} | "
            f"{'PASS' if check['passed'] else 'FAIL'} | `{observed}` | `{expected}` | "
            f"{check['tolerance']} |"
        )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "The suite checks crystallographic selection rules, powder multiplicities, cubic plane spacing, "
            "the q definition, analytic X-ray lattice structure factors, profile normalization, and the "
            "closed-form directional Young's modulus of a cubic stiffness tensor. It does not validate "
            "experimental instrument models, phase identification, or refinement.",
            "",
        ]
    )
    return "\n".join(lines)


def _build_manifest(root: Path, *, all_passed: bool) -> Path:
    entries = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "benchmark_manifest.json":
            continue
        relative = path.relative_to(root).as_posix()
        entries.append(
            {"path": relative, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    return write_json(
        root / "benchmark_manifest.json",
        {
            "schema": BENCHMARK_MANIFEST_SCHEMA,
            "all_passed": all_passed,
            "files": entries,
        },
    )


def verify_benchmark_bundle(root: str | Path) -> dict[str, Any]:
    directory = Path(root).expanduser().resolve()
    manifest = directory / "benchmark_manifest.json"
    errors: list[str] = []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "manifest": str(manifest), "errors": [str(exc)]}
    if payload.get("schema") != BENCHMARK_MANIFEST_SCHEMA:
        errors.append("Unknown benchmark manifest schema.")
    listed: set[str] = set()
    for entry in payload.get("files", []):
        relative = str(entry.get("path") or "")
        pure = PurePosixPath(relative)
        if not relative or pure.is_absolute() or ".." in pure.parts:
            errors.append(f"Unsafe manifest path: {relative!r}")
            continue
        if relative in listed:
            errors.append(f"Duplicate manifest path: {relative}")
            continue
        listed.add(relative)
        path = directory.joinpath(*pure.parts)
        if path.is_symlink():
            errors.append(f"Symbolic links are not allowed: {relative}")
            continue
        if not path.is_file():
            errors.append(f"Missing file: {relative}")
            continue
        if path.stat().st_size != int(entry.get("size_bytes", -1)):
            errors.append(f"Size mismatch: {relative}")
        if sha256_file(path) != str(entry.get("sha256") or ""):
            errors.append(f"SHA-256 mismatch: {relative}")
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != "benchmark_manifest.json"
    }
    for extra in sorted(actual - listed):
        errors.append(f"Unlisted file: {extra}")
    return {
        "ok": not errors,
        "manifest": str(manifest),
        "all_passed": bool(payload.get("all_passed")),
        "errors": errors,
    }


def _prepare_target(output_dir: str | Path, *, overwrite: bool) -> Path:
    raw = Path(output_dir).expanduser()
    if raw.is_symlink():
        raise FileExistsError(f"Refusing to use a symbolic-link benchmark directory: {raw}")
    target = raw.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not target.is_dir():
        raise FileExistsError(f"Benchmark output exists and is not a directory: {target}")
    if target.exists() and any(target.iterdir()):
        if not overwrite:
            raise FileExistsError(
                f"Benchmark output is not empty: {target}. Choose a new directory or pass overwrite=True."
            )
        existing = verify_benchmark_bundle(target)
        if not existing["ok"]:
            raise FileExistsError(
                "Refusing to overwrite an invalid or unrelated benchmark directory: "
                + "; ".join(existing["errors"][:5])
            )
    return target


def _commit_directory(target: Path, staging: Path) -> None:
    backup: Path | None = None
    try:
        if target.exists():
            backup = target.with_name(f".{target.name}.backup-{uuid4().hex}")
            target.replace(backup)
        staging.replace(target)
    except Exception:
        if not target.exists() and backup is not None and backup.exists():
            backup.replace(target)
        raise
    else:
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)


def run_reference_benchmarks(
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Run all packaged analytic benchmarks and atomically write a result bundle."""

    target = _prepare_target(output_dir, overwrite=overwrite)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.benchmark-", dir=str(target.parent))
    ).resolve()
    try:
        fixture_dir = staging / "fixtures"
        cases = _copy_benchmark_data(fixture_dir)
        checks: list[BenchmarkCheck] = []
        for case_name, specification in cases.items():
            try:
                checks.extend(
                    _check_crystal_case(case_name, specification, fixture_dir)
                )
            except Exception as exc:
                checks.append(
                    BenchmarkCheck(
                        case_name,
                        "benchmark execution",
                        False,
                        type(exc).__name__,
                        "successful execution",
                        note=str(exc),
                    )
                )
        checks.extend(_check_cubic_elasticity())
        passed = sum(item.passed for item in checks)
        payload = {
            "schema": BENCHMARK_SCHEMA,
            "generated_at_utc": utc_now_iso(),
            "synthetic_data": True,
            "all_passed": passed == len(checks),
            "passed_checks": passed,
            "total_checks": len(checks),
            "checks": [item.__dict__ for item in checks],
            "software_versions": package_versions(
                ("diffractscout", "gemmi", "numpy", "spglib")
            ),
            "runtime_environment": runtime_environment(),
        }
        write_json(staging / "benchmark_report.json", payload)
        (staging / "benchmark_report.md").write_text(
            _markdown_report(payload), encoding="utf-8"
        )
        _build_manifest(staging, all_passed=payload["all_passed"])
        verification = verify_benchmark_bundle(staging)
        if not verification["ok"]:
            raise RuntimeError(
                "Analytic benchmark bundle failed integrity verification: "
                + "; ".join(verification["errors"])
            )
        _commit_directory(target, staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    payload["output_dir"] = str(target)
    payload["manifest_path"] = str(target / "benchmark_manifest.json")
    return payload
