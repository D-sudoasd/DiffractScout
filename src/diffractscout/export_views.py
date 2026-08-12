"""Lab-oriented Excel views: beginner Chinese peak table and usage guide.

These sheets are additive presentation layers over the canonical English CSV/XLSX
exports. Scientific definitions follow SCIENTIFIC_CONTRACTS.md: R_hkl aliases are
project-defined volume-normalized theoretical intensities, not residuals or QPA.
"""

from __future__ import annotations

import re
from typing import Any

# Ordered Chinese display header -> canonical peak_rows / PEAK_HEADERS key.
# Order is analysis-first: identity → hkl → geometry → intensity → ranks → elastic → meta.
BEGINNER_PEAK_HEADERS_ZH: dict[str, str] = {
    # Identity (filter by phase)
    "物相名称": "phase_name",
    "CIF文件": "cif_name",
    "化学式": "formula",
    "空间群": "space_group",
    # Miller indices
    "h": "h",
    "k": "k",
    "i": "i",
    "l": "l",
    "晶面指标": "hkl",
    "晶面族": "family_label",
    "多重度": "multiplicity",
    # Geometry
    "d间距_Å": "d_spacing_A",
    "θ_deg": "theta_deg",
    "2θ_当前_deg": "two_theta_deg",
    "2θ_CuKa_deg": "two_theta_cu_ka_deg",
    "q_1/Å": "q_invA",
    "g_1/Å": "g_invA",
    # Display intensity (max=100 within phase)
    "相对强度_相内max100": "normalized_intensity",
    "强度排序_相内": "rank_by_intensity",
    # LP / no-LP channels
    "强度_含LP": "intensity_with_lp",
    "强度_无LP": "intensity_no_lp",
    "LP因子": "lp_factor",
    # Volume-normalized J (= historical R_hkl alias) — NOT residual R
    "体积归一强度J_含LP_R_hkl别名": "volume_normalized_intensity_with_lp",
    "体积归一强度J_无LP": "volume_normalized_intensity_no_lp",
    "1/J_含LP": "inverse_R_hkl",
    "1/J_无LP": "inverse_R_hkl_no_lp",
    "相内相对J_含LP_%": "phase_relative_R_hkl_pct",
    "相内相对J_无LP_%": "phase_relative_R_hkl_no_lp_pct",
    "J_含LP排序": "rank_by_R_hkl",
    "J_无LP排序": "rank_by_R_hkl_no_lp",
    # Quality flags
    "是否多族共2θ": "is_multi_family_peak",
    "共位hkl族数": "coincident_hkl_family_count",
    # Elastic (optional)
    "杨氏模量_hkl法向_GPa": "young_modulus_hkl_normal_GPa",
    "弹性状态": "elastic_status",
    "弹性备注": "elastic_note",
    # Run metadata
    "波长_Å": "wavelength_A",
    "能量_keV": "energy_keV",
    "晶胞体积_Å3": "cell_volume_A3",
    "式量_g_mol": "formula_weight_g_mol",
    "密度_g_cm3": "density_g_cm3",
    "J_R_hkl通道说明": "r_hkl_model_note",
}

# Practical analysis column set required for criterion-1 style checks (canonical names).
ANALYSIS_PEAK_COLUMNS: tuple[str, ...] = (
    "phase_name",
    "hkl",
    "d_spacing_A",
    "two_theta_deg",
    "two_theta_cu_ka_deg",
    "normalized_intensity",
    "intensity_with_lp",
    "intensity_no_lp",
    "volume_normalized_intensity_with_lp",
    "volume_normalized_intensity_no_lp",
    "rank_by_intensity",
    "wavelength_A",
    "energy_keV",
    "young_modulus_hkl_normal_GPa",
)


