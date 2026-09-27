from __future__ import annotations

import csv
import html
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from .hkl import format_hkl, plane_hkl_for_normal
from .models import ExperimentalPattern, Cif2PeaksExportPayload, Cif2PeaksPeakRow, XrdAxisMode, XrdPhase
from .service import phase_peak_rows
from .utils import friendly_cif_issue_message, now_iso, package_versions
from .workbook_views import (
    STRUCTURE_HEADERS,
    WORKING_PEAK_HEADERS,
    overlap_sheet_rows,
    structure_status_rows,
    working_peak_rows,
)


QUANT_PHASE_ANALYSIS_HEADERS = [
    "inverse_material_scattering_factor_1_over_R_hkl",
    "inverse_material_scattering_factor_1_over_R_hkl_no_lp",
    "phase_relative_R_hkl_pct",
    "phase_relative_R_hkl_no_lp_pct",
    "phase_peak_rank_by_R_hkl",
    "phase_peak_rank_by_R_hkl_no_lp",
    "phase_peak_rank_by_relative_intensity",
    "coincident_hkl_family_count",
    "is_multi_family_peak",
    "mean_structure_factor_sq_per_multiplicity",
    "mean_structure_factor_abs_per_multiplicity",
    "sin_theta",
    "cos_theta",
    "sin_theta_over_lambda_1_over_A",
    "sin2_theta_over_lambda2_1_over_A2",
    "phase_density_g_cm3",
    "phase_formula_weight_g_mol",
    "phase_cell_volume_A3",
]


PEAK_HEADERS = [
    "phase_name",
    "cif_name",
    "formula",
    "space_group",
    "hkl",
    "d_A",
    "two_theta_current_deg",
    "relative_intensity",
    "material_scattering_factor_R_hkl",
    "material_scattering_factor_R_hkl_no_lp",
    *QUANT_PHASE_ANALYSIS_HEADERS,
    "theoretical_intensity_unscaled",
    "cell_volume_A3",
    "lp_factor",
    "multiplicity_structure_factor_sq",
    "r_hkl_model_note",
    "multiplicity",
    "warnings",
    "family_label",
    "h",
    "k",
    "i",
    "l",
    "g_1_over_A",
    "q_1_over_A",
    "theta_deg",
    "two_theta_cu_ka_deg",
    "space_group_from_cif",
    "space_group_detected",
    "young_modulus_hkl_normal_GPa",
    "elastic_status",
    "elastic_warning",
    "elastic_hkl_used",
    "elastic_family_count",
    "elastic_family_moduli_GPa",
    "elastic_modulus_note",
]

PEAK_REFERENCE_HEADERS = [
    "phase_name",
    "cif_name",
    "formula",
    "space_group",
    "hkl",
    "family_label",
    "d_A",
    "two_theta_deg",
    "two_theta_cu_ka_deg",
    "relative_intensity",
    "material_scattering_factor_R_hkl",
    "material_scattering_factor_R_hkl_no_lp",
    *QUANT_PHASE_ANALYSIS_HEADERS,
    "theoretical_intensity_unscaled",
    "cell_volume_A3",
    "lp_factor",
    "multiplicity_structure_factor_sq",
    "r_hkl_model_note",
    "multiplicity",
    "warnings",
    "space_group_from_cif",
    "space_group_detected",
]

PATTERN_PROFILE_HEADERS = [
    "phase_name",
    "cif_name",
    "x_axis_mode",
    "x",
    "relative_intensity",
    "two_theta_deg",
    "d_A",
    "q_1_over_A",
    "g_1_over_A",
]

ELASTIC_CONSTANTS_HEADERS = [
    "phase_name",
    "cif_name",
    "elastic_status",
    "elastic_warning",
    "unit",
    "source",
    "coordinate_frame",
    "C11",
    "C12",
    "C13",
    "C14",
    "C15",
    "C16",
    "C21",
    "C22",
    "C23",
    "C24",
    "C25",
    "C26",
    "C31",
    "C32",
    "C33",
    "C34",
    "C35",
    "C36",
    "C41",
    "C42",
    "C43",
    "C44",
    "C45",
    "C46",
    "C51",
    "C52",
    "C53",
    "C54",
    "C55",
    "C56",
    "C61",
    "C62",
    "C63",
    "C64",
    "C65",
    "C66",
]

BEGINNER_PEAK_HEADERS = [
    "相名",
    "CIF 文件",
    "化学式",
    "空间群",
    "晶面 hkl",
    "d 间距 (Å)",
    "2θ 当前设置 (°)",
    "2θ Cu Kα (°)",
    "相对强度",
    "多重性",
    "提示",
    "R因子 R_hkl",
    "1/R_hkl",
    "相内 R_hkl (%)",
    "R因子 R_hkl_no_LP",
    "1/R_hkl_no_LP",
    "相内 R_hkl_no_LP (%)",
    "未归一化理论强度",
    "晶胞体积 (Å^3)",
    "密度 (g/cm³)",
    "多族峰",
    "R因子说明",
    "晶面法向杨氏模量 (GPa)",
    "弹性常数状态",
]

HEADER_STYLE_ID = 1
KEY_HEADER_STYLE_ID = 2
PHASE_STYLE_FIRST_ID = 3
BEGINNER_KEY_COLUMN_INDEXES = {1, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 20, 21}
PHASE_FILL_COLORS = [
    "FFF2CC",
    "DDEBF7",
    "E2F0D9",
    "FCE4D6",
    "EADCF8",
    "D9EAD3",
    "F4CCCC",
    "D9E2F3",
]


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (float, np.floating)):
        resolved = float(value)
        return resolved if np.isfinite(resolved) else None
    if isinstance(value, np.integer):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _export_table_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, np.integer, np.floating)) and not np.isfinite(float(value)):
        return ""
    return value


def _row_to_dict(row: Cif2PeaksPeakRow) -> dict[str, Any]:
    return asdict(row)


def _format_peak_row_hkl(row: Cif2PeaksPeakRow) -> str:
    if row.i is None:
        return format_hkl((row.h, row.k, row.l))
    return format_hkl((row.h, row.k, row.i, row.l))


def _space_group_from_cif(phase: XrdPhase) -> str:
    if phase.crystal is None:
        return ""
    return phase.crystal.validation_report.space_group_from_cif or ""


def _space_group_detected(phase: XrdPhase) -> str:
    if phase.crystal is None:
        return ""
    return phase.crystal.detected_space_group_symbol or ""


def _row_hkl_tuple(row: Cif2PeaksPeakRow) -> tuple[int, ...]:
    if row.i is None:
        return row.h, row.k, row.l
    return row.h, row.k, row.i, row.l


