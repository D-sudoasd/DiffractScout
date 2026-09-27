"""Pure views over peak/structure records for the default peak workbook."""

from __future__ import annotations

import re
from typing import Any

from .models import XrdPhase

DEFAULT_OVERLAP_DELTA_TWO_THETA_DEG = 0.05
DEFAULT_OVERLAP_DELTA_D_A = 0.005

WORKING_PEAK_HEADERS = [
    "相名",
    "晶面 hkl",
    "d 间距 (Å)",
    "2θ 当前设置 (°)",
    "相对强度",
    "多重性",
    "提示",
    "晶面法向杨氏模量 (GPa)",
    "弹性常数状态",
]

STRUCTURE_HEADERS = [
    "phase_name",
    "cif_name",
    "formula",
    "a_A",
    "b_A",
    "c_A",
    "alpha_deg",
    "beta_deg",
    "gamma_deg",
    "cell_volume_A3",
    "space_group_from_cif",
    "space_group_detected",
    "space_group_status",
    "occupancy_status",
    "occupancy_summary",
    "occupancy_sites",
    "warnings",
    "error",
]

OVERLAP_HEADERS = [
    "phase_a",
    "hkl_a",
    "d_A_a",
    "two_theta_a_deg",
    "Irel_a",
    "phase_b",
    "hkl_b",
    "d_A_b",
    "two_theta_b_deg",
    "Irel_b",
    "delta_two_theta_deg",
    "delta_d_A",
    "match_by",
]


def _normalized_symbol(symbol: str | None) -> str:
    """Collapse equivalent Hermann–Mauguin spellings to one token."""

    if not symbol:
        return ""
    text = str(symbol).casefold()
    text = re.sub(r"_+", "", text)
    return re.sub(r"[\s\-/\\]+", "", text)


def space_group_symbols_equivalent(left: str | None, right: str | None) -> bool:
    left_norm = _normalized_symbol(left)
    right_norm = _normalized_symbol(right)
    return bool(left_norm) and left_norm == right_norm


def working_peak_rows(combined_rows: list[dict[str, Any]]) -> list[list[Any]]:
    """Compact working peak table for the default workbook."""

    rows: list[list[Any]] = [WORKING_PEAK_HEADERS]
    for row in combined_rows:
        rows.append(
            [
                row.get("phase_name", ""),
                row.get("hkl", ""),
                row.get("d_A", ""),
                row.get("two_theta_current_deg", ""),
                row.get("relative_intensity", ""),
                row.get("multiplicity", ""),
                row.get("warnings", ""),
                row.get("young_modulus_hkl_normal_GPa", ""),
                row.get("elastic_status", ""),
            ]
        )
    return rows


def _space_group_status(crystal) -> str:
    cif_symbol = crystal.validation_report.space_group_from_cif
    detected = crystal.detected_space_group_symbol
    cif_number = crystal.validation_report.space_group_number_from_cif
    detected_number = crystal.detected_space_group_number
    cif_norm = _normalized_symbol(cif_symbol)
    detected_norm = _normalized_symbol(detected)
    if not cif_norm and not detected_norm and cif_number is None and detected_number is None:
        return "unknown"
    numbers_agree = (
        cif_number is not None
        and detected_number is not None
        and int(cif_number) == int(detected_number)
        and int(detected_number) > 1
    )
    if space_group_symbols_equivalent(cif_symbol, detected) or numbers_agree:
        return "match"
    if not cif_norm or not detected_norm:
        return "partial"
    return "mismatch"


def _occupancy_sites(crystal) -> str:
    structure = getattr(crystal, "pymatgen_structure", None)
    if structure is None:
        return ""
    bits: list[str] = []
    for site in structure:
        species = getattr(site, "species", None)
        if species is None:
            continue
        label = str(getattr(site, "label", "") or "").strip()
        for specie, occupancy in species.items():
            occ = float(occupancy)
            if abs(occ - 1.0) <= 1e-8:
                continue
            symbol = getattr(specie, "symbol", str(specie))
            prefix = label or symbol
            bits.append(f"{prefix}:{symbol}={occ:.4g}")
    return "; ".join(bits)


