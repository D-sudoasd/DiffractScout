"""One worker, one task; all numerical work goes through existing workflows."""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..models import AnalysisSettings, DiscoverySettings, PipelineResult
from ..pipeline import analyze_cifs, export_discovery, run_pipeline
from ..utils import sha256_file
from ..validation import verify_bundle
from .checkpoints import environment, tensor_from_dict
from .contracts import WorkflowRequest, plan_workflow
from .execution import Execution, WorkflowCancelled, WorkflowIntegrityError
from .preparation import explicit_derivation, prepare
from .provider import CheckpointProvider
from .results import result_record
from .snapshots import snapshot_request
from .store import RunStore, file_lock, read_json


def _owned_published_output(target: Path, root: Path, request_hash: str) -> bool:
    """Recognize publication whose acknowledgement was interrupted.

    Preserve the verified original and finish in a new revision using saved
    calculations. Never infer ownership merely from a directory's name.
    """
    try:
        from .checkpoints import fingerprint
        return (verify_bundle(target)["ok"]
                and read_json(target / "workflow_summary.json").get("run_id") == root.name
                and fingerprint(read_json(target / "workflow_request.json")) == request_hash)
    except (ValueError, OSError, KeyError):
        return False


def execute(root: Path, *, provider=None, api_key=None, expected_attempt=None) -> dict:
    try:
        with file_lock(root / "worker.lock"):
            if expected_attempt is not None and read_json(root / "state.json")["attempt"] != expected_attempt:
                return read_json(root / "state.json")
            return _execute_locked(root, provider=provider, api_key=api_key)
    except BlockingIOError:
        return read_json(root / "state.json")