def _blank_elastic_peak_values(status: str, warning: str = "") -> dict[str, Any]:
    return {
        "young_modulus_hkl_normal_GPa": "",
        "elastic_status": status,
        "elastic_warning": warning,
        "elastic_hkl_used": "",
        "elastic_family_count": "",
        "elastic_family_moduli_GPa": "",
        "elastic_modulus_note": "",
    }


def _format_hkl_for_normal(values: tuple[int, ...]) -> str:
    return format_hkl(plane_hkl_for_normal(values))


def _hkl_modulus_value(phase: XrdPhase, values: tuple[int, ...]) -> tuple[float | None, str, str]:
    if phase.elastic_constants is None or phase.crystal is None:
        return None, "", ""
    try:
        hkl_used = _format_hkl_for_normal(values)
        modulus = phase.elastic_constants.young_modulus_hkl_normal_GPa(phase.crystal.pymatgen_structure.lattice, values)
    except ValueError as exc:
        return None, "", str(exc)
    return modulus, hkl_used, "" if modulus is not None else "hkl normal Young's modulus could not be calculated."


def _format_family_moduli(phase: XrdPhase, family_hkls: tuple[tuple[int, ...], ...]) -> tuple[str, list[str]]:
    values: list[str] = []
    warnings: list[str] = []
    for hkl in family_hkls:
        modulus, _hkl_used, warning = _hkl_modulus_value(phase, hkl)
        if warning:
            warnings.append(f"{format_hkl(hkl)}: {warning}")
            values.append(f"{format_hkl(hkl)}=invalid")
        elif modulus is not None:
            values.append(f"{format_hkl(hkl)}={modulus:.6g}")
    return "; ".join(values), warnings


def _elastic_peak_values(phase: XrdPhase, row: Cif2PeaksPeakRow) -> dict[str, Any]:
    elastic = phase.elastic_constants
    family_hkls = row.family_hkls or (_row_hkl_tuple(row),)
    if elastic is None:
        values = _blank_elastic_peak_values("no_elastic_constants")
        values["elastic_family_count"] = len(family_hkls)
        return values
    warnings_text = " | ".join(elastic.warnings)
    if elastic.status == "invalid_elastic_constants":
        values = _blank_elastic_peak_values(elastic.status, warnings_text)
        values["elastic_family_count"] = len(family_hkls)
        return values
    if phase.crystal is None:
        values = _blank_elastic_peak_values(
            "invalid_elastic_constants",
            "No crystal lattice is available for hkl normal calculation.",
        )
        values["elastic_family_count"] = len(family_hkls)
        return values

    modulus, hkl_used, warning = _hkl_modulus_value(phase, _row_hkl_tuple(row))
    family_moduli, family_warnings = _format_family_moduli(phase, family_hkls)
    warning_parts = [item for item in [warnings_text, warning, *family_warnings] if item]
    note = ""
    if len(family_hkls) > 1:
        note = "multiple_hkl_families; primary value uses representative hkl"
    if modulus is None:
        values = _blank_elastic_peak_values(elastic.status, " | ".join(warning_parts))
        values.update(
            {
                "elastic_family_count": len(family_hkls),
                "elastic_family_moduli_GPa": family_moduli,
                "elastic_modulus_note": note,
            }
        )
        return values
    return {
        "young_modulus_hkl_normal_GPa": float(modulus),
        "elastic_status": elastic.status,
        "elastic_warning": " | ".join(warning_parts),
        "elastic_hkl_used": hkl_used,
        "elastic_family_count": len(family_hkls),
        "elastic_family_moduli_GPa": family_moduli,
        "elastic_modulus_note": note,
    }


