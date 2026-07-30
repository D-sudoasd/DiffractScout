"""High-level local-analysis, discovery, and end-to-end workflows."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Sequence

from .composition import parse_composition_text
from .diffraction import simulate_powder_pattern
from .elasticity import discover_elastic_tensor
from .exporters import export_result_bundle
from .models import (
    AnalysisSettings,
    DiscoveryResult,
    DiscoverySettings,
    PhaseAnalysis,
    PipelineResult,
)
from .providers.base import PhaseProvider
from .selection import search_candidates
from .structure import load_structure
from .utils import sha256_file


def collect_cif_paths(inputs: Sequence[str | Path], *, recursive: bool = True) -> list[Path]:
    output: list[Path] = []
    seen: set[Path] = set()
    for item in inputs:
        path = Path(item).expanduser().resolve()
        if path.is_dir():
            iterator = path.rglob("*.cif") if recursive else path.glob("*.cif")
            candidates = sorted(iterator, key=lambda value: str(value).lower())
        else:
            candidates = [path]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.suffix.lower() == ".cif" and resolved.is_file() and resolved not in seen:
                output.append(resolved)
                seen.add(resolved)
    return output


def _prepare_output(output_dir: str | Path, *, overwrite: bool = False) -> Path:
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and not output.is_dir():
        raise FileExistsError(f"Output path exists and is not a directory: {output}")
    if output.exists() and any(output.iterdir()):
        if not overwrite:
            raise FileExistsError(
                f"Output directory is not empty: {output}. Choose a new directory or pass overwrite=True."
            )
        manifest = output / "manifest.json"
        if not manifest.is_file():
            raise FileExistsError(
                f"Refusing to overwrite a non-empty directory without a DiffractScout manifest: {output}"
            )
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FileExistsError(f"Refusing to overwrite output with an unreadable manifest: {exc}") from exc
        if payload.get("schema") != "diffractscout_bundle_manifest_v1":
            raise FileExistsError("Refusing to overwrite output with an unknown manifest schema.")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    return output


def _copy_local_input(cif_path: Path, inputs_dir: Path) -> tuple[Path, object | None]:
    digest = sha256_file(cif_path)
    target = inputs_dir / cif_path.name
    if target.exists() and sha256_file(target) != digest:
        target = inputs_dir / f"{cif_path.stem}_{digest[:8]}{cif_path.suffix}"
    shutil.copy2(cif_path, target)

    tensor = discover_elastic_tensor(cif_path)
    if tensor is not None and tensor.raw_payload_path is not None and tensor.raw_payload_path.is_file():
        sidecar_target = target.with_name(f"{target.stem}_elasticity{tensor.raw_payload_path.suffix}")
        shutil.copy2(tensor.raw_payload_path, sidecar_target)
        tensor.raw_payload_path = sidecar_target
    return target, tensor


def _analyze_paths(
    paths_and_tensors: Iterable[tuple[Path, object | None]],
    settings: AnalysisSettings,
) -> tuple[list[PhaseAnalysis], list[str]]:
    analyses: list[PhaseAnalysis] = []
    warnings: list[str] = []
    for path, tensor in paths_and_tensors:
        try:
            structure = load_structure(path)
            analysis = simulate_powder_pattern(
                structure,
                settings,
                elastic_tensor=tensor,  # type: ignore[arg-type]
            )
            analyses.append(analysis)
        except Exception as exc:
            warnings.append(f"{path.name}: {exc}")
    return analyses, warnings


def analyze_cifs(
    inputs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    settings: AnalysisSettings | None = None,
    recursive: bool = True,
    include_excel: bool = True,
    overwrite: bool = False,
) -> PipelineResult:
    settings = settings or AnalysisSettings()
    paths = collect_cif_paths(inputs, recursive=recursive)
    if not paths:
        raise FileNotFoundError("No CIF files were found in the supplied inputs.")
    output = _prepare_output(output_dir, overwrite=overwrite)
    inputs_dir = output / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    copied = [_copy_local_input(path, inputs_dir) for path in paths]
    analyses, warnings = _analyze_paths(copied, settings)
    manifest = export_result_bundle(
        output,
        analyses=analyses,
        settings=settings,
        downloads=[],
        include_excel=include_excel,
    )
    return PipelineResult(
        output_dir=output,
        discovery=None,
        downloads=[],
        analyses=analyses,
        manifest_path=manifest,
        warnings=warnings,
    )


def discover_candidates(
    composition: str,
    provider: PhaseProvider,
    *,
    settings: DiscoverySettings | None = None,
) -> DiscoveryResult:
    parsed = parse_composition_text(composition)
    return search_candidates(provider, parsed, settings or DiscoverySettings())


def export_discovery(
    composition: str,
    provider: PhaseProvider,
    output_dir: str | Path,
    *,
    discovery_settings: DiscoverySettings | None = None,
    include_excel: bool = True,
    overwrite: bool = False,
) -> PipelineResult:
    output = _prepare_output(output_dir, overwrite=overwrite)
    discovery = discover_candidates(
        composition,
        provider,
        settings=discovery_settings,
    )
    manifest = export_result_bundle(
        output,
        analyses=[],
        settings=AnalysisSettings(),
        discovery=discovery,
        downloads=[],
        include_excel=include_excel,
    )
    return PipelineResult(
        output_dir=output,
        discovery=discovery,
        downloads=[],
        analyses=[],
        manifest_path=manifest,
        warnings=list(discovery.warnings),
    )


def run_pipeline(
    composition: str,
    provider: PhaseProvider,
    output_dir: str | Path,
    *,
    discovery_settings: DiscoverySettings | None = None,
    analysis_settings: AnalysisSettings | None = None,
    conventional_unit_cell: bool = True,
    include_elasticity: bool = True,
    include_excel: bool = True,
    overwrite: bool = False,
    confirm_above: int = 200,
    authorize_large_download: bool = False,
) -> PipelineResult:
    if include_elasticity and not conventional_unit_cell:
        raise ValueError(
            "Primitive-cell downloads cannot be paired automatically with Materials Project "
            "elastic tensors. Set include_elasticity=False or use the conventional cell."
        )
    output = _prepare_output(output_dir, overwrite=overwrite)
    discovery = discover_candidates(
        composition,
        provider,
        settings=discovery_settings,
    )
    if len(discovery.candidates) > confirm_above and not authorize_large_download:
        shutil.rmtree(output)
        raise PermissionError(
            f"Refusing to download {len(discovery.candidates)} candidates (> {confirm_above}) "
            "without explicit authorization. Set authorize_large_download=True or reduce the query."
        )
    inputs_dir = output / "inputs"
    downloads = provider.download_candidates(
        discovery.candidates,
        inputs_dir,
        conventional_unit_cell=conventional_unit_cell,
        include_elasticity=include_elasticity,
    )
    settings = analysis_settings or AnalysisSettings(include_elasticity=include_elasticity)
    if settings.include_elasticity != include_elasticity:
        settings = replace(settings, include_elasticity=include_elasticity)

    path_pairs: list[tuple[Path, object | None]] = []
    for item in downloads:
        if item.cif_path is None or not item.cif_path.is_file():
            continue
        tensor = discover_elastic_tensor(item.cif_path) if include_elasticity else None
        path_pairs.append((item.cif_path, tensor))
    analyses, analysis_warnings = _analyze_paths(path_pairs, settings)
    warnings = [*discovery.warnings, *analysis_warnings]
    for item in downloads:
        if item.status != "ok":
            warnings.append(f"{item.candidate.material_id}: {item.error}")

    manifest = export_result_bundle(
        output,
        analyses=analyses,
        settings=settings,
        discovery=discovery,
        downloads=downloads,
        include_excel=include_excel,
    )
    return PipelineResult(
        output_dir=output,
        discovery=discovery,
        downloads=downloads,
        analyses=analyses,
        manifest_path=manifest,
        warnings=list(dict.fromkeys(warnings)),
    )
