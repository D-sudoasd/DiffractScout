"""Delivery, retry, and provenance contracts beyond ordinary happy paths."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from diffractscout.demo import SYNTHETIC_FCC_CIF
from diffractscout.models import CandidateRecord, DownloadArtifact
from diffractscout.workflow import WorkflowRequest, get_result, load_result_object, plan_workflow, run_batch, run_job, status_job


class RetryProvider:
    name = "retry-fixture"

    def __init__(self, error=TimeoutError, failures=2):
        self.error, self.failures = error, failures
        self.queries = self.downloads = 0

    def metadata(self):
        return {"provider": self.name}

    def search_subsystem(self, _system, **_options):
        self.queries += 1
        if self.queries <= self.failures:
            raise self.error("transient query failure")
        return [CandidateRecord("fixture-1", formula="Al")]

    def download_candidates(self, candidates, output_dir, **_options):
        self.downloads += 1
        if self.downloads <= self.failures:
            raise self.error("transient download failure")
        path = output_dir / "fixture.cif"
        path.write_text(SYNTHETIC_FCC_CIF, encoding="utf-8")
        return [DownloadArtifact(candidates[0], path)]


@pytest.mark.parametrize("error,expected_state,attempts", [(TimeoutError, "completed", 3), (ValueError, "failed", 1)])
def test_only_transient_errors_receive_bounded_retries(tmp_path, error, expected_state, attempts):
    provider = RetryProvider(error=error)
    result = run_job({"workflow": "run", "composition": "Al", "analysis": {"include_elasticity": False}},
                     workspace=tmp_path / "jobs", provider=provider)
    assert result["state"] == expected_state, result["diagnostics"]
    assert provider.queries == attempts
    assert provider.downloads == (3 if expected_state == "completed" else 0)


def test_manual_elastic_tensor_survives_portable_replay(tmp_path):
    source = tmp_path / "al.cif"
    source.write_text(SYNTHETIC_FCC_CIF, encoding="utf-8")
    workspace = tmp_path / "jobs"
    first = run_job({"workflow": "analyze", "inputs": [str(source)],
                     "elastic_overrides": {str(source): {"stiffness_GPa": (np.eye(6)*100).tolist(), "source_provider": "manual fixture"}}},
                    workspace=workspace)
    assert first["state"] == "completed", first["diagnostics"]
    assert first["completed_items"] == first["total_items"] == 1
    replay_file = Path(first["output_dir"]) / "replay_request.json"
    replay = WorkflowRequest.from_dict(json.loads(replay_file.read_text()), base_dir=replay_file.parent)
    second = run_job(replay, workspace=workspace)
    assert second["state"] == "completed", second["diagnostics"]
    expected = load_result_object(first["run_id"], workspace=workspace)
    actual = load_result_object(second["run_id"], workspace=workspace)
    assert actual.analyses[0].reflections[0].young_modulus_hkl_normal_GPa == expected.analyses[0].reflections[0].young_modulus_hkl_normal_GPa
    assert actual.analyses[0].elastic_tensor.source_provider == "manual fixture"


def test_relative_tensor_identity_resolves_against_request_file(tmp_path):
    request = WorkflowRequest.from_dict({"workflow": "analyze", "inputs": ["inputs/al.cif"],
        "elastic_overrides": {"inputs/al.cif": {"stiffness_GPa": (np.eye(6)*100).tolist()}}}, base_dir=tmp_path)
    assert request.inputs[0] in request.elastic_overrides


def test_plan_preserves_user_values_and_declared_defaults(tmp_path):
    source = tmp_path / "al.cif"
    source.write_text(SYNTHETIC_FCC_CIF)
    request = WorkflowRequest.from_dict({"workflow": "analyze", "inputs": [str(source)], "analysis": {"energy_keV": 100}})
    plan = plan_workflow(request)
    assert plan["parameter_sources"]["analysis"]["energy_keV"] == "request"
    assert plan["parameter_sources"]["analysis"]["step_deg"] == "default"
    assert plan["parameter_sources"]["analysis"]["input_mode"] == "derived_from_energy_keV"


def test_empty_peak_table_is_not_reported_as_complete_reference(tmp_path):
    source = tmp_path / "al.cif"
    source.write_text(SYNTHETIC_FCC_CIF)
    status = run_job({"workflow": "analyze", "inputs": [str(source)],
                      "analysis": {"two_theta_min_deg": 0, "two_theta_max_deg": 1, "include_elasticity": False}}, workspace=tmp_path / "jobs")
    assert status["state"] == "partial"
    assert any(item["code"] == "EMPTY_REFLECTION_TABLE" for item in status["diagnostics"])
    assert get_result(status["run_id"], workspace=tmp_path / "jobs")["integrity"] == "passed"


def test_background_batch_keeps_valid_jobs_when_one_request_is_invalid(tmp_path):
    source = tmp_path / "al.cif"
    source.write_text(SYNTHETIC_FCC_CIF)
    workspace = tmp_path / "jobs"
    response = run_batch([{"workflow": "analyze", "inputs": [str(source)]}, {"workflow": "invalid"}],
                         workspace=workspace, background=True)
    assert response["jobs"][1]["state"] == "failed"
    run_id = response["jobs"][0]["run_id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = status_job(run_id, workspace=workspace)
        if status["state"] not in {"pending", "running"}:
            break
        time.sleep(0.1)
    assert status["state"] == "completed", status


def test_background_batch_preserves_order_and_schedules_duplicate_id_once(tmp_path):
    from diffractscout.workflow.store import process_alive
    source = tmp_path / "al.cif"
    source.write_text(SYNTHETIC_FCC_CIF)
    workspace = tmp_path / "jobs"
    request = {"workflow": "analyze", "inputs": [str(source)], "submission_id": "duplicate-in-batch"}
    response = run_batch([{"workflow": "invalid"}, request, request], workspace=workspace, background=True)
    assert response["jobs"][0]["state"] == "failed"
    run_id = response["jobs"][1]["run_id"]
    assert response["jobs"][2]["run_id"] == run_id
    root = workspace / "jobs" / run_id
    launch = json.loads((root / "launch.json").read_text())
    deadline = time.monotonic() + 30
    while process_alive(launch["pid"]) and time.monotonic() < deadline:
        time.sleep(0.1)
    status = status_job(run_id, workspace=workspace)
    assert status["state"] == "completed", status
    assert status["attempt"] == 1


def test_exited_worker_is_not_kept_alive_by_a_process_handle():
    import os
    import subprocess
    import sys
    from diffractscout.workflow.store import process_alive
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with subprocess.Popen([sys.executable, "-c", "pass"], **kwargs) as child:
        child.wait(timeout=10)
        assert process_alive(child.pid) is False
        assert process_alive(os.getpid()) is True


def test_retry_limit_cannot_exceed_three():
    with pytest.raises(ValueError, match="between 1 and 3"):
        WorkflowRequest.from_dict({"workflow": "discover", "composition": "Al", "execution": {"max_attempts": 4}})


def test_published_bundle_is_recoverable_after_acknowledgement_failure(tmp_path, monkeypatch):
    from diffractscout.workflow import runner, resume_job
    from diffractscout.validation import verify_bundle
    source = tmp_path / "al.cif"
    source.write_text(SYNTHETIC_FCC_CIF)
    workspace = tmp_path / "jobs"
    original = runner.result_record
    monkeypatch.setattr(runner, "result_record", lambda *args: (_ for _ in ()).throw(OSError("record write failed")))
    first = run_job({"workflow": "analyze", "inputs": [str(source)]}, workspace=workspace)
    assert first["state"] == "failed"
    assert verify_bundle(first["output_dir"])["ok"]
    monkeypatch.setattr(runner, "result_record", original)
    recovered = resume_job(first["run_id"], workspace=workspace, background=False)
    assert recovered["state"] == "completed", recovered["diagnostics"]
    assert recovered["counters"]["analyses"] == 1
    assert first["output_dir"] in recovered["recovered_bundles"]
    assert verify_bundle(first["output_dir"])["ok"]
    assert verify_bundle(recovered["output_dir"])["ok"]


def test_discovery_replay_retains_discovery_request(tmp_path):
    provider = RetryProvider(failures=0)
    result = run_job({"workflow": "discover", "composition": "Al"}, workspace=tmp_path / "jobs", provider=provider)
    path = Path(result["output_dir"]) / "replay_request.json"
    request = WorkflowRequest.from_dict(json.loads(path.read_text()), base_dir=path.parent)
    assert request.workflow == "discover"
    assert request.composition == "Al"
    assert plan_workflow(request, provider=provider)["ready"]


def test_frozen_worker_launch_uses_app_dispatch(monkeypatch):
    from diffractscout.workflow import service
    captured = {}
    monkeypatch.setattr(service.sys, "frozen", True, raising=False)
    monkeypatch.setattr(service.subprocess, "Popen", lambda command, **kwargs: captured.update(command=command, **kwargs))
    service._spawn(["--run-id", "a"*32, "--workspace", "example"])
    assert captured["command"][1] == "_agent-worker"
    assert captured["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


@pytest.mark.parametrize("workflow", ["fetch", "adapt"])
def test_explicit_derivations_remain_offline_and_replayable(tmp_path, workflow):
    import diffractscout
    source = Path(diffractscout.__file__).parent / "prototype_data" / "cod_9008554_beta_ti.cif"
    request = {"workflow": workflow, "composition": "Ti"}
    if workflow == "fetch":
        request["preparation"] = {"phases": ["beta"], "templates": {"beta": str(source)}}
    else:
        request["inputs"] = [str(source)]
        request["adaptation"] = {"atomic_percent": "Ti=100", "a": 3.3, "citation": "synthetic test value"}
    workspace = tmp_path / "jobs"
    result = run_job(request, workspace=workspace)
    assert result["state"] == "completed", result["diagnostics"]
    assert result["counters"]["queries"] == result["counters"]["downloads"] == 0
    assert get_result(result["run_id"], workspace=workspace)["integrity"] == "passed"
    restored = load_result_object(result["run_id"], workspace=workspace)
    if workflow == "fetch":
        assert restored.records[0].cif_path.is_file()
    else:
        assert restored.cif_path.is_file() and restored.sidecar_path.is_file()
    path = Path(result["output_dir"]) / "replay_request.json"
    replay = WorkflowRequest.from_dict(json.loads(path.read_text()), base_dir=path.parent)
    assert plan_workflow(replay)["ready"]