def combined_peak_rows(phases: list[XrdPhase]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase in phases:
        crystal = phase.crystal
        warnings_text = " | ".join(phase.warning_messages)
        for row in phase_peak_rows(phase):
            values = _row_to_dict(row)
            values.update(
                {
                    "formula": "" if crystal is None else crystal.formula,
                    "space_group": phase.display_space_group,
                    "hkl": _format_peak_row_hkl(row),
                    "warnings": warnings_text,
                    "space_group_from_cif": _space_group_from_cif(phase),
                    "space_group_detected": _space_group_detected(phase),
                }
            )
            values.update(_elastic_peak_values(phase, row))
            rows.append(values)
    return rows


def peak_reference_rows(phases: list[XrdPhase]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase in phases:
        crystal = phase.crystal
        warnings_text = " | ".join(phase.warning_messages)
        for row in phase_peak_rows(phase):
            rows.append(
                {
                    "phase_name": phase.phase_name,
                    "cif_name": phase.cif_path.name,
                    "formula": "" if crystal is None else crystal.formula,
                    "space_group": phase.display_space_group,
                    "hkl": _format_peak_row_hkl(row),
                    "family_label": row.family_label,
                    "d_A": row.d_A,
                    "two_theta_deg": row.two_theta_current_deg,
                    "two_theta_cu_ka_deg": row.two_theta_cu_ka_deg,
                    "relative_intensity": row.relative_intensity,
                    "material_scattering_factor_R_hkl": row.material_scattering_factor_R_hkl,
                    "material_scattering_factor_R_hkl_no_lp": row.material_scattering_factor_R_hkl_no_lp,
                    "inverse_material_scattering_factor_1_over_R_hkl": row.inverse_material_scattering_factor_1_over_R_hkl,
                    "inverse_material_scattering_factor_1_over_R_hkl_no_lp": row.inverse_material_scattering_factor_1_over_R_hkl_no_lp,
                    "phase_relative_R_hkl_pct": row.phase_relative_R_hkl_pct,
                    "phase_relative_R_hkl_no_lp_pct": row.phase_relative_R_hkl_no_lp_pct,
                    "phase_peak_rank_by_R_hkl": row.phase_peak_rank_by_R_hkl,
                    "phase_peak_rank_by_R_hkl_no_lp": row.phase_peak_rank_by_R_hkl_no_lp,
                    "phase_peak_rank_by_relative_intensity": row.phase_peak_rank_by_relative_intensity,
                    "coincident_hkl_family_count": row.coincident_hkl_family_count,
                    "is_multi_family_peak": row.is_multi_family_peak,
                    "mean_structure_factor_sq_per_multiplicity": row.mean_structure_factor_sq_per_multiplicity,
                    "mean_structure_factor_abs_per_multiplicity": row.mean_structure_factor_abs_per_multiplicity,
                    "sin_theta": row.sin_theta,
                    "cos_theta": row.cos_theta,
                    "sin_theta_over_lambda_1_over_A": row.sin_theta_over_lambda_1_over_A,
                    "sin2_theta_over_lambda2_1_over_A2": row.sin2_theta_over_lambda2_1_over_A2,
                    "phase_density_g_cm3": row.phase_density_g_cm3,
                    "phase_formula_weight_g_mol": row.phase_formula_weight_g_mol,
                    "phase_cell_volume_A3": row.phase_cell_volume_A3,
                    "theoretical_intensity_unscaled": row.theoretical_intensity_unscaled,
                    "cell_volume_A3": row.cell_volume_A3,
                    "lp_factor": row.lp_factor,
                    "multiplicity_structure_factor_sq": row.multiplicity_structure_factor_sq,
                    "r_hkl_model_note": row.r_hkl_model_note,
                    "multiplicity": row.multiplicity,
                    "warnings": warnings_text,
                    "space_group_from_cif": _space_group_from_cif(phase),
                    "space_group_detected": _space_group_detected(phase),
                }
            )
    return rows


def export_peak_reference_csv(payload: Cif2PeaksExportPayload, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PEAK_REFERENCE_HEADERS)
        writer.writeheader()
        writer.writerows(
            {header: _export_table_value(row.get(header, "")) for header in PEAK_REFERENCE_HEADERS}
            for row in peak_reference_rows(payload.phases)
        )


def _phase_wavelength_A(phase: XrdPhase, fallback: float) -> float:
    if phase.result is not None:
        value = phase.result.metadata.get("wavelength_A")
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(float(value)) and float(value) > 0:
            return float(value)
    return float(fallback)


def _pattern_coordinate_values(two_theta_deg: float, wavelength_A: float) -> tuple[float, float, float]:
    theta_rad = np.deg2rad(float(two_theta_deg) / 2.0)
    sin_theta = float(np.sin(theta_rad))
    q_invA = 4.0 * np.pi * sin_theta / wavelength_A
    if sin_theta <= 0.0:
        return float("inf"), float(q_invA), 0.0
    d_A = wavelength_A / (2.0 * sin_theta)
    return float(d_A), float(q_invA), float(1.0 / d_A)


def _selected_pattern_x(axis_mode: XrdAxisMode, two_theta_deg: float, d_A: float, q_invA: float, g_invA: float) -> float:
    if axis_mode == "d_spacing":
        return d_A
    if axis_mode == "q":
        return q_invA
    if axis_mode == "g":
        return g_invA
    return two_theta_deg


def _finite_or_blank(value: float) -> float | str:
    return float(value) if np.isfinite(float(value)) else ""


def pattern_profile_rows(payload: Cif2PeaksExportPayload, axis_mode: XrdAxisMode = "two_theta") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase in payload.phases:
        result = phase.result
        if result is None:
            continue
        wavelength_A = _phase_wavelength_A(phase, payload.settings.wavelength_A)
        for two_theta, intensity in zip(result.two_theta_grid, result.intensity_profile, strict=True):
            two_theta_deg = float(two_theta)
            d_A, q_invA, g_invA = _pattern_coordinate_values(two_theta_deg, wavelength_A)
            x_value = _selected_pattern_x(axis_mode, two_theta_deg, d_A, q_invA, g_invA)
            if not np.isfinite(float(x_value)):
                continue
            rows.append(
                {
                    "phase_name": phase.phase_name,
                    "cif_name": phase.cif_path.name,
                    "x_axis_mode": axis_mode,
                    "x": float(x_value),
                    "relative_intensity": float(intensity),
                    "two_theta_deg": two_theta_deg,
                    "d_A": _finite_or_blank(d_A),
                    "q_1_over_A": _finite_or_blank(q_invA),
                    "g_1_over_A": _finite_or_blank(g_invA),
                }
            )
    return rows


def _summary_rows(payload: Cif2PeaksExportPayload) -> list[list[Any]]:
    rows: list[list[Any]] = [
        ["CIF2Peaks export", "theoretical powder XRD simulation; not experimental fitting"],
        ["exported_at", now_iso()],
        ["xray_input_mode", payload.settings.input_mode],
        ["source_preset", payload.settings.source_preset],
        ["energy_keV", payload.settings.energy_keV],
        ["wavelength_A", payload.settings.wavelength_A],
        ["d_min_A", payload.settings.d_min_A],
        ["d_max_A", payload.settings.d_max_A],
        ["two_theta_min_deg", payload.settings.two_theta_min_deg],
        ["two_theta_max_deg", payload.settings.two_theta_max_deg],
        ["step_deg", payload.settings.step_deg],
        ["fwhm_deg", payload.settings.fwhm_deg],
        ["display_axis_mode", payload.settings.axis_mode],
        ["R_hkl_definition", "R_hkl = I_unscaled / V_cell^2"],
        ["R_hkl_with_LP_definition", "R_hkl_with_LP = I_unscaled / V_cell^2"],
        ["R_hkl_no_LP_definition", "R_hkl_no_LP = (I_unscaled / LP) / V_cell^2"],
        ["I_unscaled_definition", "I_unscaled ≈ p_hkl |F_hkl|^2 LP; Debye-Waller assumed 1"],
        [
            "R_hkl_usage",
            "with-LP: uncorrected peak areas or pymatgen-style pattern comparison; no-LP: pyFAI or equivalent corrected integrated intensities",
        ],
        ["R_hkl_scope", "not a Rietveld residual; no experimental absorption, preferred orientation, or peak-integration-error correction"],
        ["result_reading_order", "先看 工作峰表；结构/占位看 Structure；多相重叠看 Overlap；英文全列看 Combined Peaks。"],
        ["warning_guidance", "error 或 warnings 非空时，先确认 CIF 结构、占位、空间群和导出范围；可用相仍会继续导出。"],
        ["r_hkl_guidance", "R_hkl 不是 Rietveld 残差；含 LP 与 no-LP 口径必须和实验积分强度处理流程一致。"],
        ["elastic_guidance", "young_modulus_hkl_normal_GPa 仅在提供有效 Cij 时可用；no_elastic_constants 表示未输入 Cij。"],
        ["q_definition", "q = 4*pi*sin(theta)/lambda"],
        ["g_definition", "g = 1/d"],
        [],
        [
            "phase_name",
            "cif_name",
            "cif_path",
            "cif_hash",
            "formula",
            "space_group",
            "space_group_from_cif",
            "space_group_detected",
            "enabled",
            "peak_count",
            "elastic_status",
            "elastic_warning",
            "error",
            "warnings",
        ],
    ]
    for phase in payload.phases:
        crystal = phase.crystal
        elastic_status, elastic_warning = _phase_elastic_summary(phase)
        rows.append(
            [
                phase.phase_name,
                phase.cif_path.name,
                str(phase.cif_path),
                "" if crystal is None else crystal.cif_hash,
                "" if crystal is None else crystal.formula,
                phase.display_space_group,
                _space_group_from_cif(phase),
                _space_group_detected(phase),
                phase.enabled,
                0 if phase.result is None else len(phase.result.peaks),
                elastic_status,
                elastic_warning,
                friendly_cif_issue_message(phase.error, []),
                " | ".join(phase.warning_messages),
            ]
        )
    return rows


def _pattern_summary_rows(payload: Cif2PeaksExportPayload, axis_mode: XrdAxisMode) -> list[list[Any]]:
    rows = _summary_rows(payload)
    rows.insert(14, ["pattern_axis_mode", axis_mode])
    return rows


def _experimental_rows(patterns: list[ExperimentalPattern]) -> list[list[Any]]:
    rows: list[list[Any]] = [["pattern_label", "source_file", "axis_mode", "x", "relative_intensity"]]
    for pattern in patterns:
        for x_value, intensity in zip(pattern.x_values, pattern.intensity, strict=True):
            rows.append([pattern.label, str(pattern.path), pattern.axis_mode, float(x_value), float(intensity)])
    return rows


def _phase_elastic_summary(phase: XrdPhase) -> tuple[str, str]:
    elastic = phase.elastic_constants
    if elastic is None:
        return "no_elastic_constants", ""
    return elastic.status, " | ".join(elastic.warnings)


def _phase_elastic_json(phase: XrdPhase) -> dict[str, Any]:
    elastic = phase.elastic_constants
    status, warning = _phase_elastic_summary(phase)
    if elastic is None:
        return {"status": status, "warning": warning}
    return {
        "status": status,
        "warning": warning,
        "unit": elastic.unit,
        "source": elastic.source,
        "coordinate_frame": elastic.coordinate_frame,
        "stiffness_GPa": _to_jsonable(elastic.stiffness_GPa),
    }


def _elastic_constants_rows_for_sheet(phases: list[XrdPhase]) -> list[list[Any]]:
    rows: list[list[Any]] = [ELASTIC_CONSTANTS_HEADERS]
    for phase in phases:
        elastic = phase.elastic_constants
        status, warning = _phase_elastic_summary(phase)
        values: list[Any] = [phase.phase_name, phase.cif_path.name, status, warning]
        if elastic is None:
            values.extend(["", "", ""])
            values.extend([""] * 36)
        else:
            matrix = elastic.stiffness_matrix_GPa if elastic.stiffness_GPa else np.full((6, 6), np.nan)
            if matrix.shape != (6, 6):
                matrix = np.full((6, 6), np.nan)
            values.extend([elastic.unit, elastic.source, elastic.coordinate_frame])
            values.extend(
                "" if not np.isfinite(float(matrix[row, column])) else float(matrix[row, column])
                for row in range(6)
                for column in range(6)
            )
        rows.append(values)
    return rows


def _user_guide_rows(payload: Cif2PeaksExportPayload) -> list[list[Any]]:
    return [
        ["CIF2Peaks 使用说明", ""],
        ["这是什么", "从 CIF 晶体结构计算理论粉末 XRD 峰表，便于在 Excel、Origin 或 Python 中继续分析。"],
        [
            "默认参数",
            (
                f"{payload.settings.source_preset}，d "
                f"{payload.settings.d_min_A:g}-{payload.settings.d_max_A:g} Å"
                if payload.settings.d_min_A is not None and payload.settings.d_max_A is not None
                else f"{payload.settings.source_preset}，2θ {payload.settings.two_theta_min_deg:g}-{payload.settings.two_theta_max_deg:g}°"
            ),
        ],
        ["最快使用", "打开后默认落在 工作峰表：相、hkl、d、2θ、相对强度、模量状态。结构体检看 Structure；多相叠峰看 Overlap。"],
        ["结果阅读顺序", "先看 工作峰表；再看 Structure 检查格子/空间群/占位；两个及以上相时看 Overlap；英文全列或批处理看 Combined Peaks。"],
        ["警告处理建议", "Summary 或峰表 warnings 非空时，先确认 CIF 是否完整、占位/空间群是否可信、导出 d 或 2θ 范围是否过窄；其它可用相仍可继续使用。"],
        ["R_hkl 使用边界", "R_hkl 不是 Rietveld 残差或实验拟合优度；含 LP 与 no-LP 口径必须匹配实验积分强度的 LP/几何/偏振校正状态。"],
        ["Cij / 弹性结果", "只有输入有效 Cij 后才会计算 hkl 法向杨氏模量；no_elastic_constants 表示未输入，invalid_elastic_constants 表示 Cij 无法用于模量计算。"],
        ["注意", "这是理论峰表，不是实验谱拟合、物相检索数据库或 Rietveld 精修。"],
        ["颜色说明", "推荐峰表 和 Combined Peaks 中，同一相使用相同淡色底纹；不同相用不同颜色，便于筛选、复制和与实验峰对齐。"],
        [],
        ["工作表", "内容"],
        ["Summary", "导出参数、每个 CIF 的读取状态、错误和警告。"],
        ["工作峰表", "精简工作表：相、hkl、d、当前 2θ、相对强度、多重性、提示、hkl 法向杨氏模量和弹性状态。"],
        ["Structure", "每个 CIF 的晶胞参数、CIF/检测空间群、占位状态与部分占位位点。"],
        ["Overlap", "两个及以上相时列出 Δ2θ 或 Δd 落在声明窗口内的峰对；窗口写在表头。"],
        ["推荐峰表", "中文列名的常用峰表，适合直接查看、筛选和复制到 Origin。"],
        ["Combined Peaks", "英文列名的完整合并峰表，适合程序读取或后续批处理。"],
        ["各相工作表", "单个 CIF/相的峰表，名称来自 CIF 文件名。"],
        [],
        ["新手先看哪几列", "用途"],
        ["相名 / phase_name", "判断这一行峰属于哪个 CIF/相；合并表中可按这一列筛选。"],
        ["晶面 hkl / hkl", "该峰对应的晶面指数，用于标注和对比不同相的特征峰。"],
        ["六方/三方 hkl 说明", "六方或三方结构可能采用四指数 Miller-Bravais 标记 (h k i l)，例如 (1 0 -1 0)；其他晶系通常为三指数 (h k l)。"],
        ["Miller-Bravais 校验", "四指数晶面指标仅在 i = -(h+k) 时用于模量计算，并转换为 (h k l) 晶面法向；这里不支持四指数晶向指标。"],
        ["d 间距 / d_A", "晶面间距，单位 Å；跨不同 X 射线波长或不同仪器设置比较时优先看这一列。"],
        ["2θ 当前设置 / two_theta_current_deg", "按当前导出参数计算的 2θ 峰位，和实验谱横坐标对齐时优先看这一列。"],
        ["2θ Cu Kα / two_theta_cu_ka_deg", "固定换算到 Cu Kα 条件下的 2θ，便于和常见实验数据或文献表格快速比较。"],
        ["相对强度 / relative_intensity", "理论归一化强度，最强峰为 100；可辅助找强峰，但不是实验定量强度。"],
        [
            "R因子 R_hkl / material_scattering_factor_R_hkl",
            "含 LP 口径，R_hkl_with_LP = I_unscaled / V_cell^2；适合未做 LP/几何/偏振校正的实验峰面积，或复现 pymatgen 理论粉末强度。",
        ],
        ["1/R_hkl / inverse_material_scattering_factor_1_over_R_hkl", "含 LP 口径 R_hkl 的倒数。"],
        ["相内 R_hkl (%) / phase_relative_R_hkl_pct", "同一相内按最大含 LP R_hkl 归一化到 100。"],
        [
            "R因子 R_hkl_no_LP / material_scattering_factor_R_hkl_no_lp",
            "去 LP 口径，R_hkl_no_LP = (I_unscaled / LP) / V_cell^2；pyFAI 或等效流程已校正积分强度推荐 no-LP。",
        ],
        [
            "1/R_hkl_no_LP / inverse_material_scattering_factor_1_over_R_hkl_no_lp",
            "去 LP 口径 R_hkl_no_LP 的倒数，用于已校正实验积分强度的 I_exp/R 校正。",
        ],
        ["相内 R_hkl_no_LP (%) / phase_relative_R_hkl_no_lp_pct", "同一相内按最大去 LP R_hkl_no_LP 归一化到 100。"],
        ["多族峰 / is_multi_family_peak", "TRUE 表示该 2θ 峰含多个 hkl family；用于定量时应谨慎检查峰归属。"],
        ["未归一化理论强度 / theoretical_intensity_unscaled", "来自 pymatgen scaled=False 的粉末理论强度，近似 I_unscaled ≈ p_hkl |F_hkl|^2 LP；Debye-Waller 默认为 1。"],
        [
            "R因子说明 / r_hkl_model_note",
            "说明含 LP 与去 LP 两种口径；如果实验处理流程是否已去 LP 不确定，不应直接做相分数定量，应先核查 pyFAI 配置和积分记录。",
        ],
        ["晶面法向杨氏模量 / young_modulus_hkl_normal_GPa", "仅当该相提供 Cij 时计算，表示 hkl 晶面法向方向的各向异性 Young's modulus，单位 GPa。"],
        ["弹性 hkl 追溯列", "elastic_hkl_used 是实际用于法向计算的三指数晶面；multiple_hkl_families 表示该 2θ 峰含多个 hkl family，主模量只对应代表 hkl。"],
        ["Cij 坐标系假设", "coordinate_frame 默认为 crystal_cartesian_from_cif_lattice；若文献 Cij 坐标轴与 CIF/Pymatgen 晶格笛卡尔坐标不一致，应先自行旋转转换。"],
        ["弹性常数状态 / elastic_status", "no_elastic_constants 表示未提供 Cij；invalid_elastic_constants 表示 Cij 无法反求柔度或不满足校验，模量列会留空。"],
        ["提示 / warnings", "CIF 读取或计算提示；非空时先检查 CIF 信息、占位、对称性或计算限制。"],
        [],
        ["如何和实验谱对齐", "先确认实验 X 射线波长是否与导出设置一致；一致时主要对比 2θ 当前设置，不一致时先用 d 间距或重新导出对应波长。"],
        [
            "定量相分析限制",
            "理论参考列不包含吸收、择优取向、显微吸收、实验峰积分误差或 Rietveld 残差修正；含 LP 与去 LP 口径必须和实验积分强度处理流程一致。",
        ],
        ["常见误区", "不要只凭单个强峰判定物相；应同时比较多个峰位、hkl 和相邻相的重叠峰。相对强度受择优取向、晶粒尺寸、仪器函数等影响较大。"],
        [],
        ["常用列名", "含义"],
        ["phase_name", "相名，默认来自 CIF 文件名。"],
        ["cif_name", "原始 CIF 文件名。"],
        ["cif_path", "原始 CIF 完整路径，可用于追溯同名文件。"],
        ["formula", "程序从 CIF 读取到的化学式。"],
        ["space_group", "空间群。"],
        ["hkl", "晶面指数。"],
        ["d_A", "晶面间距 d，单位 Å。"],
        ["two_theta_current_deg", "当前设置下的 2θ 位置，单位 °。"],
        ["two_theta_cu_ka_deg", "Cu Kα 条件下的 2θ 位置，单位 °。"],
        ["relative_intensity", "归一化相对强度，最强峰为 100。"],
        ["material_scattering_factor_R_hkl", "含 LP 口径，每峰 material scattering factor，按 R_hkl_with_LP = I_unscaled / V_cell^2 计算。"],
        ["material_scattering_factor_R_hkl_no_lp", "去 LP 口径，每峰 material scattering factor，按 R_hkl_no_LP = (I_unscaled / LP) / V_cell^2 计算。"],
        ["inverse_material_scattering_factor_1_over_R_hkl", "含 LP R_hkl 倒数。"],
        ["inverse_material_scattering_factor_1_over_R_hkl_no_lp", "去 LP R_hkl_no_LP 倒数；pyFAI 已校正积分强度推荐使用。"],
        ["phase_relative_R_hkl_pct", "同一相内含 LP R_hkl 相对最大值的百分比。"],
        ["phase_relative_R_hkl_no_lp_pct", "同一相内去 LP R_hkl_no_LP 相对最大值的百分比。"],
        ["phase_peak_rank_by_R_hkl", "同一相内按含 LP R_hkl 从大到小的 1-based 排名。"],
        ["phase_peak_rank_by_R_hkl_no_lp", "同一相内按去 LP R_hkl_no_LP 从大到小的 1-based 排名。"],
        ["phase_peak_rank_by_relative_intensity", "同一相内按 relative_intensity 从大到小的 1-based 排名。"],
        ["coincident_hkl_family_count", "同一 2θ 峰中合并的 hkl family 数量。"],
        ["is_multi_family_peak", "是否为多 hkl family 合并峰。"],
        ["mean_structure_factor_sq_per_multiplicity", "multiplicity_structure_factor_sq 除以 multiplicity 得到的平均项。"],
        ["mean_structure_factor_abs_per_multiplicity", "mean_structure_factor_sq_per_multiplicity 的平方根。"],
        ["sin_theta", "Bragg 角 theta 的正弦。"],
        ["cos_theta", "Bragg 角 theta 的余弦。"],
        ["sin_theta_over_lambda_1_over_A", "sin(theta)/lambda，单位 1/Å。"],
        ["sin2_theta_over_lambda2_1_over_A2", "(sin(theta)/lambda)^2，单位 1/Å^2。"],
        ["phase_density_g_cm3", "该相结构密度，单位 g/cm³。"],
        ["phase_formula_weight_g_mol", "该相组成式量，单位 g/mol。"],
        ["phase_cell_volume_A3", "该相晶胞体积，单位 Å^3；在峰表中重复提供便于筛选复制。"],
        ["theoretical_intensity_unscaled", "未归一化理论强度，近似 p_hkl |F_hkl|^2 LP；Debye-Waller 默认为 1。"],
        ["cell_volume_A3", "该 CIF/Pymatgen 结构的晶胞体积，单位 Å^3。"],
        ["lp_factor", "Lorentz-polarization 修正因子。"],
        ["multiplicity_structure_factor_sq", "由 I_unscaled / LP 得到，近似 p_hkl |F_hkl|^2。"],
        ["r_hkl_model_note", "R_hkl 计算口径和未包含修正项说明；不是 Rietveld 残差。"],
        ["young_modulus_hkl_normal_GPa", "由用户提供的 Cij 反求 compliance 后计算的 hkl 晶面法向杨氏模量，单位 GPa；不是 CIF 自动给出的实验模量。"],
        ["elastic_hkl_used", "实际用于模量计算的三指数晶面法向。"],
        ["elastic_family_count", "该 2θ 峰中 pymatgen 返回的 hkl family 数量。"],
        ["elastic_family_moduli_GPa", "同一峰中每个 hkl family 的法向模量列表；多 family 峰需要优先看这一列。"],
        ["elastic_modulus_note", "例如 multiple_hkl_families; primary value uses representative hkl，用于提示主模量列的适用范围。"],
        ["elastic_status", "该相弹性常数状态：valid、valid_with_warnings、no_elastic_constants 或 invalid_elastic_constants。"],
        ["elastic_warning", "Cij 单位、对称性、可逆性、正定性或 hkl 法向模量计算提示。"],
        ["warnings", "CIF 读取或计算过程中的提示；为空通常表示无明显问题。"],
    ]


def export_cif2peaks_json(payload: Cif2PeaksExportPayload, output_path: str | Path) -> None:
    data = {
        "metadata": {
            "exported_at": now_iso(),
            "application": "CIF2Peaks",
            "coordinate_definitions": {
                "q_1_over_A": "4*pi*sin(theta)/lambda",
                "g_1_over_A": "1/d",
            },
            "software_versions": package_versions(),
        },
        "settings": _to_jsonable(asdict(payload.settings)),
        "phases": [
            {
                "phase_name": phase.phase_name,
                "cif_path": str(phase.cif_path),
                "enabled": phase.enabled,
                "error": phase.error,
                "crystal": None
                if phase.crystal is None
                else {
                    "cif_hash": phase.crystal.cif_hash,
                    "formula": phase.crystal.formula,
                    "space_group": phase.display_space_group,
                    "space_group_from_cif": phase.crystal.validation_report.space_group_from_cif,
                    "space_group_detected": phase.crystal.detected_space_group_symbol,
                    "cell_parameters": phase.crystal.cell_parameters,
                },
                "elastic_constants": _phase_elastic_json(phase),
                "metadata": {} if phase.result is None else _to_jsonable(phase.result.metadata),
                "peaks": [_to_jsonable(row) for row in combined_peak_rows([phase])],
            }
            for phase in payload.phases
        ],
        "experimental_patterns": [
            {
                "label": pattern.label,
                "path": str(pattern.path),
                "axis_mode": pattern.axis_mode,
                "point_count": int(len(pattern.x_values)),
            }
            for pattern in payload.experimental_patterns
        ],
    }
    Path(output_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _xlsx_column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _xlsx_style_attribute(style_id: int | None) -> str:
    return "" if style_id is None else f' s="{style_id}"'


def _xlsx_cell(ref: str, value: Any, style_id: int | None = None) -> str:
    value = _export_table_value(value)
    style = _xlsx_style_attribute(style_id)
    if value is None:
        return f'<c r="{ref}"{style} t="inlineStr"><is><t></t></is></c>'
    if isinstance(value, bool):
        text = "TRUE" if value else "FALSE"
        return f'<c r="{ref}"{style} t="inlineStr"><is><t>{text}</t></is></c>'
    if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(float(value)):
        return f'<c r="{ref}"{style}><v>{float(value):.12g}</v></c>'
    text = html.escape(str(value))
    return f'<c r="{ref}"{style} t="inlineStr"><is><t>{text}</t></is></c>'


def _xlsx_styles_xml() -> str:
    phase_fills = "".join(
        '<fill><patternFill patternType="solid">'
        f'<fgColor rgb="FF{color}"/><bgColor indexed="64"/>'
        "</patternFill></fill>"
        for color in PHASE_FILL_COLORS
    )
    phase_xfs = "".join(
        f'<xf numFmtId="0" fontId="0" fillId="{index}" borderId="0" xfId="0" applyFill="1" applyAlignment="1">'
        '<alignment horizontal="center" vertical="center"/></xf>'
        for index in range(4, 4 + len(PHASE_FILL_COLORS))
    )
    cell_xfs_count = PHASE_STYLE_FIRST_ID + len(PHASE_FILL_COLORS)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><color rgb="FF000000"/><name val="Times New Roman"/><family val="1"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Times New Roman"/><family val="1"/></font>'
        "</fonts>"
        f'<fills count="{4 + len(PHASE_FILL_COLORS)}">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF44546A"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF548235"/><bgColor indexed="64"/></patternFill></fill>'
        f"{phase_fills}</fills>"
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        f'<cellXfs count="{cell_xfs_count}">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment horizontal="center" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1">'
        '<alignment horizontal="center" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="1" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1">'
        '<alignment horizontal="center" vertical="center"/></xf>'
        f"{phase_xfs}</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '<dxfs count="0"/>'
        '<tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>'
        "</styleSheet>"
    )


def _table_column_widths(headers: list[Any]) -> list[int]:
    default_widths = {
        "phase_name": 22,
        "cif_name": 30,
        "formula": 14,
        "space_group": 14,
        "space_group_from_cif": 20,
        "space_group_detected": 22,
        "hkl": 12,
        "d_A": 12,
        "two_theta_current_deg": 19,
        "two_theta_deg": 16,
        "two_theta_cu_ka_deg": 19,
        "x_axis_mode": 15,
        "x": 12,
        "relative_intensity": 17,
        "material_scattering_factor_R_hkl": 32,
        "material_scattering_factor_R_hkl_no_lp": 36,
        "inverse_material_scattering_factor_1_over_R_hkl": 38,
        "inverse_material_scattering_factor_1_over_R_hkl_no_lp": 42,
        "phase_relative_R_hkl_pct": 24,
        "phase_relative_R_hkl_no_lp_pct": 28,
        "phase_peak_rank_by_R_hkl": 24,
        "phase_peak_rank_by_R_hkl_no_lp": 28,
        "phase_peak_rank_by_relative_intensity": 32,
        "coincident_hkl_family_count": 26,
        "is_multi_family_peak": 18,
        "mean_structure_factor_sq_per_multiplicity": 38,
        "mean_structure_factor_abs_per_multiplicity": 40,
        "sin_theta": 14,
        "cos_theta": 14,
        "sin_theta_over_lambda_1_over_A": 28,
        "sin2_theta_over_lambda2_1_over_A2": 34,
        "phase_density_g_cm3": 22,
        "phase_formula_weight_g_mol": 28,
        "phase_cell_volume_A3": 22,
        "theoretical_intensity_unscaled": 30,
        "cell_volume_A3": 18,
        "lp_factor": 16,
        "multiplicity_structure_factor_sq": 34,
        "r_hkl_model_note": 64,
        "multiplicity": 12,
        "warnings": 48,
        "family_label": 18,
        "i": 10,
        "g_1_over_A": 14,
        "q_1_over_A": 14,
        "theta_deg": 12,
        "young_modulus_hkl_normal_GPa": 26,
        "elastic_status": 22,
        "elastic_warning": 48,
        "elastic_hkl_used": 16,
        "elastic_family_count": 18,
        "elastic_family_moduli_GPa": 48,
        "elastic_modulus_note": 44,
        "Elastic Constants": 22,
        "unit": 10,
        "source": 28,
        "coordinate_frame": 34,
        "pattern_label": 22,
        "source_file": 42,
        "axis_mode": 14,
        "相名": 18,
        "CIF 文件": 30,
        "化学式": 14,
        "空间群": 14,
        "晶面 hkl": 12,
        "d 间距 (Å)": 13,
        "2θ 当前设置 (°)": 18,
        "2θ Cu Kα (°)": 17,
        "相对强度": 12,
        "多重性": 10,
        "提示": 48,
        "R因子 R_hkl": 20,
        "1/R_hkl": 18,
        "相内 R_hkl (%)": 18,
        "未归一化理论强度": 22,
        "晶胞体积 (Å^3)": 18,
        "密度 (g/cm³)": 16,
        "多族峰": 10,
        "R因子说明": 64,
        "晶面法向杨氏模量 (GPa)": 24,
        "弹性常数状态": 16,
        "occupancy_status": 16,
        "occupancy_summary": 36,
        "occupancy_sites": 36,
        "space_group_status": 18,
        "a_A": 12,
        "b_A": 12,
        "c_A": 12,
        "alpha_deg": 12,
        "beta_deg": 12,
        "gamma_deg": 12,
        "match_by": 14,
        "phase_a": 22,
        "phase_b": 22,
    }
    return [default_widths.get(str(header), max(10, min(24, len(str(header)) + 2))) for header in headers]


def _is_table_sheet(rows: list[list[Any]]) -> bool:
    if not rows:
        return False
    headers = [str(value) for value in rows[0]]
    return (
        headers == PEAK_HEADERS
        or headers == BEGINNER_PEAK_HEADERS
        or headers == WORKING_PEAK_HEADERS
        or headers == STRUCTURE_HEADERS
        or headers == PATTERN_PROFILE_HEADERS
        or headers == ELASTIC_CONSTANTS_HEADERS
        or headers == ["pattern_label", "source_file", "axis_mode", "x", "relative_intensity"]
    )


def _is_user_guide_sheet(rows: list[list[Any]]) -> bool:
    return bool(rows and rows[0] and rows[0][0] == "CIF2Peaks 使用说明")


def _table_sheet_preamble(rows: list[list[Any]]) -> str:
    if _is_user_guide_sheet(rows):
        return (
            '<cols>'
            '<col min="1" max="1" width="24" customWidth="1"/>'
            '<col min="2" max="2" width="88" customWidth="1"/>'
            "</cols>"
        )
    if not _is_table_sheet(rows):
        return ""
    widths = _table_column_widths(rows[0])
    cols = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(widths, start=1)
    )
    return (
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft"/>'
        "</sheetView></sheetViews>"
        f"<cols>{cols}</cols>"
    )


def _table_sheet_postamble(rows: list[list[Any]]) -> str:
    if not _is_table_sheet(rows):
        return ""
    last_column = _xlsx_column_name(len(rows[0]))
    last_row = max(1, len(rows))
    return f'<autoFilter ref="A1:{last_column}{last_row}"/>'


def _header_style_id(rows: list[list[Any]], col_index: int) -> int | None:
    if not _is_table_sheet(rows):
        return None
    if rows[0] == BEGINNER_PEAK_HEADERS and col_index in BEGINNER_KEY_COLUMN_INDEXES:
        return KEY_HEADER_STYLE_ID
    return HEADER_STYLE_ID


def _cell_style_id(
    rows: list[list[Any]],
    row_index: int,
    col_index: int,
    data_row_style_ids: list[int] | None,
) -> int | None:
    if row_index == 1:
        return _header_style_id(rows, col_index)
    if data_row_style_ids is None:
        return None
    data_index = row_index - 2
    if 0 <= data_index < len(data_row_style_ids):
        return data_row_style_ids[data_index]
    return None


def _sheet_xml(rows: list[list[Any]], data_row_style_ids: list[int] | None = None) -> str:
    xml_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            style_id = _cell_style_id(rows, row_index, col_index, data_row_style_ids)
            cells.append(_xlsx_cell(f"{_xlsx_column_name(col_index)}{row_index}", value, style_id))
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'{_table_sheet_preamble(rows)}<sheetData>{"".join(xml_rows)}</sheetData>{_table_sheet_postamble(rows)}'
        "</worksheet>"
    )


