"""Lab-oriented Excel views: beginner Chinese peak table and usage guide.

These sheets are additive presentation layers over the canonical English CSV/XLSX
exports. Scientific definitions follow SCIENTIFIC_CONTRACTS.md: R_hkl aliases are
project-defined volume-normalized theoretical intensities, not residuals or QPA.
"""

from __future__ import annotations

import re
from typing import Any

# Chinese display header -> canonical peak_rows / PEAK_HEADERS key.
BEGINNER_PEAK_HEADERS_ZH: dict[str, str] = {
    "物相名称": "phase_name",
    "CIF文件": "cif_name",
    "化学式": "formula",
    "空间群": "space_group",
    "h": "h",
    "k": "k",
    "i": "i",
    "l": "l",
    "晶面指标": "hkl",
    "晶面族": "family_label",
    "多重度": "multiplicity",
    "d间距_Å": "d_spacing_A",
    "θ_deg": "theta_deg",
    "2θ_deg": "two_theta_deg",
    "2θ_CuKa_deg": "two_theta_cu_ka_deg",
    "q_1/Å": "q_invA",
    "g_1/Å": "g_invA",
    "相对强度": "normalized_intensity",
    "强度_含LP": "intensity_with_lp",
    "强度_无LP": "intensity_no_lp",
    "体积归一强度_含LP_R_hkl": "volume_normalized_intensity_with_lp",
    "体积归一强度_无LP": "volume_normalized_intensity_no_lp",
    "相内相对R_hkl_%": "phase_relative_R_hkl_pct",
    "强度排序": "rank_by_intensity",
    "R_hkl排序": "rank_by_R_hkl",
    "杨氏模量_hkl法向_GPa": "young_modulus_hkl_normal_GPa",
    "弹性状态": "elastic_status",
    "波长_Å": "wavelength_A",
    "晶胞体积_Å3": "cell_volume_A3",
    "式量_g_mol": "formula_weight_g_mol",
    "密度_g_cm3": "density_g_cm3",
    "R_hkl说明": "r_hkl_model_note",
}


def beginner_peak_rows_zh(peaks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map canonical peak row dicts onto Chinese beginner headers."""

    rows: list[dict[str, Any]] = []
    for peak in peaks:
        rows.append({zh: peak.get(en) for zh, en in BEGINNER_PEAK_HEADERS_ZH.items()})
    return rows


def user_guide_rows() -> list[list[str]]:
    """Two-column 使用说明 content for the Excel lab view."""

    return [
        ["项目", "说明"],
        ["软件", "DiffractScout — 理论粉末 XRD 参考与物相候选 scout（非实验反演）"],
        ["推荐峰表", "面向实验室阅读的中文精简峰表；完整英文字段见 Peaks 工作表与 peak_reference.csv"],
        ["Peaks / peak_reference.csv", "完整索引峰表（规范英文列名，可复现分析）"],
        ["Patterns / pattern_profiles.csv", "显示用峰形轮廓；不是仪器分辨率模型"],
        ["d_spacing_A / d_A", "面间距 d（Å）"],
        ["two_theta_deg", "当前波长下的 2θ（°）"],
        ["two_theta_cu_ka_deg", "同一 d 在 Cu Kα（1.5406 Å）下的 2θ 便捷列"],
        ["q_invA", "q = 2π/d = 4π sin(θ)/λ（1/Å）"],
        ["g_invA", "g = 1/d（1/Å）"],
        ["normalized_intensity / 相对强度", "相内将最强线标为 100 的显示归一；不可直接跨物相比对"],
        ["intensity_with_lp", "多重度 × |F|² × Lorentz–polarization"],
        ["intensity_no_lp", "多重度 × |F|²（不含 LP）"],
        [
            "volume_normalized_intensity_with_lp / R_hkl",
            "I_with_LP / V_cell² — 项目定义的体积归一理论强度（历史别名 material_scattering_factor_R_hkl）",
        ],
        [
            "volume_normalized_intensity_no_lp",
            "I_no_LP / V_cell² — 同上通道但不含 LP（历史别名 material_scattering_factor_R_hkl_no_lp）",
        ],
        [
            "重要：R_hkl 不是残差",
            "R_hkl 不是 Rietveld R / Rwp / RBragg 等晶体学残差因子，也不是标准化 QPA 系数或实验标定散射因子",
        ],
        [
            "本软件不做",
            "物相鉴定、Rietveld/Le Bail/Pawley 精修、定量相分析（QPA）、绝对强度标定、择优取向/吸收/背底推断",
        ],
        ["杨氏模量列", "可选：沿 hkl 倒易法向的 E(n)；依赖匹配的弹性张量与坐标框架"],
        ["scientific_boundary", "完整科学边界见 provenance.json 与 SCIENTIFIC_CONTRACTS.md"],
        ["复现", "使用同一 CIF SHA-256、波长设置与软件版本；manifest.json 提供文件 SHA-256 清单"],
    ]


def safe_excel_sheet_title(name: str, used: set[str] | None = None, max_len: int = 31) -> str:
    """Excel sheet titles: max 31 chars; no : \\ / ? * [ ]."""

    cleaned = re.sub(r"[:\\/?*\[\]]", "_", str(name)).strip()
    cleaned = cleaned or "phase"
    cleaned = cleaned[:max_len]
    if used is None:
        return cleaned
    candidate = cleaned
    suffix = 2
    while candidate in used:
        tail = f"_{suffix}"
        candidate = (cleaned[: max_len - len(tail)] + tail) if len(cleaned) + len(tail) > max_len else cleaned + tail
        suffix += 1
    used.add(candidate)
    return candidate
