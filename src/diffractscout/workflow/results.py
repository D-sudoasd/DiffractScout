"""Verified result loading and bounded, machine-readable table inspection."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ..initial_cifs import InitialCifRecord, PrepareCifsResult
from ..models import CandidateRecord, DiagnosticRecord, DiscoveryResult, DiscoverySettings, ParsedComposition, PipelineResult
from ..phase_cif import AdaptResult, FetchPrototypesResult, PrototypeRecord
from ..utils import sha256_file, to_jsonable, write_json
from ..validation import verify_bundle
from .checkpoints import load_analysis, publish_checkpoint, verify_checkpoint
from .provider import artifact_from_dict
from .store import job_path, read_json


def result_record(root: Path, result: Any, execution) -> Path:
    attempt = execution.store.state["attempt"]
    destination = root / "results" / str(attempt)
    if isinstance(result, PipelineResult):
        data = {"kind": "pipeline", "output_dir": str(result.output_dir),
                "discovery": to_jsonable(result.discovery), "downloads": to_jsonable(result.downloads),
                "diagnostics": to_jsonable(result.diagnostics), "warnings": result.warnings,
                "analyses": execution.analysis_refs}
    else:
        data = {"kind": "prepare" if isinstance(result, PrepareCifsResult) else
                        "fetch" if isinstance(result, FetchPrototypesResult) else "adapt",
                "result": to_jsonable(result), "output_dir": str(getattr(result, "output_dir", result.cif_path.parent if isinstance(result, AdaptResult) else ""))}
    output = Path(data["output_dir"])
    data["manifest_sha256"] = sha256_file(output / "manifest.json")
    publish_checkpoint(destination, lambda directory: write_json(directory / "result.json", execution.scrub(data)))
    return destination


def _record(root: Path, verify: bool = True) -> tuple[dict, Path]:
    status = read_json(root / "state.json")
    path = root / status.get("result_record", "results/missing")
    verify_checkpoint(path)
    data = read_json(path / "result.json")
    output = Path(data["output_dir"])
    if verify:
        report = verify_bundle(output)
        if not report["ok"] or sha256_file(output / "manifest.json") != data["manifest_sha256"]:
            raise ValueError("Result bundle integrity failed: " + "; ".join(report["errors"]))
    return data, output


def load_result_object(run_id: str, *, workspace=None):
    root = job_path(workspace, run_id)
    data, output = _record(root)
    kind = data["kind"]
    if kind == "pipeline":
        analyses = [load_analysis(root / entry["checkpoint"], cif_path=output / "inputs" / entry["cif_name"])
                    for entry in data["analyses"]]
        discovery = data["discovery"]
        if discovery:
            parsed = discovery["parsed"]
            for key in ("elements", "labels", "material_ids", "notes"):
                parsed[key] = tuple(parsed[key])
            discovery = DiscoveryResult(parsed=ParsedComposition(**parsed), settings=DiscoverySettings(**discovery["settings"]),
                candidates=[CandidateRecord(**row) for row in discovery["candidates"]],
                subsystems=discovery["subsystems"], subsystem_counts=discovery["subsystem_counts"],
                provider_metadata=discovery["provider_metadata"], warnings=discovery["warnings"])
        return PipelineResult(output, discovery, [artifact_from_dict(row, output) for row in data["downloads"]],
                              analyses, output / "manifest.json", data["warnings"],
                              [DiagnosticRecord(**row) for row in data["diagnostics"]])
    values = data["result"]
    if kind == "prepare":
        return PrepareCifsResult(output, Path(values["report_path"]), Path(values["index_path"]), Path(values["manifest_path"]),
            tuple(InitialCifRecord(row["phase"], row["status"], Path(row["cif_path"]) if row["cif_path"] else None, row["note"])
                  for row in values["records"]))
    if kind == "fetch":
        records = []
        for row in values["records"]:
            row["cif_path"] = Path(row["cif_path"]) if row["cif_path"] else None
            records.append(PrototypeRecord(**row))
        return FetchPrototypesResult(output, Path(values["index_path"]), values["host"], tuple(values["elements"]), tuple(records))
    values["cif_path"], values["sidecar_path"] = Path(values["cif_path"]), Path(values["sidecar_path"])
    values["warnings"] = tuple(values["warnings"])
    return AdaptResult(**values)


def get_result(run_id: str, *, workspace=None, table=None, offset=0, limit=100, verify=True) -> dict:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("offset must be nonnegative; limit must be between 1 and 1000.")
    root = job_path(workspace, run_id)
    data, output = _record(root, verify=verify)
    status = read_json(root / "state.json")
    response = {"run_id": run_id, "state": status["state"], "integrity": "passed" if verify else "not_checked",
                "coverage": status.get("coverage", {}), "diagnostics": status.get("diagnostics", []),
                "needs_review": status.get("needs_review", False),
                "artifacts": status.get("artifacts", []), "output_dir": str(output), "kind": data["kind"]}
    if table is None:
        response["tables"] = sorted(path.stem for path in output.glob("*.csv"))
        return response
    tables = {path.stem: path for path in output.glob("*.csv")}
    if table not in tables:
        raise ValueError(f"Unknown table {table!r}; choose one of {', '.join(sorted(tables))}.")
    rows = []
    with tables[table].open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        for index, row in enumerate(reader):
            if index < offset:
                continue
            rows.append(row)
            if len(rows) > limit:
                break
    response.update(table=table, columns=fields, rows=rows[:limit], offset=offset,
                    next_offset=offset+min(len(rows), limit), has_more=len(rows) > limit)
    return response