def _safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = re.sub(r"[\[\]\:\*\?\/\\]", "_", name).strip() or "Sheet"
    cleaned = cleaned[:31]
    base = cleaned
    suffix = 1
    while cleaned in used:
        tail = f"_{suffix}"
        cleaned = (base[: 31 - len(tail)] + tail)[:31]
        suffix += 1
    used.add(cleaned)
    return cleaned


def _peak_rows_for_sheet(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [PEAK_HEADERS, *[[_export_table_value(row.get(header, "")) for header in PEAK_HEADERS] for row in rows]]


def _pattern_rows_for_sheet(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [PATTERN_PROFILE_HEADERS, *[[_export_table_value(row.get(header, "")) for header in PATTERN_PROFILE_HEADERS] for row in rows]]


def _beginner_peak_rows_for_sheet(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        BEGINNER_PEAK_HEADERS,
        *[
            [
                _export_table_value(value)
                for value in [
                    row.get("phase_name", ""),
                    row.get("cif_name", ""),
                    row.get("formula", ""),
                    row.get("space_group", ""),
                    row.get("hkl", ""),
                    row.get("d_A", ""),
                    row.get("two_theta_current_deg", ""),
                    row.get("two_theta_cu_ka_deg", ""),
                    row.get("relative_intensity", ""),
                    row.get("multiplicity", ""),
                    row.get("warnings", ""),
                    row.get("material_scattering_factor_R_hkl", ""),
                    row.get("inverse_material_scattering_factor_1_over_R_hkl", ""),
                    row.get("phase_relative_R_hkl_pct", ""),
                    row.get("material_scattering_factor_R_hkl_no_lp", ""),
                    row.get("inverse_material_scattering_factor_1_over_R_hkl_no_lp", ""),
                    row.get("phase_relative_R_hkl_no_lp_pct", ""),
                    row.get("theoretical_intensity_unscaled", ""),
                    row.get("cell_volume_A3", ""),
                    row.get("phase_density_g_cm3", ""),
                    row.get("is_multi_family_peak", ""),
                    row.get("r_hkl_model_note", ""),
                    row.get("young_modulus_hkl_normal_GPa", ""),
                    row.get("elastic_status", ""),
                ]
            ]
            for row in rows
        ],
    ]


def _combined_peak_rows_with_phase_styles(phases: list[XrdPhase]) -> tuple[list[dict[str, Any]], list[int]]:
    rows: list[dict[str, Any]] = []
    style_ids: list[int] = []
    for phase_index, phase in enumerate(phases):
        phase_rows = combined_peak_rows([phase])
        rows.extend(phase_rows)
        style_id = PHASE_STYLE_FIRST_ID + (phase_index % len(PHASE_FILL_COLORS))
        style_ids.extend([style_id] * len(phase_rows))
    return rows, style_ids


def export_cif2peaks_workbook(payload: Cif2PeaksExportPayload, output_path: str | Path) -> None:
    sheets: list[tuple[str, list[list[Any]], list[int] | None]] = []
    used: set[str] = set()
    combined_rows, combined_row_style_ids = _combined_peak_rows_with_phase_styles(payload.phases)
    sheets.append((_safe_sheet_name("Summary", used), _summary_rows(payload), None))
    sheets.append((_safe_sheet_name("工作峰表", used), working_peak_rows(combined_rows), combined_row_style_ids))
    sheets.append((_safe_sheet_name("Structure", used), structure_status_rows(payload.phases), None))
    overlap_rows = overlap_sheet_rows(combined_rows, payload.phases)
    if overlap_rows is not None:
        sheets.append((_safe_sheet_name("Overlap", used), overlap_rows, None))
    sheets.append((_safe_sheet_name("推荐峰表", used), _beginner_peak_rows_for_sheet(combined_rows), combined_row_style_ids))
    sheets.append((_safe_sheet_name("Combined Peaks", used), _peak_rows_for_sheet(combined_rows), combined_row_style_ids))
    for phase in payload.phases:
        sheets.append((_safe_sheet_name(phase.phase_name, used), _peak_rows_for_sheet(combined_peak_rows([phase])), None))
    sheets.append((_safe_sheet_name("Elastic Constants", used), _elastic_constants_rows_for_sheet(payload.phases), None))
    if payload.experimental_patterns:
        sheets.append((_safe_sheet_name("Experimental Data", used), _experimental_rows(payload.experimental_patterns), None))
    sheets.append((_safe_sheet_name("使用说明", used), _user_guide_rows(payload), None))

    with ZipFile(Path(output_path), "w", ZIP_DEFLATED) as archive:
        content_overrides = [
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
        ]
        for index in range(1, len(sheets) + 1):
            content_overrides.append(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'{"".join(content_overrides)}'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>",
        )
        sheet_defs = []
        rel_defs = []
        for index, (name, rows, data_row_style_ids) in enumerate(sheets, start=1):
            sheet_defs.append(f'<sheet name="{html.escape(name)}" sheetId="{index}" r:id="rId{index}"/>')
            rel_defs.append(
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            )
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows, data_row_style_ids))
        style_rel_id = len(sheets) + 1
        rel_defs.append(
            f'<Relationship Id="rId{style_rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        )
        working_tab = next((index for index, (name, _rows, _styles) in enumerate(sheets) if name == "工作峰表"), 0)
        archive.writestr("xl/styles.xml", _xlsx_styles_xml())
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<bookViews><workbookView activeTab="{working_tab}"/></bookViews>'
            f'<sheets>{"".join(sheet_defs)}</sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{"".join(rel_defs)}</Relationships>',
        )
        archive.writestr(
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>CIF2Peaks export</dc:title></cp:coreProperties>',
        )
        archive.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            "<Application>CIF2Peaks</Application></Properties>",
        )


