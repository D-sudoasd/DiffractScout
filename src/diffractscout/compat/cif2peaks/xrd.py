from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from pymatgen.analysis.diffraction.xrd import XRDCalculator

from .constants import XRD_SOURCE_PRESETS, X_RAY_ENERGY_WAVELENGTH_KEV_A
from .hkl import format_hkl, normalize_hkl
from .models import CrystalModel, XRDPeakRecord, XRDRequest, XRDResult
from .utils import now_iso, package_versions


R_HKL_MODEL_NOTE = (
    "R_hkl_with_LP = I_unscaled/V_cell^2 uses pymatgen unscaled powder intensity "
    "p_hkl|F_hkl|^2*LP; use with LP for uncorrected integrated peak areas or pymatgen-style "
    "pattern comparison. R_hkl_no_LP = (I_unscaled/LP)/V_cell^2; use no-LP for pyFAI or "
    "equivalent LP/polarization/geometry corrected integrated peak areas. Debye-Waller assumed "
    "1; no experimental absorption, preferred orientation, or Rietveld residual correction; "
    "not a Rietveld residual."
)


def _gaussian_profile(grid: np.ndarray, center: float, fwhm: float) -> np.ndarray:
    sigma = max(fwhm, 1e-6) / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    return np.exp(-0.5 * ((grid - center) / sigma) ** 2)


def _lorentzian_profile(grid: np.ndarray, center: float, fwhm: float) -> np.ndarray:
    gamma = max(fwhm, 1e-6) / 2.0
    return gamma**2 / ((grid - center) ** 2 + gamma**2)


def _peak_profile(grid: np.ndarray, center: float, fwhm: float, model: str) -> np.ndarray:
    if model == "gaussian":
        return _gaussian_profile(grid, center, fwhm)
    if model == "lorentzian":
        return _lorentzian_profile(grid, center, fwhm)
    return 0.5 * _gaussian_profile(grid, center, fwhm) + 0.5 * _lorentzian_profile(grid, center, fwhm)


def _lorentz_polarization_factor(theta_rad: float) -> float:
    denominator = np.sin(theta_rad) ** 2 * np.cos(theta_rad)
    if abs(float(denominator)) < 1e-12:
        return float("inf")
    return float((1.0 + np.cos(2.0 * theta_rad) ** 2) / denominator)


def _finite_float_or_nan(value: object) -> float:
    try:
        resolved = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")
    return resolved if np.isfinite(resolved) else float("nan")


def _inverse_or_nan(value: float) -> float:
    return float("nan") if not np.isfinite(value) or value == 0 else float(1.0 / value)


def _sqrt_or_nan(value: float) -> float:
    return float("nan") if not np.isfinite(value) or value < 0 else float(np.sqrt(value))


def _descending_ordinal_ranks(values: list[float]) -> list[int]:
    indexed = sorted(
        enumerate(values),
        key=lambda item: item[1] if np.isfinite(item[1]) else float("-inf"),
        reverse=True,
    )
    ranks = [0] * len(values)
    for rank, (index, _value) in enumerate(indexed, start=1):
        ranks[index] = rank
    return ranks


def build_quality_report(result: XRDResult) -> dict[str, object]:
    warnings = list(result.warnings)
    if result.metadata.get("step_deg", 0.02) > 0.05:
        warnings.append("步长偏大，峰位标定建议使用 step <= 0.02 deg。")
    return {
        "geometry_reliability": "high",
        "intensity_reliability": "medium",
        "model_identity": "theoretical_powder_xrd_profile",
        "convergence_status": "conditionally_stable" if warnings else "stable",
        "warnings": warnings,
        "recommended_next_actions": ["用于峰位标定时优先使用 d、q 和 2θ 表格，不要把相对强度当作精修结果。"],
    }