def structure_status_rows(phases: list[XrdPhase]) -> list[list[Any]]:
    """Per-CIF lattice, space-group, and occupancy status."""

    rows: list[list[Any]] = [STRUCTURE_HEADERS]
    for phase in phases:
        crystal = phase.crystal
        if crystal is None:
            rows.append(
                [
                    phase.phase_name,
                    phase.cif_path.name,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "unknown",
                    "unavailable",
                    "",
                    "",
                    " | ".join(phase.warning_messages),
                    phase.error or "",
                ]
            )
            continue
        a, b, c, alpha, beta, gamma = crystal.cell_parameters
        lattice = crystal.pymatgen_structure.lattice
        occupancy_status = "partial" if crystal.has_partial_occupancy else "full"
        rows.append(
            [
                phase.phase_name,
                phase.cif_path.name,
                crystal.formula,
                float(a),
                float(b),
                float(c),
                float(alpha),
                float(beta),
                float(gamma),
                float(lattice.volume),
                crystal.validation_report.space_group_from_cif or "",
                crystal.detected_space_group_symbol or "",
                _space_group_status(crystal),
                occupancy_status,
                crystal.validation_report.occupancy_summary,
                _occupancy_sites(crystal),
                " | ".join(phase.warning_messages),
                phase.error or "",
            ]
        )
    return rows


def overlap_peak_records(
    combined_rows: list[dict[str, Any]],
    *,
    delta_two_theta_deg: float = DEFAULT_OVERLAP_DELTA_TWO_THETA_DEG,
    delta_d_A: float = DEFAULT_OVERLAP_DELTA_D_A,
) -> list[dict[str, Any]]:
    """Return peak pairs from different phases within the stated windows."""

    usable: list[dict[str, Any]] = []
    for row in combined_rows:
        try:
            two_theta = float(row.get("two_theta_current_deg"))
            d_spacing = float(row.get("d_A"))
        except (TypeError, ValueError):
            continue
        if two_theta != two_theta or d_spacing != d_spacing:
            continue
        usable.append(row)

    records: list[dict[str, Any]] = []
    for left_index, left in enumerate(usable):
        left_phase = str(left.get("phase_name") or "")
        for right in usable[left_index + 1 :]:
            right_phase = str(right.get("phase_name") or "")
            if not left_phase or left_phase == right_phase:
                continue
            two_theta_delta = abs(float(left["two_theta_current_deg"]) - float(right["two_theta_current_deg"]))
            d_delta = abs(float(left["d_A"]) - float(right["d_A"]))
            by_two_theta = two_theta_delta <= float(delta_two_theta_deg)
            by_d = d_delta <= float(delta_d_A)
            if not by_two_theta and not by_d:
                continue
            if by_two_theta and by_d:
                match_by = "two_theta+d"
            elif by_two_theta:
                match_by = "two_theta"
            else:
                match_by = "d"
            records.append(
                {
                    "phase_a": left_phase,
                    "hkl_a": left.get("hkl", ""),
                    "d_A_a": float(left["d_A"]),
                    "two_theta_a_deg": float(left["two_theta_current_deg"]),
                    "Irel_a": left.get("relative_intensity", ""),
                    "phase_b": right_phase,
                    "hkl_b": right.get("hkl", ""),
                    "d_A_b": float(right["d_A"]),
                    "two_theta_b_deg": float(right["two_theta_current_deg"]),
                    "Irel_b": right.get("relative_intensity", ""),
                    "delta_two_theta_deg": two_theta_delta,
                    "delta_d_A": d_delta,
                    "match_by": match_by,
                }
            )
    return records


def overlap_sheet_rows(
    combined_rows: list[dict[str, Any]],
    phases: list[XrdPhase],
    *,
    delta_two_theta_deg: float = DEFAULT_OVERLAP_DELTA_TWO_THETA_DEG,
    delta_d_A: float = DEFAULT_OVERLAP_DELTA_D_A,
) -> list[list[Any]] | None:
    """Build the Overlap sheet when two or more phases exported peaks."""

    exporting = [phase for phase in phases if phase.result is not None and phase.result.peaks]
    if len(exporting) < 2:
        return None
    records = overlap_peak_records(
        combined_rows,
        delta_two_theta_deg=delta_two_theta_deg,
        delta_d_A=delta_d_A,
    )
    rows: list[list[Any]] = [
        ["overlap_rule", "pairs from different phases with Δ2θ or Δd inside the stated window"],
        ["delta_two_theta_deg", float(delta_two_theta_deg)],
        ["delta_d_A", float(delta_d_A)],
        ["pair_count", len(records)],
        [],
        OVERLAP_HEADERS,
    ]
    for record in records:
        rows.append([record[header] for header in OVERLAP_HEADERS])
    return rows


def should_include_overlap_sheet(phases: list[XrdPhase]) -> bool:
    return sum(1 for phase in phases if phase.result is not None and phase.result.peaks) >= 2
