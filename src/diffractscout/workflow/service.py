"""Public workflow API used unchanged by CLI, desktop and MCP clients."""
from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from ..pipeline import _validate_input_output_separation
from ..utils import utc_now_iso, write_json
from .checkpoints import environment, fingerprint
from .contracts import WorkflowRequest, plan_workflow
from .results import get_result
from .snapshots import snapshot_request
from .store import TERMINAL, events_page, file_lock, is_locked, job_path, process_alive, read_json, workspace_path


def _create(request, *, workspace=None, provider=None, api_key=None):
    provided = getattr(request, "_provided_fields", None)
    request = WorkflowRequest.from_dict(request.to_dict() if isinstance(request, WorkflowRequest) else request)
    if provided is not None:
        request._provided_fields = provided
    workspace = workspace_path(workspace)
    run_id = uuid5(NAMESPACE_URL, request.submission_id).hex if request.submission_id else uuid4().hex
    root = job_path(workspace, run_id)
    _validate_input_output_separation(request.inputs, root)
    digest = fingerprint(request.to_dict())
    workspace.mkdir(parents=True, exist_ok=True)
    with file_lock(workspace / "submissions.lock", blocking=True):
        if root.exists():
            state = read_json(root / "state.json")
            if state["request_hash"] != digest:
                raise ValueError("submission_id already identifies a different request; use a new submission_id.")
            return root, False
        plan = plan_workflow(request, provider=provider, api_key=api_key)
        root.mkdir(parents=True)
        write_json(root / "request.json", request.to_dict())
        write_json(root / "plan.json", plan)
        write_json(root / "environment.json", environment())
        now = utc_now_iso()
        state = {"schema": "diffractscout_run_v1", "run_id": run_id, "name": request.name or request.workflow,
                 "workflow": request.workflow, "workspace": str(workspace), "request_hash": digest,
                 "state": "pending" if plan["ready"] else "blocked", "stage": "planning", "attempt": 0,
                 "created_at": now, "updated_at": now, "completed_items": 0, "total_items": 0,
                 "diagnostics": plan["diagnostics"], "artifacts": [], "integrity": "not_checked", "coverage": {},
                 "counters": {"queries": 0, "downloads": 0, "analyses": 0, "preparations": 0, "reused": 0},
                 "elapsed_seconds": 0.0, "output_dir": request.output_dir or str(root / "bundle")}
        write_json(root / "state.json", state)
        if plan["ready"]:
            try:
                snapshot_request(root, request)
            except Exception as exc:
                state.update(state="blocked", diagnostics=[{"code": "SNAPSHOT_FAILED", "message": str(exc),
                    "stage": "snapshot", "item": "", "retryable": False, "missing_fields": []}])
                write_json(root / "state.json", state)
    return root, True


