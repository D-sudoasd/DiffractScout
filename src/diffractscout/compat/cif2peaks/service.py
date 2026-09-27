from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .constants import DEFAULT_XRD_WAVELENGTH_A
from .elastic_io import load_elastic_for_cif
from .hkl import split_hkl_components
from .models import XRDPeakRecord, XRDRequest, Cif2PeaksPeakRow, Cif2PeaksSettings, XrdPhase
from .structure import load_crystal_model
from .xrd import XRDService


CU_KA_WAVELENGTH_A = DEFAULT_XRD_WAVELENGTH_A


@dataclass
class Cif2PeaksService:
    xrd_service: XRDService

    def __init__(self) -> None:
        self.xrd_service = XRDService()

    def load_phase(self, cif_path: str | Path, *, auto_elastic: bool = True) -> XrdPhase:
        path = Path(cif_path).expanduser().resolve()
        crystal = load_crystal_model(path)
        phase = XrdPhase(
            cif_path=path,
            phase_name=path.stem,
            crystal=crystal,
        )
        if auto_elastic:
            elastic = load_elastic_for_cif(path)
            if elastic is not None:
                phase.elastic_constants = elastic
        return phase

    def load_phases(
        self, cif_paths: list[str | Path], *, auto_elastic: bool = True
    ) -> list[XrdPhase]:
        phases: list[XrdPhase] = []
        for cif_path in cif_paths:
            path = Path(cif_path).expanduser().resolve()
            try:
                phases.append(self.load_phase(path, auto_elastic=auto_elastic))
            except Exception as exc:
                phases.append(
                    XrdPhase(
                        cif_path=path,
                        phase_name=path.stem,
                        enabled=False,
                        error=str(exc),
                    )
                )
        return phases

    def build_request(self, phase: XrdPhase, settings: Cif2PeaksSettings) -> XRDRequest:
        return XRDRequest(
            cif_path=phase.cif_path,
            input_mode=settings.input_mode,
            source_preset=settings.source_preset,
            wavelength_A=settings.wavelength_A,
            energy_keV=settings.energy_keV,
            two_theta_min_deg=settings.two_theta_min_deg,
            two_theta_max_deg=settings.two_theta_max_deg,
            step_deg=settings.step_deg,
            profile_model=settings.profile_model,
            fwhm_deg=settings.fwhm_deg,
            show_hkl_labels=settings.show_labels,
            show_sticks=settings.show_sticks,
        )

    def simulate_phase(self, phase: XrdPhase, settings: Cif2PeaksSettings) -> XrdPhase:
        request = self.build_request(phase, settings)
        crystal = load_crystal_model(request.cif_path)
        result = self.xrd_service.simulate(crystal, request)
        phase.crystal = crystal
        phase.result = result
        phase.error = None
        return phase

    def simulate_phases(self, phases: list[XrdPhase], settings: Cif2PeaksSettings) -> list[XrdPhase]:
        for phase in phases:
            if not phase.enabled or phase.crystal is None:
                continue
            try:
                self.simulate_phase(phase, settings)
            except Exception as exc:  # pragma: no cover - surfaced in CLI summaries and tests inspect phase.error
                phase.result = None
                phase.error = str(exc)
        return phases


def two_theta_for_wavelength(d_spacing_A: float, wavelength_A: float) -> float | None:
    if d_spacing_A <= 0 or wavelength_A <= 0:
        return None
    argument = wavelength_A / (2.0 * d_spacing_A)
    if argument < -1.0 or argument > 1.0:
        return None
    return float(np.rad2deg(2.0 * np.arcsin(argument)))


def peak_to_cif2peaks_row(phase: XrdPhase, peak: XRDPeakRecord) -> Cif2PeaksPeakRow:
    h, k, i, ell = split_hkl_components(peak.hkl)
    family_hkls = peak.family_hkls or (peak.hkl,)
    return Cif2PeaksPeakRow(
        phase_name=phase.phase_name,
        cif_name=phase.cif_path.name,
        h=h,
        k=k,
        i=i,
        l=ell,
        family_label=peak.family_label,
        family_hkls=family_hkls,
        d_A=peak.d_spacing_A,
        g_1_over_A=peak.g_invA,
        q_1_over_A=peak.q_invA,
        theta_deg=peak.theta_deg,
        two_theta_current_deg=peak.two_theta_deg,
        two_theta_cu_ka_deg=two_theta_for_wavelength(peak.d_spacing_A, CU_KA_WAVELENGTH_A),
        relative_intensity=peak.normalized_intensity,
        theoretical_intensity_unscaled=peak.theoretical_intensity_unscaled,
        cell_volume_A3=peak.cell_volume_A3,
        lp_factor=peak.lp_factor,
        multiplicity_structure_factor_sq=peak.multiplicity_structure_factor_sq,
        material_scattering_factor_R_hkl=peak.material_scattering_factor_R_hkl,
        material_scattering_factor_R_hkl_no_lp=peak.material_scattering_factor_R_hkl_no_lp,
        inverse_material_scattering_factor_1_over_R_hkl=peak.inverse_material_scattering_factor_1_over_R_hkl,
        inverse_material_scattering_factor_1_over_R_hkl_no_lp=peak.inverse_material_scattering_factor_1_over_R_hkl_no_lp,
        phase_relative_R_hkl_pct=peak.phase_relative_R_hkl_pct,
        phase_relative_R_hkl_no_lp_pct=peak.phase_relative_R_hkl_no_lp_pct,
        phase_peak_rank_by_R_hkl=peak.phase_peak_rank_by_R_hkl,
        phase_peak_rank_by_R_hkl_no_lp=peak.phase_peak_rank_by_R_hkl_no_lp,
        phase_peak_rank_by_relative_intensity=peak.phase_peak_rank_by_relative_intensity,
        coincident_hkl_family_count=len(family_hkls),
        is_multi_family_peak=len(family_hkls) > 1,
        mean_structure_factor_sq_per_multiplicity=peak.mean_structure_factor_sq_per_multiplicity,
        mean_structure_factor_abs_per_multiplicity=peak.mean_structure_factor_abs_per_multiplicity,
        sin_theta=peak.sin_theta,
        cos_theta=peak.cos_theta,
        sin_theta_over_lambda_1_over_A=peak.sin_theta_over_lambda_1_over_A,
        sin2_theta_over_lambda2_1_over_A2=peak.sin2_theta_over_lambda2_1_over_A2,
        phase_density_g_cm3=peak.phase_density_g_cm3,
        phase_formula_weight_g_mol=peak.phase_formula_weight_g_mol,
        phase_cell_volume_A3=peak.phase_cell_volume_A3,
        r_hkl_model_note=peak.r_hkl_model_note,
        multiplicity=peak.multiplicity,
    )


def phase_peak_rows(phase: XrdPhase) -> list[Cif2PeaksPeakRow]:
    if phase.result is None:
        return []
    return [peak_to_cif2peaks_row(phase, peak) for peak in phase.result.peaks]