def beginner_peak_rows_zh(peaks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map canonical peak row dicts onto Chinese beginner headers (ordered)."""

    rows: list[dict[str, Any]] = []
    for peak in peaks:
        rows.append({zh: peak.get(en) for zh, en in BEGINNER_PEAK_HEADERS_ZH.items()})
    return rows


def user_guide_rows() -> list[list[str]]:
    """Two-column 使用说明 content for the Excel lab view."""

    return [
        ["项目", "说明"],
        ["软件", "DiffractScout — 理论粉末 XRD 参考与候选相 scout（非实验反演）"],
        ["建议阅读顺序", "① 本表 使用说明 → ② 推荐峰表（中文筛选）→ ③ Peaks 完整英文列 → ④ CSV 做脚本"],
        ["推荐峰表", "分析向中文长表：冻结首行 + 自动筛选；用「物相名称」过滤多相；列顺序为 身份→hkl→几何→强度→排序→弹性"],
        ["Peaks", "完整规范英文峰表（与 peak_reference.csv 列名一致）；同样冻结首行 + 自动筛选"],
        ["Phases", "每个 CIF/相的晶胞、空间群、占位警告、弹性配对状态"],
        ["Patterns", "显示用连续峰形（伪 Voigt 等）；不是仪器分辨率或背景模型"],
        ["Elasticity", "6×6 Cij（GPa）与坐标框架、来源记录"],
        ["Diagnostics", "结构化警告/失败；部分相失败时仍可能有可用峰表"],
        [],
        ["—— 几何列 ——", ""],
        ["d间距_Å / d_spacing_A", "面间距 d，单位 Å；跨波长比较优先看 d"],
        ["θ_deg / theta_deg", "Bragg 角 θ（°）；衍射角 2θ = 2×θ"],
        ["2θ_当前_deg / two_theta_deg", "当前导出波长/能量下的 2θ（°）；与实验横坐标对齐时用此列"],
        ["2θ_CuKa_deg / two_theta_cu_ka_deg", "同一 d 换算到 Cu Kα（λ=1.5406 Å）的 2θ，便于对照常见实验室数据"],
        ["q_1/Å / q_invA", "q = 2π/d = 4π sin(θ)/λ，单位 1/Å"],
        ["g_1/Å / g_invA", "g = 1/d，单位 1/Å"],
        [],
        ["—— 强度列（理论） ——", ""],
        ["相对强度_相内max100 / normalized_intensity", "相内最强线标为 100 的显示归一；不可跨物相直接比绝对强度"],
        ["强度_含LP / intensity_with_lp", "多重度 × |F_xray|² × Lorentz–polarization（LP）"],
        ["强度_无LP / intensity_no_lp", "多重度 × |F_xray|²（不含 LP）"],
        ["LP因子 / lp_factor", "经典粉末 LP：(1+cos²2θ)/(sin²θ cosθ)"],
        [
            "体积归一强度J_含LP / volume_normalized_intensity_with_lp",
            "J = I_with_LP / V_cell²；历史别名 material_scattering_factor_R_hkl / R_hkl",
        ],
        [
            "体积归一强度J_无LP / volume_normalized_intensity_no_lp",
            "J = I_no_LP / V_cell²；历史别名 material_scattering_factor_R_hkl_no_lp",
        ],
        ["1/J_含LP / inverse_R_hkl", "1 / J_with_LP（便利列；非 QPA 系数）"],
        ["1/J_无LP / inverse_R_hkl_no_lp", "1 / J_no_LP"],
        ["相内相对J_%", "同一相内按最大 J 归一到 100%"],
        ["强度排序 / rank_by_*", "相内 1-based 排名：1 为最强，数值越小越强（勿按 rank 降序找强峰）"],
        [],
        ["—— 重要科学边界 ——", ""],
        [
            "R_hkl / J 不是残差",
            "R_hkl 风格名称只是体积归一理论强度别名，不是 Rietveld R/Rwp/RBragg 等晶体学残差，也不是标准化 QPA 或实验标定散射因子",
        ],
        [
            "本软件不做",
            "实验物相自动鉴定、Rietveld/Le Bail/Pawley、定量相分析（QPA）、绝对强度标定、择优取向/吸收/背底/微结构反演",
        ],
        ["是否多族共2θ", "TRUE 表示相近 2θ 上有多个 hkl 族；对比实验时需谨慎归属"],
        [],
        ["—— 弹性（可选） ——", ""],
        ["杨氏模量_hkl法向_GPa", "沿 hkl 倒易法向的 E(n)=1/(n^T S n)；需有效 Cij 与兼容坐标框架"],
        ["弹性状态", "valid / not_available / frame_transform_required / invalid 等；非 valid 时模量列可为空"],
        [],
        ["—— 如何在 Excel 中分析 ——", ""],
        ["筛选物相", "在 推荐峰表 或 Peaks 对「物相名称/phase_name」列使用自动筛选"],
        ["找强峰", "按 相对强度 降序；或筛选 rank_by_intensity=1..5（rank 升序，1 最强）"],
        ["对齐实验 2θ", "波长一致时用 2θ_当前；波长不同先比 d 或看 2θ_CuKa"],
        ["跨相强度", "不要用相内相对强度直接定量；本表为理论参考"],
        ["复现", "同一 CIF SHA-256、波长设置与软件版本；manifest.json 提供文件哈希"],
        ["scientific_boundary", "完整边界见 provenance.json 与 docs/SCIENTIFIC_CONTRACTS.md"],
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
