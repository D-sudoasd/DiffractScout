"""Traceable CSV, Excel, JSON, and bundle-manifest exports."""

from __future__ import annotations

import csv
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .diffraction import SCIENTIFIC_BOUNDARY
from .models import (
    AnalysisSettings,
    DiscoveryResult,
    DownloadArtifact,
    PhaseAnalysis,
)
from .utils import package_versions, sha256_file, to_jsonable, utc_now_iso, write_json


def _portable_path(value: Path) -> str:
    if value.parent.name == "inputs":
        return f"inputs/{value.name}"
    return value.name


def _cell_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, Path):
        return _portable_path(value)
    if isinstance(value, (np.floating, float)):
        resolved = float(value)
        return resolved if math.isfinite(resolved) else ""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(item) for item in value)
    if isinstance(value, dict):
        return " | ".join(f"{key}={item}" for key, item in value.items())
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if fieldnames:
            writer.writeheader()
            for row in rows:
                writer.writerow({name: _cell_value(row.get(name)) for name in fieldnames})
    return path


def candidate_rows(discovery: DiscoveryResult | None) -> list[dict[str, Any]]:
    if discovery is None:
        return []
    return [asdict(candidate) for candidate in discovery.candidates]


def download_rows(downloads: list[DownloadArtifact]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in downloads:
        rows.append(
            {
                "material_id": item.candidate.material_id,
                "formula": item.candidate.formula,
                "cif_path": item.cif_path,
                "cif_sha256": sha256_file(item.cif_path) if item.cif_path and item.cif_path.is_file() else "",
                "elasticity_path": item.elasticity_path,
                "elasticity_sha256": sha256_file(item.elasticity_path)
                if item.elasticity_path and item.elasticity_path.is_file()
                else "",
                "status": item.status,
                "error": item.error,
                "source_provider": item.candidate.source_provider,
                "source_url": item.candidate.source_url,
                "provider_metadata": item.provider_metadata,
            }
        )
    return rows


def phase_rows(analyses: list[PhaseAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for analysis in analyses:
        structure = analysis.structure
        cell = structure.cell_parameters
        tensor = analysis.elastic_tensor
        rows.append(
            {
                "phase_name": analysis.phase_name,
                "cif_name": structure.cif_path.name,
                "cif_path": structure.cif_path,
                "cif_sha256": structure.cif_sha256,
                "data_block": structure.data_block,
                "formula": structure.formula,
                "space_group_symbol": structure.space_group_symbol,
                "space_group_number": structure.space_group_number,
                "a_A": cell[0],
                "b_A": cell[1],
                "c_A": cell[2],
                "alpha_deg": cell[3],
                "beta_deg": cell[4],
                "gamma_deg": cell[5],
                "site_count_asymmetric": structure.site_count_asymmetric,
                "site_count_unit_cell": structure.site_count_unit_cell,
                "partial_occupancy": structure.has_partial_occupancy,
                "reflection_count": len(analysis.reflections),
                "wavelength_A": analysis.wavelength_A,
                "energy_keV": analysis.energy_keV,
                "wavelength_source": analysis.wavelength_source,
                "elastic_status": tensor.status if tensor else "not_available",
                "elastic_source_provider": tensor.source_provider if tensor else "",
                "elastic_source_record_id": tensor.source_record_id if tensor else "",
                "elastic_coordinate_frame": tensor.coordinate_frame if tensor else "",
                "warnings": analysis.warnings,
                "source_metadata": structure.source_metadata,
            }
        )
    return rows


def peak_rows(analyses: list[PhaseAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for analysis in analyses:
        structure = analysis.structure
        for reflection in analysis.reflections:
            row = {
                "phase_name": analysis.phase_name,
                "cif_name": structure.cif_path.name,
                "cif_sha256": structure.cif_sha256,
                "formula": structure.formula,
                "space_group": structure.space_group_symbol,
                "h": reflection.h,
                "k": reflection.k,
                "l": reflection.l,
                "hkl": f"({reflection.h} {reflection.k} {reflection.l})",
                "family_label": reflection.family_label,
                "multiplicity": reflection.multiplicity,
                "d_spacing_A": reflection.d_spacing_A,
                "theta_deg": reflection.theta_deg,
                "two_theta_deg": reflection.two_theta_deg,
                "q_invA": reflection.q_invA,
                "g_invA": reflection.g_invA,
                "structure_factor_sq": reflection.structure_factor_sq,
                "intensity_no_lp": reflection.intensity_no_lp,
                "lp_factor": reflection.lp_factor,
                "intensity_with_lp": reflection.intensity_with_lp,
                "normalized_intensity": reflection.normalized_intensity,
                "volume_normalized_intensity_with_lp": reflection.material_scattering_factor_R_hkl,
                "volume_normalized_intensity_no_lp": reflection.material_scattering_factor_R_hkl_no_lp,
                "material_scattering_factor_R_hkl": reflection.material_scattering_factor_R_hkl,
                "material_scattering_factor_R_hkl_no_lp": reflection.material_scattering_factor_R_hkl_no_lp,
                "rank_by_intensity": reflection.rank_by_intensity,
                "rank_by_R_hkl": reflection.rank_by_R_hkl,
                "rank_by_R_hkl_no_lp": reflection.rank_by_R_hkl_no_lp,
                "young_modulus_hkl_normal_GPa": reflection.young_modulus_hkl_normal_GPa,
                "elastic_status": reflection.elastic_status,
                "elastic_note": reflection.elastic_note,
                "wavelength_A": analysis.wavelength_A,
                "energy_keV": analysis.energy_keV,
                "scientific_boundary": SCIENTIFIC_BOUNDARY,
            }
            rows.append(row)
    return rows


def elasticity_rows(analyses: list[PhaseAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for analysis in analyses:
        tensor = analysis.elastic_tensor
        if tensor is None:
            continue
        row: dict[str, Any] = {
            "phase_name": analysis.phase_name,
            "cif_name": analysis.structure.cif_path.name,
            "status": tensor.status,
            "unit": tensor.unit,
            "source_provider": tensor.source_provider,
            "source_record_id": tensor.source_record_id,
            "source_url": tensor.source_url,
            "methodology_url": tensor.methodology_url,
            "nature_of_data": tensor.nature_of_data,
            "coordinate_frame": tensor.coordinate_frame,
            "raw_payload_path": tensor.raw_payload_path,
            "warnings": tensor.warnings,
        }
        if tensor.stiffness_GPa.shape == (6, 6):
            for i in range(6):
                for j in range(6):
                    row[f"C{i + 1}{j + 1}_GPa"] = float(tensor.stiffness_GPa[i, j])
        rows.append(row)
    return rows


def pattern_rows(analyses: list[PhaseAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for analysis in analyses:
        for angle, intensity in zip(
            analysis.two_theta_grid,
            analysis.intensity_profile,
            strict=True,
        ):
            rows.append(
                {
                    "phase_name": analysis.phase_name,
                    "cif_name": analysis.structure.cif_path.name,
                    "two_theta_deg": float(angle),
                    "relative_intensity": float(intensity),
                    "wavelength_A": analysis.wavelength_A,
                }
            )
    return rows


def _add_sheet(workbook: Workbook, title: str, rows: list[dict[str, Any]]) -> None:
    sheet = workbook.create_sheet(title=title)
    if not rows:
        sheet.append(["status"])
        sheet.append(["no rows"])
        sheet.freeze_panes = "A2"
        return
    headers = list(rows[0])
    sheet.append(headers)
    for row in rows:
        sheet.append([_cell_value(row.get(header)) for header in headers])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for column_index, header in enumerate(headers, start=1):
        sampled = [str(header)] + [str(_cell_value(row.get(header))) for row in rows[:200]]
        width = min(max(max(len(value) for value in sampled) + 2, 10), 42)
        sheet.column_dimensions[get_column_letter(column_index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def write_excel_workbook(
    path: Path,
    *,
    summary: list[dict[str, Any]],
    phases: list[dict[str, Any]],
    peaks: list[dict[str, Any]],
    elasticity: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    downloads: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> Path:
    workbook = Workbook()
    workbook.remove(workbook.active)
    _add_sheet(workbook, "Summary", summary)
    _add_sheet(workbook, "Phases", phases)
    _add_sheet(workbook, "Peaks", peaks)
    _add_sheet(workbook, "Elasticity", elasticity)
    _add_sheet(workbook, "Candidates", candidates)
    _add_sheet(workbook, "Downloads", downloads)
    if len(patterns) <= 900_000:
        _add_sheet(workbook, "Patterns", patterns)
    else:
        _add_sheet(
            workbook,
            "Patterns",
            [
                {
                    "status": "omitted_from_workbook",
                    "reason": "Pattern profile exceeded the conservative Excel row budget; use pattern_profiles.csv.",
                    "row_count": len(patterns),
                }
            ],
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def _summary_rows(
    analyses: list[PhaseAnalysis],
    discovery: DiscoveryResult | None,
    settings: AnalysisSettings,
) -> list[dict[str, Any]]:
    return [
        {"key": "generated_at_utc", "value": utc_now_iso()},
        {"key": "phase_count", "value": len(analyses)},
        {"key": "reflection_count", "value": sum(len(item.reflections) for item in analyses)},
        {"key": "candidate_count", "value": len(discovery.candidates) if discovery else 0},
        {"key": "input_mode", "value": settings.input_mode},
        {"key": "source_preset", "value": settings.source_preset},
        {"key": "two_theta_range_deg", "value": [settings.two_theta_min_deg, settings.two_theta_max_deg]},
        {"key": "scientific_boundary", "value": SCIENTIFIC_BOUNDARY},
    ]


def _bundle_readme(
    analyses: list[PhaseAnalysis],
    discovery: DiscoveryResult | None,
) -> str:
    lines = [
        "# DiffractScout result bundle",
        "",
        "This directory is a self-contained, provenance-oriented output from DiffractScout.",
        "",
        "## Contents",
        "",
        "- `phase_summary.csv`: structure identity, unit cell, validation warnings, and source metadata.",
        "- `peak_reference.csv`: indexed theoretical powder reflections and optional hkl-normal Young's modulus.",
        "- `pattern_profiles.csv`: normalized pseudo-Voigt display profiles; not an instrument model.",
        "- `elasticity.csv`: paired 6x6 tensors and explicit provenance.",
        "- `candidate_index.csv`: Materials Project search results when discovery was used.",
        "- `download_index.csv`: source download outcomes and hashes.",
        "- `results.xlsx`: human-readable workbook containing the same tables.",
        "- `provenance.json`: settings, definitions, source metadata, and scientific boundaries.",
        "- `manifest.json`: SHA-256 inventory used by `diffractscout verify`.",
        "",
        "## Scientific boundary",
        "",
        SCIENTIFIC_BOUNDARY,
        "",
        "Materials Project Cij is labeled as DFT-derived. Automatic hkl coupling uses the raw/POSCAR tensor paired with the conventional-standard CIF; IEEE-only records require an explicit frame transform. Missing tensors remain missing.",
        "",
        f"Analyzed phases: {len(analyses)}.",
    ]
    if discovery is not None:
        lines.append(f"Discovered candidates: {len(discovery.candidates)} across {len(discovery.subsystems)} queried subsystems.")
    return "\n".join(lines) + "\n"


def export_result_bundle(
    output_dir: str | Path,
    *,
    analyses: list[PhaseAnalysis],
    settings: AnalysisSettings,
    discovery: DiscoveryResult | None = None,
    downloads: list[DownloadArtifact] | None = None,
    include_excel: bool = True,
) -> Path:
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    downloads = downloads or []

    candidates = candidate_rows(discovery)
    download_table = download_rows(downloads)
    phases = phase_rows(analyses)
    peaks = peak_rows(analyses)
    elasticity = elasticity_rows(analyses)
    patterns = pattern_rows(analyses)
    summary = _summary_rows(analyses, discovery, settings)

    _write_csv(output / "phase_summary.csv", phases)
    _write_csv(output / "peak_reference.csv", peaks)
    _write_csv(output / "pattern_profiles.csv", patterns)
    _write_csv(output / "elasticity.csv", elasticity)
    _write_csv(output / "candidate_index.csv", candidates)
    _write_csv(output / "download_index.csv", download_table)
    (output / "README.md").write_text(_bundle_readme(analyses, discovery), encoding="utf-8")

    provenance = {
        "schema": "diffractscout_provenance_v1",
        "generated_at_utc": utc_now_iso(),
        "analysis_settings": asdict(settings),
        "discovery": to_jsonable(discovery) if discovery is not None else None,
        "downloads": to_jsonable(download_table),
        "phase_metadata": [
            {
                "phase_name": analysis.phase_name,
                "structure": {
                    "cif_name": analysis.structure.cif_path.name,
                    "cif_sha256": analysis.structure.cif_sha256,
                    "formula": analysis.structure.formula,
                    "space_group": analysis.structure.space_group_symbol,
                    "source_metadata": analysis.structure.source_metadata,
                },
                "analysis_metadata": analysis.metadata,
                "warnings": analysis.warnings,
            }
            for analysis in analyses
        ],
        "definitions": {
            "q": "2*pi/d = 4*pi*sin(theta)/lambda",
            "intensity_no_lp": "multiplicity * |F_xray|^2",
            "intensity_with_lp": "intensity_no_lp * Lorentz-polarization factor",
            "volume_normalized_intensity_with_lp": "intensity_with_lp / unit_cell_volume^2",
            "volume_normalized_intensity_no_lp": "intensity_no_lp / unit_cell_volume^2",
            "legacy_R_hkl_aliases": (
                "material_scattering_factor_R_hkl and material_scattering_factor_R_hkl_no_lp "
                "are compatibility aliases for the two volume-normalized theoretical intensity channels; "
                "they are not crystallographic residual factors or standardized QPA coefficients"
            ),
            "elastic_modulus": "E(n) = 1 / (q(n)^T S q(n)) under engineering-shear Voigt convention",
        },
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "software_versions": package_versions(),
    }
    write_json(output / "provenance.json", provenance)

    if include_excel:
        write_excel_workbook(
            output / "results.xlsx",
            summary=summary,
            phases=phases,
            peaks=peaks,
            elasticity=elasticity,
            candidates=candidates,
            downloads=download_table,
            patterns=patterns,
        )

    files: list[dict[str, Any]] = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        relative = path.relative_to(output).as_posix()
        files.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                "role": (
                    "source_input"
                    if relative.startswith("inputs/")
                    else "tabular_result"
                    if path.suffix.lower() in {".csv", ".xlsx"}
                    else "provenance"
                    if path.suffix.lower() == ".json"
                    else "documentation"
                ),
            }
        )
    manifest = {
        "schema": "diffractscout_bundle_manifest_v1",
        "generated_at_utc": utc_now_iso(),
        "summary": {
            "phase_count": len(analyses),
            "reflection_count": len(peaks),
            "candidate_count": len(candidates),
            "download_count": len(downloads),
        },
        "files": files,
    }
    manifest_path = write_json(output / "manifest.json", manifest)
    return manifest_path
