"""Per-phase preparation checkpoints using the established CIF workflows."""
from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from ..initial_cifs import InitialCifRecord, PrepareCifsResult, _write_csv, prepare_cifs, read_phase_parameters
from ..phase_cif import adapt_cif, canonicalize_phases, fetch_prototypes
from ..pipeline import _capture_target_state, _create_staging_output, _validate_output_target, _verify_and_commit
from ..utils import sha256_file, utc_now_iso, write_json
from .checkpoints import publish_checkpoint, verify_checkpoint
from .store import read_json


def manifest(directory: Path) -> None:
    write_json(directory / "manifest.json", {"schema": "diffractscout_bundle_manifest_v1",
        "generated_at_utc": utc_now_iso(), "files": [
            {"path": path.relative_to(directory).as_posix(), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
            for path in sorted(directory.rglob("*")) if path.is_file() and path != directory / "manifest.json"]})


def prepare(execution, target: Path, *, provider=None, api_key=None) -> PrepareCifsResult:
    request = execution.request
    options = dict(request.preparation)
    phases = canonicalize_phases(options.pop("phases", None))
    parameters = options.pop("phase_parameters", None) or {}
    parameter_file = options.pop("parameter_file", None)
    if parameter_file:
        parameters = read_phase_parameters(parameter_file)
    templates = options.pop("templates", {})
    bundles, records = [], []
    execution.store.stage("preparation", total=len(phases))
    for index, phase in enumerate(phases):
        execution.check_cancel()
        checkpoint = execution.root / "prepared" / phase
        if checkpoint.exists():
            verify_checkpoint(checkpoint)
            execution.store.count("reused")
        else:
            def write(directory: Path) -> None:
                result = prepare_cifs(request.composition, directory / "bundle", phases=[phase],
                    phase_parameters={phase: parameters[phase]} if phase in parameters else {},
                    templates={phase: templates[phase]} if phase in templates else {},
                    provider=provider, api_key=api_key, **options)
                if result.exit_code != 0:
                    raise ValueError("; ".join(record.note for record in result.records))
            try:
                execution.store.count("preparations")
                publish_checkpoint(checkpoint, write)
            except Exception as exc:
                records.append({"phase": phase, "status": "failed", "note": execution.scrub(str(exc))})
                execution.store.event("preparation_failed", item=phase, message=execution.scrub(str(exc)))
                continue
        bundle = checkpoint / "bundle"
        payload = read_json(bundle / "preparation.json")
        for row in payload["records"]:
            row = dict(row)
            if row.get("cif"):
                row["cif"] = f"phases/{phase}/{row['cif']}"
            records.append(row)
        bundles.append((phase, bundle, payload))
        execution.store.update(completed_items=index+1, total_items=len(phases))
    execution.check_cancel()
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _validate_output_target(target, overwrite=request.execution["overwrite"])
    expected = _capture_target_state(target)
    staging = _create_staging_output(target)
    try:
        for phase, bundle, _payload in bundles:
            shutil.copytree(bundle, staging / "phases" / phase)
        payload = dict(bundles[0][2]) if bundles else {"schema": "diffractscout_initial_cifs_v1"}
        payload.update(composition=request.composition, records=records,
                       phase_bundle_paths=[f"phases/{phase}" for phase, _, _ in bundles])
        write_json(staging / "preparation.json", execution.scrub(payload))
        _write_csv(staging / "initial_cifs.csv", ("phase", "status", "cif", "space_group", "lattice_basis", "composition_role", "note"), records)
        report = ["# Initial CIF preparation", "", request.composition, ""]
        for row in records:
            report.append(f"- {row['phase']}: {row['status']} — {row.get('note', '')}")
        report.extend(["", "Each phases/ directory retains the complete source/provenance report.",
                       "These are starting models, not experimentally refined structures."])
        (staging / "report.md").write_text("\n".join(report)+"\n", encoding="utf-8")
        manifest(staging)
        execution.decorate_bundle(staging, analysis=False)
        _verify_and_commit(target, staging, overwrite=request.execution["overwrite"], expected_state=expected)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return PrepareCifsResult(target, target / "report.md", target / "initial_cifs.csv", target / "manifest.json",
        tuple(InitialCifRecord(row["phase"], row["status"], target / row["cif"] if row.get("cif") else None, row.get("note", "")) for row in records))


def explicit_derivation(execution, target: Path, *, provider=None, api_key=None):
    request = execution.request
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _validate_output_target(target, overwrite=request.execution["overwrite"])
    expected = _capture_target_state(target)
    staging = _create_staging_output(target)
    try:
        execution.check_cancel()
        execution.store.stage(request.workflow)
        if request.workflow == "fetch":
            options = {key: value for key, value in request.preparation.items()
                       if key in {"phases", "templates", "host", "max_subsystems"}}
            result = fetch_prototypes(request.composition, staging / "prototypes", provider=provider, api_key=api_key, **options)
        else:
            result = adapt_cif(request.inputs[0], staging / "derived.cif", **request.adaptation)
        manifest(staging)
        execution.decorate_bundle(staging, analysis=False)
        _verify_and_commit(target, staging, overwrite=request.execution["overwrite"], expected_state=expected)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if request.workflow == "fetch":
        return replace(result, output_dir=target, index_path=target / result.index_path.relative_to(staging),
                       records=tuple(replace(record, cif_path=target / record.cif_path.relative_to(staging) if record.cif_path else None) for record in result.records))
    return replace(result, cif_path=target / result.cif_path.relative_to(staging), sidecar_path=target / result.sidecar_path.relative_to(staging))
