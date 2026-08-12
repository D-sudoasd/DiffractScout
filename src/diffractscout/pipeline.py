"""High-level local-analysis, discovery, and end-to-end workflows."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from uuid import uuid4

from .composition import parse_composition_text
from .diffraction import simulate_powder_pattern
from .elasticity import discover_elastic_tensor, validate_elastic_tensor
from .exporters import export_result_bundle
from .models import (
    AnalysisSettings,
    DiagnosticRecord,
    DiscoveryResult,
    DiscoverySettings,
    ElasticTensor,
    PhaseAnalysis,
    PipelineResult,
)
from .providers.base import PhaseProvider
from .selection import search_candidates
from .structure import load_structure
from .utils import sha256_file
from .validation import verify_bundle


def collect_cif_paths(inputs: Sequence[str | Path], *, recursive: bool = True) -> list[Path]:
    """Collect readable CIF files with case-insensitive suffix handling.

    ``Path.glob('*.cif')`` is case-sensitive on common Linux filesystems. A
    directory walk followed by a suffix check keeps command-line and GUI
    behavior consistent for ``.cif``, ``.CIF``, and mixed-case variants.
    """

    output: list[Path] = []
    seen: set[Path] = set()
    for item in inputs:
        path = Path(item).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Input path does not exist: {path}")
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            candidates = sorted(
                (
                    value
                    for value in iterator
                    if value.is_file() and value.suffix.lower() == ".cif"
                ),
                key=lambda value: str(value).lower(),
            )
        else:
            if path.suffix.lower() != ".cif":
                raise ValueError(f"Explicit input file is not a CIF: {path}")
            candidates = [path]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.suffix.lower() == ".cif" and resolved.is_file() and resolved not in seen:
                output.append(resolved)
                seen.add(resolved)
    return output


def _unique_input_target(cif_path: Path, inputs_dir: Path, digest: str) -> Path:
    """Choose a deterministic, collision-safe filename inside a result bundle."""

    suffix = ".cif"
    preferred = inputs_dir / f"{cif_path.stem}{suffix}"
    if not preferred.exists():
        return preferred

    candidate = inputs_dir / f"{cif_path.stem}_{digest[:8]}{suffix}"
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = inputs_dir / f"{cif_path.stem}_{digest[:8]}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _validate_input_output_separation(
    inputs: Sequence[str | Path], output_dir: str | Path
) -> None:
    """Reject input/output overlap before an overwrite can remove source data."""

    target = Path(output_dir).expanduser().resolve()
    for item in inputs:
        source = Path(item).expanduser().resolve()
        if source == target or source.is_relative_to(target) or target.is_relative_to(source):
            raise ValueError(
                "Input and output paths must be disjoint. "
                f"Unsafe overlap: input={source}, output={target}."
            )


def _validate_output_target(output_dir: str | Path, *, overwrite: bool) -> Path:
    raw = Path(output_dir).expanduser()
    if raw.is_symlink():
        raise FileExistsError(f"Refusing to use a symbolic-link output directory: {raw}")
    output = raw.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
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
            raise FileExistsError(
                f"Refusing to overwrite output with an unreadable manifest: {exc}"
            ) from exc
        if payload.get("schema") != "diffractscout_bundle_manifest_v1":
            raise FileExistsError("Refusing to overwrite output with an unknown manifest schema.")
        verification = verify_bundle(output)
        if not verification["ok"]:
            details = "; ".join(verification["errors"][:5])
            raise FileExistsError(
                "Refusing to overwrite an existing DiffractScout bundle that fails integrity "
                f"verification: {details}"
            )
    return output


def _create_staging_output(target: Path) -> Path:
    return Path(
        tempfile.mkdtemp(prefix=f".{target.name}.diffractscout-", dir=str(target.parent))
    ).resolve()


def _commit_staging_output(target: Path, staging: Path) -> None:
    """Replace a verified result directory while retaining rollback capability."""

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


def _lookup_elastic_override(
    cif_path: Path,
    overrides: Mapping[str, ElasticTensor] | None,
) -> ElasticTensor | None:
    """Match an override by CIF filename or stem (case-sensitive keys)."""

    if not overrides:
        return None
    for key in (cif_path.name, cif_path.stem):
        if key in overrides:
            return overrides[key]
    return None


def _revalidate_user_tensor(tensor: ElasticTensor) -> ElasticTensor:
    """Re-run validation so overrides cannot bypass stiffness checks."""

    return validate_elastic_tensor(
        tensor.stiffness_GPa,
        source_provider=tensor.source_provider or "user_input",
        source_record_id=tensor.source_record_id,
        source_url=tensor.source_url,
        methodology_url=tensor.methodology_url,
        nature_of_data=tensor.nature_of_data or "user_input",
        coordinate_frame=tensor.coordinate_frame,
        raw_payload_path=tensor.raw_payload_path,
    )


def _copy_local_input(
    cif_path: Path,
    inputs_dir: Path,
    *,
    include_elasticity: bool,
    elastic_override: ElasticTensor | None = None,
) -> tuple[Path, ElasticTensor | None]:
    digest = sha256_file(cif_path)
    target = _unique_input_target(cif_path, inputs_dir, digest)
    shutil.copy2(cif_path, target)

    if not include_elasticity:
        return target, None

    if elastic_override is not None:
        tensor = _revalidate_user_tensor(elastic_override)
        if tensor.raw_payload_path is not None and tensor.raw_payload_path.is_file():
            sidecar_target = target.with_name(
                f"{target.stem}_elasticity{tensor.raw_payload_path.suffix}"
            )
            shutil.copy2(tensor.raw_payload_path, sidecar_target)
            tensor.raw_payload_path = sidecar_target
        return target, tensor

    tensor = discover_elastic_tensor(cif_path)
    if tensor is not None and tensor.raw_payload_path is not None and tensor.raw_payload_path.is_file():
        sidecar_target = target.with_name(
            f"{target.stem}_elasticity{tensor.raw_payload_path.suffix}"
        )
        shutil.copy2(tensor.raw_payload_path, sidecar_target)
        tensor.raw_payload_path = sidecar_target
    return target, tensor


def _analyze_paths(
    paths_and_tensors: Iterable[tuple[Path, ElasticTensor | None]],
    settings: AnalysisSettings,
) -> tuple[list[PhaseAnalysis], list[DiagnosticRecord]]:
    analyses: list[PhaseAnalysis] = []
    diagnostics: list[DiagnosticRecord] = []
    for path, tensor in paths_and_tensors:
        try:
            structure = load_structure(path)
            analysis = simulate_powder_pattern(
                structure,
                settings,
                elastic_tensor=tensor,
            )
            analyses.append(analysis)
            for warning in analysis.warnings:
                diagnostics.append(
                    DiagnosticRecord("analysis", path.name, "warning", warning)
                )
        except Exception as exc:
            diagnostics.append(
                DiagnosticRecord("analysis", path.name, "error", str(exc))
            )
    return analyses, diagnostics


def _diagnostic_warnings(diagnostics: list[DiagnosticRecord]) -> list[str]:
    return list(
        dict.fromkeys(
            f"{item.item}: {item.message}" if item.item else item.message
            for item in diagnostics
            if item.level in {"warning", "error"}
        )
    )


def _verify_and_commit(target: Path, staging: Path) -> Path:
    report = verify_bundle(staging)
    if not report["ok"]:
        raise RuntimeError(
            "Generated bundle failed its integrity check: " + "; ".join(report["errors"])
        )
    _commit_staging_output(target, staging)
    return target / "manifest.json"


def analyze_cifs(
    inputs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    settings: AnalysisSettings | None = None,
    recursive: bool = True,
    include_excel: bool = True,
    overwrite: bool = False,
    elastic_overrides: Mapping[str, ElasticTensor] | None = None,
) -> PipelineResult:
    settings = settings or AnalysisSettings()
    _validate_input_output_separation(inputs, output_dir)
    paths = collect_cif_paths(inputs, recursive=recursive)
    if not paths:
        raise FileNotFoundError("No CIF files were found in the supplied inputs.")
    target = _validate_output_target(output_dir, overwrite=overwrite)
    staging = _create_staging_output(target)
    try:
        inputs_dir = staging / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        copied = [
            _copy_local_input(
                path,
                inputs_dir,
                include_elasticity=settings.include_elasticity,
                elastic_override=(
                    _lookup_elastic_override(path, elastic_overrides)
                    if settings.include_elasticity
                    else None
                ),
            )
            for path in paths
        ]
        analyses, diagnostics = _analyze_paths(copied, settings)
        export_result_bundle(
            staging,
            analyses=analyses,
            settings=settings,
            downloads=[],
            diagnostics=diagnostics,
            include_excel=include_excel,
        )
        manifest = _verify_and_commit(target, staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return PipelineResult(
        output_dir=target,
        discovery=None,
        downloads=[],
        analyses=analyses,
        manifest_path=manifest,
        warnings=_diagnostic_warnings(diagnostics),
        diagnostics=diagnostics,
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
    discovery = discover_candidates(
        composition,
        provider,
        settings=discovery_settings,
    )
    target = _validate_output_target(output_dir, overwrite=overwrite)
    staging = _create_staging_output(target)
    diagnostics = [
        DiagnosticRecord("discovery", "query", "warning", warning)
        for warning in discovery.warnings
    ]
    try:
        export_result_bundle(
            staging,
            analyses=[],
            settings=AnalysisSettings(),
            discovery=discovery,
            downloads=[],
            diagnostics=diagnostics,
            include_excel=include_excel,
        )
        manifest = _verify_and_commit(target, staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return PipelineResult(
        output_dir=target,
        discovery=discovery,
        downloads=[],
        analyses=[],
        manifest_path=manifest,
        warnings=_diagnostic_warnings(diagnostics),
        diagnostics=diagnostics,
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
    if isinstance(confirm_above, bool) or not isinstance(confirm_above, int) or confirm_above < 1:
        raise ValueError("confirm_above must be a positive integer.")

    discovery = discover_candidates(
        composition,
        provider,
        settings=discovery_settings,
    )
    if len(discovery.candidates) > confirm_above and not authorize_large_download:
        raise PermissionError(
            f"Refusing to download {len(discovery.candidates)} candidates (> {confirm_above}) "
            "without explicit authorization. Set authorize_large_download=True or reduce the query."
        )

    target = _validate_output_target(output_dir, overwrite=overwrite)
    staging = _create_staging_output(target)
    diagnostics = [
        DiagnosticRecord("discovery", "query", "warning", warning)
        for warning in discovery.warnings
    ]
    try:
        inputs_dir = staging / "inputs"
        downloads = provider.download_candidates(
            discovery.candidates,
            inputs_dir,
            conventional_unit_cell=conventional_unit_cell,
            include_elasticity=include_elasticity,
        )
        settings = analysis_settings or AnalysisSettings(
            include_elasticity=include_elasticity
        )
        if settings.include_elasticity != include_elasticity:
            settings = replace(settings, include_elasticity=include_elasticity)

        path_pairs: list[tuple[Path, ElasticTensor | None]] = []
        for item in downloads:
            if item.status != "ok":
                diagnostics.append(
                    DiagnosticRecord(
                        "download",
                        item.candidate.material_id,
                        "error",
                        item.error or "Structure download failed.",
                    )
                )
                continue
            if item.elasticity_status in {
                "elasticity_query_failed",
                "frame_transform_required",
                "no_elasticity_data",
                "no_elastic_tensor",
            }:
                level = "error" if item.elasticity_status == "elasticity_query_failed" else "warning"
                diagnostics.append(
                    DiagnosticRecord(
                        "elasticity",
                        item.candidate.material_id,
                        level,  # type: ignore[arg-type]
                        item.elasticity_error or item.elasticity_status,
                    )
                )
            if item.cif_path is None or not item.cif_path.is_file():
                diagnostics.append(
                    DiagnosticRecord(
                        "download",
                        item.candidate.material_id,
                        "error",
                        "Provider reported success without a readable CIF file.",
                    )
                )
                continue
            tensor = discover_elastic_tensor(item.cif_path) if include_elasticity else None
            path_pairs.append((item.cif_path, tensor))

        analyses, analysis_diagnostics = _analyze_paths(path_pairs, settings)
        diagnostics.extend(analysis_diagnostics)
        export_result_bundle(
            staging,
            analyses=analyses,
            settings=settings,
            discovery=discovery,
            downloads=downloads,
            diagnostics=diagnostics,
            include_excel=include_excel,
        )
        manifest = _verify_and_commit(target, staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return PipelineResult(
        output_dir=target,
        discovery=discovery,
        downloads=downloads,
        analyses=analyses,
        manifest_path=manifest,
        warnings=_diagnostic_warnings(diagnostics),
        diagnostics=diagnostics,
    )
