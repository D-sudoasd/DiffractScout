from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import numpy as np

SearchMode = Literal["possible_phases", "near_stable", "single_chemsys", "mpids_only"]
XrayInputMode = Literal["source", "wavelength", "energy"]
DiagnosticLevel = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class ParsedComposition:
    elements: tuple[str, ...]
    labels: tuple[str, ...] = ()
    material_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    raw: str = ""

    @property
    def chemsys(self) -> str:
        return "-".join(sorted(self.elements))

    @property
    def default_label(self) -> str:
        if self.labels:
            return self.labels[0]
        if self.material_ids and not self.elements:
            return "_".join(self.material_ids[:3])
        return "".join(self.elements) or "composition"


@dataclass(frozen=True)
class CandidateRecord:
    material_id: str
    formula: str = ""
    energy_above_hull_eV_atom: float | None = None
    is_stable: bool | None = None
    theoretical: bool | None = None
    space_group: str = ""
    space_group_number: int | None = None
    crystal_system: str = ""
    deprecated: bool | None = None
    queried_chemsys: str = ""
    source_provider: str = "Materials Project"
    source_url: str = ""
    structure_type: str = ""
    structure_type_rule: str = ""


@dataclass(frozen=True)
class DiscoverySettings:
    mode: SearchMode = "possible_phases"
    e_hull_max_eV_atom: float | None = None
    max_subsystem_order: int | None = None
    max_per_subsystem: int | None = None
    max_total: int | None = None
    exclude_deprecated: bool = True


@dataclass(frozen=True)
class AnalysisSettings:
    input_mode: XrayInputMode = "source"
    source_preset: str = "Cu Ka"
    wavelength_A: float | None = None
    energy_keV: float | None = None
    two_theta_min_deg: float = 5.0
    two_theta_max_deg: float = 120.0
    step_deg: float = 0.02
    fwhm_deg: float = 0.15
    profile_eta: float = 0.5
    include_elasticity: bool = True
    max_profile_points: int = 1_000_000
    max_reflection_estimate: int = 2_000_000


@dataclass(frozen=True)
class DiagnosticRecord:
    stage: str
    item: str
    level: DiagnosticLevel
    message: str


@dataclass
class ElasticTensor:
    stiffness_GPa: np.ndarray
    source_provider: str = ""
    source_record_id: str = ""
    source_url: str = ""
    methodology_url: str = ""
    nature_of_data: str = ""
    coordinate_frame: str = "crystal_cartesian_from_cif_lattice"
    unit: str = "GPa"
    status: str = "valid"
    warnings: list[str] = field(default_factory=list)
    raw_payload_path: Path | None = None

    @cached_property
    def compliance_1_over_GPa(self) -> np.ndarray | None:
        """Return a cached compliance tensor for repeated directional evaluations."""

        if self.status == "invalid" or self.stiffness_GPa.shape != (6, 6):
            return None
        try:
            return np.linalg.inv(self.stiffness_GPa)
        except np.linalg.LinAlgError:
            return None


@dataclass
class StructureRecord:
    cif_path: Path
    cif_sha256: str
    data_block: str
    formula: str
    cell_parameters: tuple[float, float, float, float, float, float]
    space_group_symbol: str
    space_group_number: int | None
    site_count_asymmetric: int
    site_count_unit_cell: int
    has_partial_occupancy: bool
    warnings: list[str] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)
    small_structure: Any = field(default=None, repr=False, compare=False)
    structure_factor_structure: Any = field(default=None, repr=False, compare=False)
    space_group_object: Any = field(default=None, repr=False, compare=False)


@dataclass
class ReflectionRecord:
    h: int
    k: int
    l: int
    family_label: str
    multiplicity: int
    d_spacing_A: float
    theta_deg: float
    two_theta_deg: float
    q_invA: float
    g_invA: float
    structure_factor_sq: float
    intensity_no_lp: float
    lp_factor: float
    intensity_with_lp: float
    normalized_intensity: float
    material_scattering_factor_R_hkl: float
    material_scattering_factor_R_hkl_no_lp: float
    rank_by_intensity: int = 0
    rank_by_R_hkl: int = 0
    rank_by_R_hkl_no_lp: int = 0
    young_modulus_hkl_normal_GPa: float | None = None
    elastic_status: str = "not_requested"
    elastic_note: str = ""

    @property
    def hkl(self) -> tuple[int, int, int]:
        return self.h, self.k, self.l


@dataclass
class PhaseAnalysis:
    phase_name: str
    structure: StructureRecord
    reflections: list[ReflectionRecord]
    two_theta_grid: np.ndarray
    intensity_profile: np.ndarray
    wavelength_A: float
    energy_keV: float | None
    wavelength_source: str
    elastic_tensor: ElasticTensor | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DownloadArtifact:
    candidate: CandidateRecord
    cif_path: Path | None
    elasticity_path: Path | None = None
    status: str = "ok"
    error: str = ""
    elasticity_status: str = ""
    elasticity_error: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveryResult:
    parsed: ParsedComposition
    settings: DiscoverySettings
    candidates: list[CandidateRecord]
    subsystems: list[str]
    subsystem_counts: dict[str, int]
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    output_dir: Path
    discovery: DiscoveryResult | None
    downloads: list[DownloadArtifact]
    analyses: list[PhaseAnalysis]
    manifest_path: Path
    warnings: list[str] = field(default_factory=list)
    diagnostics: list[DiagnosticRecord] = field(default_factory=list)
