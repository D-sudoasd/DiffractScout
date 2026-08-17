"""High-level local-analysis, discovery, and end-to-end workflows."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from .composition import parse_composition_text
from .diffraction import simulate_powder_pattern, validate_analysis_settings
from .elasticity import (
    discover_elastic_tensor,
    load_elastic_tensor_for_cif,
    normalize_elasticity_sidecar,
    validate_elastic_tensor,
)
from .exporters import export_result_bundle
from .models import (
    AnalysisSettings,
    DiagnosticRecord,
    DiscoveryResult,
    DownloadArtifact,
    DiscoverySettings,
    ElasticTensor,
    PhaseAnalysis,
    PipelineResult,
)
from .providers.base import PhaseProvider
from .selection import search_candidates
from .structure import load_structure
from .utils import sha256_file, slugify
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


_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def _is_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink or Windows reparse point.

    ``Path.is_junction`` was added after Python 3.10 and is not available in
    all supported runtimes.  ``st_file_attributes`` is exposed by Windows
    ``stat`` results on those runtimes, while remaining absent on POSIX.
    """

    try:
        stat_result = path.stat(follow_symlinks=False)
    except (OSError, TypeError):
        try:
            stat_result = path.lstat()
        except OSError:
            return path.is_symlink()
    return path.is_symlink() or bool(
        getattr(stat_result, "st_file_attributes", 0)
        & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _reject_reparse_components(path: Path, *, label: str) -> None:
    """Reject symlink/junction/reparse components before resolving a path."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    components: list[Path] = []
    current = absolute
    while True:
        components.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    for component in reversed(components):
        if component.exists() or component.is_symlink():
            if _is_reparse_point(component):
                raise FileExistsError(
                    f"Refusing to use a symbolic-link or Windows reparse-point {label}: {component}"
                )


def _validate_output_target(output_dir: str | Path, *, overwrite: bool) -> Path:
    raw = Path(output_dir).expanduser()
    _reject_reparse_components(raw, label="output directory")
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
        if not isinstance(payload, dict) or payload.get("schema") != "diffractscout_bundle_manifest_v1":
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
    """Match an override by canonical path, then an unambiguous legacy key.

    GUI state uses the canonical absolute CIF path so two files with the same
    basename cannot inherit one another's tensor.  Filename/stem keys remain
    supported for older callers, but a simultaneous ``name`` and ``stem``
    match is treated as ambiguous rather than selected by iteration order.
    """

    if not overrides:
        return None
    canonical = Path(cif_path).expanduser().resolve()
    canonical_text = str(canonical)
    # Prefer an exact key first, then tolerate equivalent absolute spellings
    # (for example case differences on Windows) without interpreting a stem
    # such as ``C`` as a path.
    if canonical_text in overrides:
        return overrides[canonical_text]
    absolute_matches: list[ElasticTensor] = []
    for key, tensor in overrides.items():
        try:
            key_path = Path(str(key)).expanduser()
        except (TypeError, ValueError):
            continue
        if not key_path.is_absolute():
            continue
        try:
            if key_path.resolve() == canonical:
                absolute_matches.append(tensor)
        except OSError:
            continue
    if len(absolute_matches) == 1:
        return absolute_matches[0]
    if len(absolute_matches) > 1:
        return None

    legacy_matches = [
        tensor
        for key, tensor in overrides.items()
        if str(key) in {cif_path.name, cif_path.stem}
    ]
    if len(legacy_matches) == 1:
        return legacy_matches[0]
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


def _safe_staged_filename(value: object, fallback: str, *, suffix: str) -> str:
    """Make an artifact basename that cannot encode a path traversal."""

    raw_name = Path(str(value or "")).name
    raw_stem = Path(raw_name).stem
    stem = slugify(raw_stem, Path(fallback).stem).replace(".", "_")
    stem = slugify(stem, Path(fallback).stem).replace(".", "_")
    return f"{stem}{suffix}"


def _copy_provider_artifact(
    source: str | Path,
    destination_dir: Path,
    *,
    preferred_name: str,
    suffix: str,
) -> Path:
    """Copy one provider artifact into ``inputs`` with a collision-safe name."""

    source_path = Path(source).expanduser()
    _reject_reparse_components(source_path, label="provider artifact")
    if not source_path.is_file():
        raise FileNotFoundError(f"Provider artifact does not exist: {source_path}")
    source_path = source_path.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    preferred = destination_dir / _safe_staged_filename(
        preferred_name,
        "provider_artifact",
        suffix=suffix,
    )
    _reject_reparse_components(preferred, label="staged provider artifact")
    digest = sha256_file(source_path)
    candidate = preferred
    if candidate.exists():
        if candidate.is_file() and sha256_file(candidate) == digest:
            return candidate
        candidate = destination_dir / (
            f"{preferred.stem}_{digest[:8]}{preferred.suffix}"
        )
        counter = 2
        while candidate.exists():
            if candidate.is_file() and sha256_file(candidate) == digest:
                return candidate
            candidate = destination_dir / (
                f"{preferred.stem}_{digest[:8]}_{counter}{preferred.suffix}"
            )
            counter += 1
    shutil.copy2(source_path, candidate)
    return candidate


def _stable_provider_artifact_error(prefix: str, source: object, exc: Exception) -> str:
    """Describe an artifact failure without exposing transaction-directory paths."""

    name = Path(str(source or "provider-artifact")).name or "provider-artifact"
    return f"{prefix} {name!r}: {type(exc).__name__}."


def _scrub_transaction_path(message: object, staging: Path) -> str:
    """Remove staging-root details from provider-facing error strings."""

    text = str(message or "")
    staging_text = str(staging)
    variants = {
        staging_text,
        staging_text.replace("\\", "/"),
        staging.name,
    }
    for variant in variants:
        if variant:
            text = text.replace(variant, "<staging>")
    return text


def _failed_download_artifact(item: DownloadArtifact, message: str) -> DownloadArtifact:
    """Reject an artifact while retaining a deterministic, exportable failure row."""

    return replace(
        item,
        cif_path=None,
        elasticity_path=None,
        status="failed",
        error=message,
    )


def _reconcile_download_coverage(
    candidates: Sequence[Any],
    downloads: Sequence[DownloadArtifact] | None,
) -> tuple[list[DownloadArtifact], list[DiagnosticRecord]]:
    """Reconcile provider results with the requested candidate IDs.

    Missing candidates receive synthetic failure rows.  Duplicate and
    unrequested provider rows are retained only as rejected failure rows, so
    no provider artifact can be analyzed under the wrong candidate.
    """

    requested: dict[str, Any] = {}
    requested_order: list[str] = []
    for candidate in candidates:
        material_id = str(candidate.material_id)
        if material_id not in requested:
            requested[material_id] = candidate
            requested_order.append(material_id)

    returned: dict[str, list[DownloadArtifact]] = {}
    unrequested: list[DownloadArtifact] = []
    diagnostics: list[DiagnosticRecord] = []
    for item in list(downloads or []):
        material_id = str(item.candidate.material_id)
        if material_id not in requested:
            message = (
                f"unrequested provider download artifact for candidate {material_id!r}; "
                "artifact was rejected."
            )
            unrequested.append(_failed_download_artifact(item, message))
            diagnostics.append(DiagnosticRecord("download", material_id, "error", message))
            continue
        returned.setdefault(material_id, []).append(item)

    reconciled: list[DownloadArtifact] = []
    for material_id in requested_order:
        matches = returned.get(material_id, [])
        if not matches:
            message = (
                f"missing provider download artifact for requested candidate {material_id!r}."
            )
            reconciled.append(
                DownloadArtifact(
                    candidate=requested[material_id],
                    cif_path=None,
                    status="failed",
                    error=message,
                )
            )
            diagnostics.append(DiagnosticRecord("download", material_id, "error", message))
            continue
        if len(matches) > 1:
            message = (
                f"duplicate provider download artifacts for requested candidate {material_id!r}; "
                "all duplicates were rejected."
            )
            reconciled.extend(_failed_download_artifact(item, message) for item in matches)
            diagnostics.append(DiagnosticRecord("download", material_id, "error", message))
            continue
        reconciled.append(matches[0])

    # Keep rejected unrequested rows after the requested-candidate rows in the
    # provider's original order, making exports deterministic and auditable.
    reconciled.extend(unrequested)
    return reconciled, diagnostics


def _normalize_download_artifacts(
    downloads: Sequence[DownloadArtifact],
    inputs_dir: Path,
    *,
    include_elasticity: bool,
) -> tuple[list[DownloadArtifact], list[DiagnosticRecord]]:
    """Normalize provider-returned files into the transaction staging root.

    Providers are allowed to use their own temporary download locations, but
    a result bundle must never depend on those locations after commit.  Every
    successful candidate therefore gets a staged CIF, and an explicitly
    returned elasticity artifact is copied and paired with that staged CIF.
    """

    normalized: list[DownloadArtifact] = []
    diagnostics: list[DiagnosticRecord] = []
    for item in downloads:
        staged_cif: Path | None = None
        staged_elasticity: Path | None = None
        status = item.status
        error = _scrub_transaction_path(item.error, inputs_dir.parent)
        elasticity_status = item.elasticity_status
        elasticity_error = _scrub_transaction_path(item.elasticity_error, inputs_dir.parent)

        if item.status == "ok":
            if item.cif_path is None:
                status = "failed"
                error = error or "Provider reported success without a CIF artifact."
                diagnostics.append(
                    DiagnosticRecord(
                        "download",
                        item.candidate.material_id,
                        "error",
                        error,
                    )
                )
            else:
                try:
                    staged_cif = _copy_provider_artifact(
                        item.cif_path,
                        inputs_dir,
                        preferred_name=item.cif_path.name,
                        suffix=".cif",
                    )
                except (OSError, ValueError) as exc:
                    status = "failed"
                    error = _stable_provider_artifact_error(
                        "Could not stage provider CIF artifact",
                        item.cif_path,
                        exc,
                    )
                    diagnostics.append(
                        DiagnosticRecord(
                            "download",
                            item.candidate.material_id,
                            "error",
                            error,
                        )
                    )

        if not include_elasticity:
            elasticity_status = "not_requested"
            elasticity_error = ""
        elif item.elasticity_path is None:
            no_data_statuses = {
                "no_elasticity_data",
                "no_elastic_tensor",
                "not_available",
            }
            failure_statuses = {"invalid", "elasticity_query_failed"}
            if item.status == "ok" or elasticity_status not in no_data_statuses | failure_statuses:
                elasticity_status = "no_elasticity_data"
                elasticity_error = (
                    elasticity_error
                    or "Provider reported a successful candidate without an elasticity artifact."
                )
                diagnostics.append(
                    DiagnosticRecord(
                        "elasticity",
                        item.candidate.material_id,
                        "error",
                        elasticity_error,
                    )
                )
            elif elasticity_status in failure_statuses and not elasticity_error:
                elasticity_error = "Provider returned no readable elasticity artifact."
        elif item.status == "ok" and staged_cif is None:
            if elasticity_status not in {"invalid", "elasticity_query_failed"}:
                elasticity_status = "elasticity_query_failed"
                elasticity_error = (
                    "Provider elasticity artifact was not consumed because CIF staging failed."
                )
                diagnostics.append(
                    DiagnosticRecord(
                        "elasticity",
                        item.candidate.material_id,
                        "error",
                        elasticity_error,
                    )
                )
        elif staged_cif is not None:
            try:
                staged_elasticity = _copy_provider_artifact(
                    item.elasticity_path,
                    inputs_dir,
                    preferred_name=f"{staged_cif.stem}_elasticity.json",
                    suffix=".json",
                )
                elasticity_status, elasticity_error = normalize_elasticity_sidecar(
                    item.elasticity_path,
                    staged_elasticity,
                    cif_path=item.cif_path,
                    committed_cif_name=staged_cif.name,
                    expected_material_id=item.candidate.material_id,
                )
                elasticity_error = _scrub_transaction_path(
                    elasticity_error, inputs_dir.parent
                )
                if elasticity_status in {"invalid", "elasticity_query_failed"}:
                    diagnostics.append(
                        DiagnosticRecord(
                            "elasticity",
                            item.candidate.material_id,
                            "error",
                            elasticity_error or elasticity_status,
                        )
                    )
                elif elasticity_status not in {"", "ok"}:
                    diagnostics.append(
                        DiagnosticRecord(
                            "elasticity",
                            item.candidate.material_id,
                            "warning",
                            elasticity_error or elasticity_status,
                        )
                    )
            except (OSError, TypeError, ValueError) as exc:
                elasticity_status = "elasticity_query_failed"
                elasticity_error = _stable_provider_artifact_error(
                    "Could not stage or validate provider elasticity artifact",
                    item.elasticity_path,
                    exc,
                )
                diagnostics.append(
                    DiagnosticRecord(
                        "elasticity",
                        item.candidate.material_id,
                        "error",
                        elasticity_error,
                    )
                )

        normalized.append(
            replace(
                item,
                cif_path=staged_cif,
                elasticity_path=staged_elasticity if include_elasticity else None,
                status=status,
                error=error,
                elasticity_status=elasticity_status,
                elasticity_error=elasticity_error,
            )
        )
    return normalized, diagnostics


def _rebind_committed_path(path: Path | None, staging: Path, target: Path) -> Path | None:
    if path is None:
        return None
    path_abs = Path(os.path.abspath(os.fspath(path)))
    staging_abs = Path(os.path.abspath(os.fspath(staging)))
    try:
        relative = path_abs.relative_to(staging_abs)
    except ValueError:
        return path
    return target / relative


def _rebind_metadata_paths(value: Any, staging: Path, target: Path) -> Any:
    """Rebind Path values recursively without rewriting arbitrary strings."""

    if isinstance(value, Path):
        return _rebind_committed_path(value, staging, target) or value
    if isinstance(value, dict):
        return {
            _rebind_metadata_paths(key, staging, target): _rebind_metadata_paths(
                item, staging, target
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rebind_metadata_paths(item, staging, target) for item in value]
    if isinstance(value, tuple):
        return tuple(_rebind_metadata_paths(item, staging, target) for item in value)
    if isinstance(value, set):
        return {_rebind_metadata_paths(item, staging, target) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_rebind_metadata_paths(item, staging, target) for item in value)
    return value


def _rebind_committed_results(
    analyses: Sequence[PhaseAnalysis],
    downloads: Sequence[DownloadArtifact],
    staging: Path,
    target: Path,
    *,
    discovery: DiscoveryResult | None = None,
) -> list[DownloadArtifact]:
    """Rebind returned artifact paths after the staging directory is renamed."""

    for analysis in analyses:
        analysis.structure.cif_path = _rebind_committed_path(
            analysis.structure.cif_path, staging, target
        ) or analysis.structure.cif_path
        if analysis.elastic_tensor is not None:
            analysis.elastic_tensor.raw_payload_path = _rebind_committed_path(
                analysis.elastic_tensor.raw_payload_path, staging, target
            )
        analysis.metadata = _rebind_metadata_paths(analysis.metadata, staging, target)
        analysis.structure.source_metadata = _rebind_metadata_paths(
            analysis.structure.source_metadata, staging, target
        )
    if discovery is not None:
        discovery.provider_metadata = _rebind_metadata_paths(
            discovery.provider_metadata, staging, target
        )
    return [
        replace(
            item,
            cif_path=_rebind_committed_path(item.cif_path, staging, target),
            elasticity_path=_rebind_committed_path(
                item.elasticity_path, staging, target
            ),
            provider_metadata=_rebind_metadata_paths(
                item.provider_metadata, staging, target
            ),
        )
        for item in downloads
    ]


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


def _verify_and_commit(target: Path, staging: Path, *, overwrite: bool) -> Path:
    report = verify_bundle(staging)
    if not report["ok"]:
        raise RuntimeError(
            "Generated bundle failed its integrity check: " + "; ".join(report["errors"])
        )
    # Close the long-running transaction's time-of-check/time-of-use gap. A
    # target created or modified during analysis must satisfy the same overwrite
    # policy as it did before the run started.
    _validate_output_target(target, overwrite=overwrite)
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
    validate_analysis_settings(settings)
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
        manifest = _verify_and_commit(target, staging, overwrite=overwrite)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _rebind_committed_results(analyses, [], staging, target)
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
    target = _validate_output_target(output_dir, overwrite=overwrite)
    discovery = discover_candidates(
        composition,
        provider,
        settings=discovery_settings,
    )
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
        manifest = _verify_and_commit(target, staging, overwrite=overwrite)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _rebind_committed_results([], [], staging, target, discovery=discovery)
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
    requested_analysis_settings = analysis_settings or AnalysisSettings(
        include_elasticity=include_elasticity
    )
    if requested_analysis_settings.include_elasticity != include_elasticity:
        requested_analysis_settings = replace(
            requested_analysis_settings, include_elasticity=include_elasticity
        )
    validate_analysis_settings(requested_analysis_settings)
    if include_elasticity and not conventional_unit_cell:
        raise ValueError(
            "Primitive-cell downloads cannot be paired automatically with Materials Project "
            "elastic tensors. Set include_elasticity=False or use the conventional cell."
        )
    if isinstance(confirm_above, bool) or not isinstance(confirm_above, int) or confirm_above < 1:
        raise ValueError("confirm_above must be a positive integer.")

    target = _validate_output_target(output_dir, overwrite=overwrite)
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

    staging = _create_staging_output(target)
    diagnostics = [
        DiagnosticRecord("discovery", "query", "warning", warning)
        for warning in discovery.warnings
    ]
    try:
        inputs_dir = staging / "inputs"
        provider_downloads = provider.download_candidates(
            discovery.candidates,
            inputs_dir,
            conventional_unit_cell=conventional_unit_cell,
            include_elasticity=include_elasticity,
        )
        reconciled_downloads, coverage_diagnostics = _reconcile_download_coverage(
            discovery.candidates,
            provider_downloads,
        )
        downloads, artifact_diagnostics = _normalize_download_artifacts(
            reconciled_downloads,
            inputs_dir,
            include_elasticity=include_elasticity,
        )
        diagnostics.extend(coverage_diagnostics)
        diagnostics.extend(artifact_diagnostics)
        settings = requested_analysis_settings

        path_pairs: list[tuple[Path, ElasticTensor | None]] = []
        for index, item in enumerate(downloads):
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
            tensor = None
            if include_elasticity:
                if item.elasticity_path is not None:
                    if item.elasticity_status not in {
                        "invalid",
                        "no_elasticity_data",
                        "no_elastic_tensor",
                        "elasticity_query_failed",
                        "not_available",
                    }:
                        tensor, sidecar_status, sidecar_error = load_elastic_tensor_for_cif(
                            item.elasticity_path,
                            item.cif_path,
                            expected_material_id=item.candidate.material_id,
                        )
                        sidecar_changed = (
                            sidecar_status != item.elasticity_status
                            or sidecar_error != item.elasticity_error
                        )
                        if sidecar_changed:
                            item = replace(
                                item,
                                elasticity_status=sidecar_status,
                                elasticity_error=sidecar_error,
                            )
                            downloads[index] = item
                            if sidecar_status in {"invalid", "elasticity_query_failed"}:
                                diagnostics.append(
                                    DiagnosticRecord(
                                        "elasticity",
                                        item.candidate.material_id,
                                        "error",
                                        sidecar_error or sidecar_status,
                                    )
                                )
                            elif sidecar_status not in {"", "ok"} and sidecar_error:
                                diagnostics.append(
                                    DiagnosticRecord(
                                        "elasticity",
                                        item.candidate.material_id,
                                        "warning",
                                        sidecar_error,
                                    )
                                )
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
        manifest = _verify_and_commit(target, staging, overwrite=overwrite)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    downloads = _rebind_committed_results(
        analyses,
        downloads,
        staging,
        target,
        discovery=discovery,
    )
    return PipelineResult(
        output_dir=target,
        discovery=discovery,
        downloads=downloads,
        analyses=analyses,
        manifest_path=manifest,
        warnings=_diagnostic_warnings(diagnostics),
        diagnostics=diagnostics,
    )