def _spawn(arguments: list[str], *, api_key=None) -> subprocess.Popen:
    env = os.environ.copy()
    source = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"
    if api_key:
        env["MP_API_KEY"] = api_key
    kwargs = {"env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        command = [sys.executable, "_agent-worker", *arguments]
    else:
        command = [sys.executable, "-m", "diffractscout.workflow.worker", *arguments]
    return subprocess.Popen(command, **kwargs)


def _launch(root: Path, *, api_key=None) -> None:
    attempt = read_json(root / "state.json")["attempt"]
    process = _spawn(["--workspace", str(root.parent.parent), "--run-id", root.name, "--expected-attempt", str(attempt)], api_key=api_key)
    write_json(root / "launch.json", {"pid": process.pid, "created_at": utc_now_iso()})


def run_job(request, *, workspace=None, provider=None, api_key=None) -> dict:
    root, created = _create(request, workspace=workspace, provider=provider, api_key=api_key)
    if not created or read_json(root / "state.json")["state"] == "blocked":
        return status_job(root.name, workspace=root.parent.parent)
    from .runner import execute
    return execute(root, provider=provider, api_key=api_key, expected_attempt=0)


def submit_job(request, *, workspace=None, api_key=None) -> dict:
    root, created = _create(request, workspace=workspace, api_key=api_key)
    if created and read_json(root / "state.json")["state"] == "pending":
        _launch(root, api_key=api_key)
    return status_job(root.name, workspace=root.parent.parent)


def status_job(run_id: str, *, workspace=None) -> dict:
    root = job_path(workspace, run_id)
    state = read_json(root / "state.json")
    active = is_locked(root / "worker.lock")
    if state["state"] in {"running", "cancelling"} and not active:
        state["state"] = "interrupted"
    elif state["state"] == "pending" and (root / "launch.json").exists():
        if not process_alive(read_json(root / "launch.json")["pid"]):
            state["state"] = "interrupted"
    if (root / "cancel.json").exists() and state["state"] not in {"completed", "partial", "failed"}:
        state["state"] = "cancelling" if active else "cancelled"
    state["active"] = active
    return state


def list_jobs(*, workspace=None) -> list[dict]:
    base = workspace_path(workspace)
    if not (base / "jobs").exists():
        return []
    rows = [status_job(root.name, workspace=base) for root in (base / "jobs").iterdir()
            if root.is_dir() and (root / "state.json").exists()]
    return sorted(rows, key=lambda row: (row["created_at"], row["run_id"]), reverse=True)


def read_events(run_id: str, *, workspace=None, after=0, limit=100) -> dict:
    root = job_path(workspace, run_id)
    if not (root / "state.json").is_file():
        raise FileNotFoundError(f"Task not found: {run_id}")
    return {"run_id": run_id, **events_page(root, after=after, limit=limit)}


def cancel_job(run_id: str, *, workspace=None) -> dict:
    root = job_path(workspace, run_id)
    state = status_job(run_id, workspace=workspace)
    if state["state"] not in TERMINAL or state["state"] in {"blocked", "interrupted"}:
        write_json(root / "cancel.json", {"requested_at": utc_now_iso()})
    return status_job(run_id, workspace=workspace)


def resume_job(run_id: str, *, workspace=None, background=True, provider=None, api_key=None) -> dict:
    root = job_path(workspace, run_id)
    with file_lock(root / "control.lock", blocking=True):
        state = status_job(run_id, workspace=workspace)
        if state["active"]:
            return state
        if state["state"] == "completed":
            get_result(run_id, workspace=workspace)
            return state
        if background and provider is not None:
            raise ValueError("Injected Python providers require background=False.")
        launch = root / "launch.json"
        if launch.exists() and process_alive(read_json(launch)["pid"]):
            return state
        (root / "cancel.json").unlink(missing_ok=True)
        if background:
            _launch(root, api_key=api_key)
        else:
            from .runner import execute
            return execute(root, provider=provider, api_key=api_key, expected_attempt=state["attempt"])
    return status_job(run_id, workspace=workspace)


def run_batch(requests, *, workspace=None, max_workers=1, background=False) -> dict:
    if not isinstance(requests, (list, tuple)) or not requests:
        raise ValueError("A batch must contain at least one request.")
    if type(max_workers) is not int or max_workers < 1:
        raise ValueError("max_workers must be a positive integer.")
    max_workers = min(max_workers, len(requests))
    base = workspace_path(workspace)
    if background:
        roots, entries = [], []
        for request in requests:
            try:
                root = _create(request, workspace=base)[0]
                roots.append(root)
                entries.append(root)
            except (ValueError, OSError, RuntimeError) as exc:
                entries.append({"state": "failed", "diagnostics": [{"code": "INVALID_REQUEST", "message": str(exc)}]})
        if not roots:
            return {"state": "failed", "jobs": entries}
        # Repeated submission IDs are references to one task, not invitations
        # for the batch scheduler to execute the same task a second time.
        roots = list(dict.fromkeys(roots))
        batch_id = uuid4().hex
        batch_path = base / "batches" / (batch_id + ".json")
        write_json(batch_path, {"run_ids": [root.name for root in roots], "max_workers": max_workers})
        process = _spawn(["--workspace", str(base), "--batch-id", batch_id])
        for root in roots:
            write_json(root / "launch.json", {"pid": process.pid, "created_at": utc_now_iso()})
        return {"batch_id": batch_id, "state": "pending", "jobs": [status_job(entry.name, workspace=base) if isinstance(entry, Path) else entry for entry in entries]}
    def run(request):
        try:
            return run_job(request, workspace=base)
        except (ValueError, OSError, RuntimeError) as exc:
            return {"state": "failed", "diagnostics": [{"code": "INVALID_REQUEST", "message": str(exc)}]}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        jobs = list(pool.map(run, requests))
    successes = sum(row["state"] == "completed" for row in jobs)
    state = "completed" if successes == len(jobs) else "partial" if any(row["state"] in {"completed", "partial"} for row in jobs) else "failed"
    return {"state": state, "jobs": jobs, "completed": successes, "total": len(jobs)}