def _execute_locked(root: Path, *, provider=None, api_key=None) -> dict:
    store = RunStore(root)
    request = WorkflowRequest.from_dict(read_json(root / "request.json"))
    execution = Execution(store, request, api_key=api_key)
    if provider is not None and isinstance(getattr(provider, "api_key", None), str):
        execution.secrets.append(provider.api_key)
    started = time.monotonic()
    previous_elapsed = store.state.get("elapsed_seconds", 0)
    store.update(state="running", worker_pid=os.getpid(), attempt=store.state.get("attempt", 0)+1,
                 diagnostics=[], integrity="not_checked")
    store.event("started", attempt=store.state["attempt"])
    try:
        execution.check_cancel()
        from .checkpoints import fingerprint
        if fingerprint(request.to_dict()) != store.state["request_hash"]:
            raise ValueError("Saved request changed; submit a new task instead of editing a task record.")
        saved_environment = read_json(root / "environment.json")
        if saved_environment != environment():
            raise ValueError("Software or dependency versions changed; submit a new task. Existing checkpoints were preserved.")
        store.stage("snapshot")
        request = snapshot_request(root, request)
        execution.request = request
        target = Path(request.output_dir) if request.output_dir else root / "bundle"
        if target.exists() and (store.state.get("result_record") or _owned_published_output(target, root, store.state["request_hash"])):
            if not store.state.get("result_record"):
                store.event("publication_recovered", preserved_bundle=str(target))
                store.update(recovered_bundles=[*store.state.get("recovered_bundles", []), str(target)])
            target = target.with_name(f"{target.name}-retry-{store.state['attempt']}")
        request.output_dir = str(target)
        plan = plan_workflow(request, provider=provider, api_key=api_key)
        if not plan["ready"]:
            store.update(state="blocked", stage="planning", diagnostics=plan["diagnostics"])
            return store.state
        needs_provider = request.workflow in {"run", "discover"} or (
            request.workflow == "fetch" and ("mp-api" in plan["required_dependencies"] or bool(api_key or os.environ.get("MP_API_KEY")))) or (
            request.workflow in {"prepare", "prepare_analyze"} and not request.preparation.get("offline", False)
            and bool(api_key or os.environ.get("MP_API_KEY") or provider))
        if needs_provider and provider is None:
            from ..providers.materials_project import MaterialsProjectProvider
            provider = MaterialsProjectProvider(api_key or os.environ.get("MP_API_KEY", ""))
        if provider is not None:
            provider = CheckpointProvider(provider, execution)
            execution.provider = provider
        target.parent.mkdir(parents=True, exist_ok=True)
        store.update(output_dir=str(target))
        settings = AnalysisSettings(**request.analysis)
        options = request.execution
        common = {"include_excel": request.exports["include_excel"], "overwrite": options["overwrite"], "_execution": execution}
        if request.workflow == "analyze":
            result = analyze_cifs(request.inputs, target, settings=settings, recursive=options["recursive"],
                elastic_overrides={key: tensor_from_dict(value) for key, value in request.elastic_overrides.items()}, **common)
        elif request.workflow in {"run", "discover"}:
            discovery = DiscoverySettings(**request.discovery)
            if request.workflow == "discover":
                result = export_discovery(request.composition, provider, target, discovery_settings=discovery, **common)
            else:
                result = run_pipeline(request.composition, provider, target, discovery_settings=discovery,
                    analysis_settings=settings, conventional_unit_cell=options["conventional_unit_cell"],
                    confirm_above=options["confirm_above"], authorize_large_download=options["authorize_large_download"], **common)
        elif request.workflow in {"prepare", "prepare_analyze"}:
            prepared_target = target if request.workflow == "prepare" else root / f"preparation-{store.state['attempt']}"
            prepared = prepare(execution, prepared_target, provider=provider, api_key=api_key)
            if request.workflow == "prepare":
                result = prepared
            else:
                paths = [str(row.cif_path) for row in prepared.records if row.cif_path]
                if not paths:
                    result = prepared
                else:
                    from ..models import DiagnosticRecord
                    execution.extra_diagnostics.extend(DiagnosticRecord("preparation", row.phase, "error", row.note)
                                                       for row in prepared.records if not row.cif_path)
                    result = analyze_cifs(paths, target, settings=settings, **common)
                store.update(preparation_bundle=str(prepared_target))
        else:
            result = explicit_derivation(execution, target, provider=provider, api_key=api_key)
        output = Path(getattr(result, "output_dir", result.cif_path.parent if request.workflow == "adapt" else target))
        report = verify_bundle(output)
        if not report["ok"]:
            raise ValueError("Published result failed verification: " + "; ".join(report["errors"]))
        saved_result = result_record(root, result, execution)
        diagnostics = []
        if isinstance(result, PipelineResult):
            diagnostics = [execution.diagnostic("ITEM_FAILED" if row.level == "error" else "SCIENTIFIC_WARNING", row.message,
                                               stage=row.stage, item=row.item) | {"level": row.level} for row in result.diagnostics]
            successes = len(result.analyses)
            total = len(result.downloads) if result.discovery is not None and request.workflow != "discover" else len(request.inputs)
            if request.workflow == "prepare_analyze":
                total = len(prepared.records)
            if request.workflow == "discover":
                successes = len(result.discovery.candidates)
                total = successes
            errors = sum(row.level == "error" for row in result.diagnostics)
            if request.workflow == "discover":
                state = "partial" if errors and successes else "failed" if errors else "completed"
            else:
                state = "failed" if not successes else "partial" if errors else "completed"
                empty_phases = [analysis.phase_name for analysis in result.analyses if not analysis.reflections]
                for phase in empty_phases:
                    diagnostics.append(execution.diagnostic("EMPTY_REFLECTION_TABLE", "No reflections in the requested window; the reference table is empty.",
                                                            stage="analysis", item=phase) | {"level": "warning"})
                if empty_phases and state == "completed":
                    state = "partial"
            if not successes and request.workflow != "discover":
                diagnostics.append(execution.diagnostic("NO_ANALYZABLE_PHASES", "No phase could be analyzed; inspect source and provider diagnostics."))
        else:
            rows = getattr(result, "records", None)
            successes = sum(row.cif_path is not None for row in rows) if rows is not None else 1
            total = len(rows) if rows is not None else 1
            state = "completed" if successes == total else "partial" if successes else "failed"
            if rows:
                diagnostics = [execution.diagnostic("PREPARATION_FAILED" if not row.cif_path else "INITIAL_MODEL", row.note,
                                                   stage="preparation", item=row.phase) for row in rows if row.note]
        if provider is not None:
            diagnostics.extend(provider.failures)
            if provider.failures and state == "completed":
                state = "partial" if successes else "failed"
        artifacts = [{"kind": "bundle", "path": str(output)},
                     {"kind": "manifest", "path": str(output / "manifest.json"), "sha256": sha256_file(output / "manifest.json")}]
        artifacts.extend({"kind": "workbook", "path": str(path)} for path in sorted(output.glob("*.xlsx")))
        if store.state.get("preparation_bundle"):
            artifacts.append({"kind": "preparation", "path": store.state["preparation_bundle"]})
        store.update(state=state, stage="done", result_record=str(saved_result.relative_to(root)),
                     completed_items=successes, total_items=total,
                     artifacts=artifacts, integrity="passed", coverage={"requested": total, "successful": successes, "failed": max(0, total-successes)},
                     diagnostics=diagnostics, output_dir=str(output), needs_review=bool(diagnostics))
        store.event("finished", state=state, integrity="passed")
    except WorkflowCancelled:
        store.update(state="cancelled", stage=store.state["stage"])
        store.event("cancelled")
    except KeyboardInterrupt:
        store.update(state="interrupted")
        store.event("interrupted")
    except WorkflowIntegrityError as exc:
        store.update(state="blocked", diagnostics=[execution.diagnostic("CHECKPOINT_INVALID", exc, stage=store.state["stage"])])
        store.event("failed", code="CHECKPOINT_INVALID", message=execution.scrub(str(exc)))
    except Exception as exc:
        code = "OUTPUT_CONFLICT" if isinstance(exc, FileExistsError) else "WORKFLOW_FAILED"
        if "Checkpoint" in str(exc) or "checkpoint" in str(exc):
            code = "CHECKPOINT_INVALID"
        elif "versions changed" in str(exc):
            code = "ENVIRONMENT_CHANGED"
        diagnostics = [execution.diagnostic(code, exc, stage=store.state["stage"])]
        if execution.provider:
            diagnostics.extend(execution.provider.failures)
        store.update(state="blocked" if code in {"OUTPUT_CONFLICT", "ENVIRONMENT_CHANGED", "CHECKPOINT_INVALID"} else "failed",
                     diagnostics=diagnostics)
        store.event("failed", code=code, message=execution.scrub(str(exc)))
    finally:
        store.update(elapsed_seconds=previous_elapsed + time.monotonic()-started)
    return store.state