def export_cif2peaks_pattern_workbook(
    payload: Cif2PeaksExportPayload,
    output_path: str | Path,
    *,
    axis_mode: XrdAxisMode = "two_theta",
) -> None:
    sheets: list[tuple[str, list[list[Any]], list[int] | None]] = []
    used: set[str] = set()
    sheets.append((_safe_sheet_name("Summary", used), _pattern_summary_rows(payload, axis_mode), None))
    sheets.append((_safe_sheet_name("Combined Patterns", used), _pattern_rows_for_sheet(pattern_profile_rows(payload, axis_mode)), None))
    for phase in payload.phases:
        sheets.append((_safe_sheet_name(phase.phase_name, used), _pattern_rows_for_sheet(pattern_profile_rows(Cif2PeaksExportPayload([phase], payload.settings), axis_mode)), None))

    with ZipFile(Path(output_path), "w", ZIP_DEFLATED) as archive:
        content_overrides = [
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
        ]
        for index in range(1, len(sheets) + 1):
            content_overrides.append(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'{"".join(content_overrides)}'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>",
        )
        sheet_defs = []
        rel_defs = []
        for index, (name, rows, data_row_style_ids) in enumerate(sheets, start=1):
            sheet_defs.append(f'<sheet name="{html.escape(name)}" sheetId="{index}" r:id="rId{index}"/>')
            rel_defs.append(
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            )
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows, data_row_style_ids))
        style_rel_id = len(sheets) + 1
        rel_defs.append(
            f'<Relationship Id="rId{style_rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        )
        archive.writestr("xl/styles.xml", _xlsx_styles_xml())
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<bookViews><workbookView activeTab="{len(sheets) - 1}"/></bookViews>'
            f'<sheets>{"".join(sheet_defs)}</sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'{"".join(rel_defs)}</Relationships>',
        )
        archive.writestr(
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>CIF2Peaks pattern export</dc:title></cp:coreProperties>',
        )
        archive.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            "<Application>CIF2Peaks</Application></Properties>",
        )