class XRDService:
    def __init__(self) -> None:
        self._result_cache: dict[tuple[object, ...], XRDResult] = {}

    @staticmethod
    def _build_result_cache_key(crystal: CrystalModel, request: XRDRequest) -> tuple[object, ...]:
        return (crystal.cif_hash, *request.cache_key())

    def resolve_wavelength(self, request: XRDRequest) -> tuple[float, float | None, str]:
        input_mode = request.input_mode or "source"
        if input_mode == "energy":
            if request.energy_keV is None or request.energy_keV <= 0:
                raise ValueError("XRD 能量输入必须为正数，单位 keV。")
            energy = float(request.energy_keV)
            return X_RAY_ENERGY_WAVELENGTH_KEV_A / energy, energy, "energy_keV"

        if input_mode == "wavelength":
            if request.wavelength_A is None or request.wavelength_A <= 0:
                raise ValueError("XRD 波长输入必须为正数，单位 Å。")
            return float(request.wavelength_A), None, "wavelength_A"

        value = XRD_SOURCE_PRESETS.get(request.source_preset)
        if value is None:
            if request.wavelength_A is None or request.wavelength_A <= 0:
                raise ValueError("选择自定义 XRD 光源时必须提供正的波长，单位 Å。")
            return float(request.wavelength_A), None, "source_preset_custom_wavelength"

        wavelength = float(value)
        return wavelength, X_RAY_ENERGY_WAVELENGTH_KEV_A / wavelength, f"source_preset:{request.source_preset}"

    @staticmethod
    def _validate_scan_window(request: XRDRequest) -> tuple[float, float, float, float]:
        two_theta_min = _finite_float_or_nan(request.two_theta_min_deg)
        two_theta_max = _finite_float_or_nan(request.two_theta_max_deg)
        step_deg = _finite_float_or_nan(request.step_deg)
        fwhm_deg = _finite_float_or_nan(request.fwhm_deg)
        if not np.isfinite(two_theta_min) or not np.isfinite(two_theta_max):
            raise ValueError("2theta range values must be finite numbers.")
        if two_theta_min < 0 or two_theta_max > 180 or two_theta_min >= two_theta_max:
            raise ValueError("2theta range must satisfy 0 <= min < max <= 180.")
        if not np.isfinite(step_deg) or step_deg <= 0:
            raise ValueError("step_deg must be a finite positive number.")
        if not np.isfinite(fwhm_deg) or fwhm_deg <= 0:
            raise ValueError("fwhm_deg must be a finite positive number.")
        return two_theta_min, two_theta_max, step_deg, fwhm_deg

    def simulate(self, crystal: CrystalModel, request: XRDRequest) -> XRDResult:
        wavelength, energy_keV, wavelength_source = self.resolve_wavelength(request)
        two_theta_min, two_theta_max, step_deg, fwhm_deg = self._validate_scan_window(request)
        resolved_request = XRDRequest(
            cif_path=Path(request.cif_path).expanduser().resolve(),
            two_theta_min_deg=two_theta_min,
            two_theta_max_deg=two_theta_max,
            step_deg=step_deg,
            input_mode=request.input_mode or "source",
            source_preset=request.source_preset,
            wavelength_A=wavelength,
            energy_keV=energy_keV if request.input_mode != "wavelength" else request.energy_keV,
            profile_model=request.profile_model,
            fwhm_deg=fwhm_deg,
            show_hkl_labels=request.show_hkl_labels,
            show_sticks=request.show_sticks,
        )
        cache_key = self._build_result_cache_key(crystal, resolved_request)
        cached = self._result_cache.get(cache_key)
        if cached is not None:
            return cached

        calculator = XRDCalculator(wavelength=wavelength, symprec=0.0)
        pattern = calculator.get_pattern(
            crystal.pymatgen_structure,
            scaled=False,
            two_theta_range=(resolved_request.two_theta_min_deg, resolved_request.two_theta_max_deg),
        )

        grid = np.arange(
            resolved_request.two_theta_min_deg,
            resolved_request.two_theta_max_deg + resolved_request.step_deg * 0.5,
            resolved_request.step_deg,
            dtype=float,
        )
        profile = np.zeros_like(grid, dtype=float)
        peaks: list[XRDPeakRecord] = []
        pattern_x = np.asarray(pattern.x, dtype=float)
        pattern_y = np.asarray(pattern.y, dtype=float)
        d_hkls = np.asarray(pattern.d_hkls, dtype=float)
        max_intensity = float(np.max(pattern_y)) if pattern_y.size else 1.0
        cell_volume_A3 = float(crystal.pymatgen_structure.lattice.volume)
        phase_density_g_cm3 = _finite_float_or_nan(crystal.pymatgen_structure.density)
        phase_formula_weight_g_mol = _finite_float_or_nan(crystal.pymatgen_structure.composition.weight)

        for two_theta, intensity, families, d_spacing in zip(pattern_x, pattern_y, pattern.hkls, d_hkls, strict=True):
            if not families:
                continue
            representative = max(families, key=lambda item: int(item.get("multiplicity", 1)))
            hkl = normalize_hkl(representative["hkl"])
            family_hkls = tuple(normalize_hkl(item["hkl"]) for item in families)
            multiplicity = sum(int(item.get("multiplicity", 1)) for item in families)
            label = " / ".join(format_hkl(item["hkl"]) for item in families[:3])
            family_label = "{" + " / ".join(format_hkl(item["hkl"])[1:-1] for item in families[:6]) + "}"
            theta = float(two_theta) / 2.0
            theta_rad = np.deg2rad(theta)
            sin_theta = float(np.sin(theta_rad))
            cos_theta = float(np.cos(theta_rad))
            sin_theta_over_lambda = float("nan") if wavelength <= 0 else float(sin_theta / wavelength)
            g_invA = 0.0 if float(d_spacing) == 0 else 1.0 / float(d_spacing)
            q_invA = 4.0 * np.pi * sin_theta / wavelength
            lp_factor = _lorentz_polarization_factor(theta_rad)
            theoretical_intensity_unscaled = float(intensity)
            multiplicity_structure_factor_sq = (
                float("nan")
                if not np.isfinite(lp_factor) or lp_factor == 0
                else theoretical_intensity_unscaled / lp_factor
            )
            material_scattering_factor_R_hkl = (
                float("nan")
                if cell_volume_A3 <= 0
                else theoretical_intensity_unscaled / (cell_volume_A3**2)
            )
            material_scattering_factor_R_hkl_no_lp = (
                float("nan")
                if cell_volume_A3 <= 0 or not np.isfinite(multiplicity_structure_factor_sq)
                else float(multiplicity_structure_factor_sq / (cell_volume_A3**2))
            )
            coincident_hkl_family_count = len(family_hkls) or 1
            mean_structure_factor_sq_per_multiplicity = (
                float("nan")
                if multiplicity <= 0 or not np.isfinite(multiplicity_structure_factor_sq)
                else float(multiplicity_structure_factor_sq / multiplicity)
            )
            peaks.append(
                XRDPeakRecord(
                    hkl=hkl,
                    d_spacing_A=float(d_spacing),
                    theta_deg=theta,
                    two_theta_deg=float(two_theta),
                    q_invA=float(q_invA),
                    g_invA=float(g_invA),
                    intensity=theoretical_intensity_unscaled,
                    normalized_intensity=0.0 if max_intensity == 0 else float(intensity / max_intensity * 100.0),
                    theoretical_intensity_unscaled=theoretical_intensity_unscaled,
                    cell_volume_A3=cell_volume_A3,
                    lp_factor=lp_factor,
                    multiplicity_structure_factor_sq=float(multiplicity_structure_factor_sq),
                    material_scattering_factor_R_hkl=float(material_scattering_factor_R_hkl),
                    material_scattering_factor_R_hkl_no_lp=float(material_scattering_factor_R_hkl_no_lp),
                    inverse_material_scattering_factor_1_over_R_hkl=_inverse_or_nan(float(material_scattering_factor_R_hkl)),
                    inverse_material_scattering_factor_1_over_R_hkl_no_lp=_inverse_or_nan(
                        float(material_scattering_factor_R_hkl_no_lp)
                    ),
                    phase_relative_R_hkl_pct=float("nan"),
                    phase_relative_R_hkl_no_lp_pct=float("nan"),
                    phase_peak_rank_by_R_hkl=0,
                    phase_peak_rank_by_R_hkl_no_lp=0,
                    phase_peak_rank_by_relative_intensity=0,
                    coincident_hkl_family_count=coincident_hkl_family_count,
                    is_multi_family_peak=coincident_hkl_family_count > 1,
                    mean_structure_factor_sq_per_multiplicity=mean_structure_factor_sq_per_multiplicity,
                    mean_structure_factor_abs_per_multiplicity=_sqrt_or_nan(mean_structure_factor_sq_per_multiplicity),
                    sin_theta=sin_theta,
                    cos_theta=cos_theta,
                    sin_theta_over_lambda_1_over_A=sin_theta_over_lambda,
                    sin2_theta_over_lambda2_1_over_A2=float("nan")
                    if not np.isfinite(sin_theta_over_lambda)
                    else float(sin_theta_over_lambda**2),
                    phase_density_g_cm3=phase_density_g_cm3,
                    phase_formula_weight_g_mol=phase_formula_weight_g_mol,
                    phase_cell_volume_A3=cell_volume_A3,
                    r_hkl_model_note=R_HKL_MODEL_NOTE,
                    multiplicity=multiplicity,
                    label=label,
                    family_label=family_label,
                    family_hkls=family_hkls,
                )
            )
            profile += float(intensity) * _peak_profile(grid, float(two_theta), resolved_request.fwhm_deg, resolved_request.profile_model)

        if np.max(profile) > 0:
            profile = profile / np.max(profile) * 100.0

        if peaks:
            r_hkl_values = [peak.material_scattering_factor_R_hkl for peak in peaks]
            r_hkl_no_lp_values = [peak.material_scattering_factor_R_hkl_no_lp for peak in peaks]
            intensity_values = [peak.normalized_intensity for peak in peaks]
            finite_r_hkl_values = [value for value in r_hkl_values if np.isfinite(value)]
            finite_r_hkl_no_lp_values = [value for value in r_hkl_no_lp_values if np.isfinite(value)]
            max_r_hkl = max(finite_r_hkl_values) if finite_r_hkl_values else float("nan")
            max_r_hkl_no_lp = max(finite_r_hkl_no_lp_values) if finite_r_hkl_no_lp_values else float("nan")
            r_hkl_ranks = _descending_ordinal_ranks(r_hkl_values)
            r_hkl_no_lp_ranks = _descending_ordinal_ranks(r_hkl_no_lp_values)
            intensity_ranks = _descending_ordinal_ranks(intensity_values)
            peaks = [
                replace(
                    peak,
                    phase_relative_R_hkl_pct=float("nan")
                    if not np.isfinite(max_r_hkl) or max_r_hkl == 0 or not np.isfinite(peak.material_scattering_factor_R_hkl)
                    else float(100.0 * peak.material_scattering_factor_R_hkl / max_r_hkl),
                    phase_relative_R_hkl_no_lp_pct=float("nan")
                    if not np.isfinite(max_r_hkl_no_lp)
                    or max_r_hkl_no_lp == 0
                    or not np.isfinite(peak.material_scattering_factor_R_hkl_no_lp)
                    else float(100.0 * peak.material_scattering_factor_R_hkl_no_lp / max_r_hkl_no_lp),
                    phase_peak_rank_by_R_hkl=r_hkl_ranks[index],
                    phase_peak_rank_by_R_hkl_no_lp=r_hkl_no_lp_ranks[index],
                    phase_peak_rank_by_relative_intensity=intensity_ranks[index],
                )
                for index, peak in enumerate(peaks)
            ]

        warnings = list(crystal.validation_report.warnings)
        if crystal.has_partial_occupancy:
            warnings.append("当前 XRD 为平均结构近似；部分占位按 CIF 平均占位参与结构因子计算。")
        if not peaks:
            warnings.append("给定 2θ 范围内没有理论衍射峰。")

        result = XRDResult(
            two_theta_grid=grid,
            intensity_profile=profile,
            stick_positions_deg=pattern_x,
            stick_intensities=pattern_y if pattern_y.size else np.array([], dtype=float),
            peaks=peaks,
            metadata={
                "timestamp_utc": now_iso(),
                "cif_hash": crystal.cif_hash,
                "structure_version_token": crystal.cif_hash,
                "cif_path": str(crystal.cif_path),
                "formula": crystal.formula,
                "space_group": crystal.detected_space_group_symbol or crystal.space_group_symbol,
                "space_group_from_cif": crystal.space_group_symbol,
                "space_group_detected": crystal.detected_space_group_symbol,
                "xray_input_mode": resolved_request.input_mode,
                "energy_keV": energy_keV,
                "wavelength_source": wavelength_source,
                "source_preset": resolved_request.source_preset,
                "wavelength_A": wavelength,
                "cell_volume_A3": cell_volume_A3,
                "phase_density_g_cm3": phase_density_g_cm3,
                "phase_formula_weight_g_mol": phase_formula_weight_g_mol,
                "R_hkl_definition": "R_hkl = I_unscaled / V_cell^2",
                "R_hkl_with_LP_definition": "R_hkl_with_LP = I_unscaled / V_cell^2",
                "R_hkl_no_LP_definition": "R_hkl_no_LP = (I_unscaled / LP) / V_cell^2",
                "I_unscaled_definition": "I_unscaled = p_hkl|F_hkl|^2*LP from pymatgen scaled=False; Debye-Waller assumed 1.",
                "R_hkl_usage": "Use with-LP R for uncorrected peak areas; use no-LP R for pyFAI or equivalent corrected integrated intensities.",
                "q_definition": "4*pi*sin(theta)/lambda",
                "two_theta_range_deg": [resolved_request.two_theta_min_deg, resolved_request.two_theta_max_deg],
                "step_deg": resolved_request.step_deg,
                "profile_model": resolved_request.profile_model,
                "fwhm_deg": resolved_request.fwhm_deg,
                "software_versions": package_versions(),
            },
            warnings=warnings,
        )
        result.quality_report = build_quality_report(result)
        result.summary_sections = {
            "实验事实": ["输入为 CIF 结构，输出为理论粉末 XRD。"],
            "计算结果": [f"峰数量：{len(result.peaks)}", f"波长：{wavelength:.5f} Å"],
            "模型限制": ["不包含实验仪器函数拟合、物相检索或 Rietveld 精修。"],
            "可信度提示": result.quality_report["warnings"] or ["峰位几何用于标定较可靠；相对强度仅作理论参考。"],
        }
        self._result_cache[cache_key] = result
        return result
