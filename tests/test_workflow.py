"""Offline integration checks for durable workflow execution and recovery."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from diffractscout import pipeline
from diffractscout.demo import SYNTHETIC_FCC_CIF
from diffractscout.models import AnalysisSettings, CandidateRecord, DownloadArtifact
from diffractscout.utils import write_json
from diffractscout.validation import verify_bundle
from diffractscout.workflow import (
    cancel_job,
    get_result,
    list_jobs,
    load_result_object,
    read_events,
    resume_job,
    run_batch,
    run_job,
    status_job,
    submit_job,
)
from diffractscout.workflow import service


class CountingProvider:
    """An offline provider that records actual external-operation boundaries."""

    name = "Offline counting provider"

    def __init__(self, count=1, *, query_error=None):
        self.candidates = [CandidateRecord(f"mp-{index + 1}", formula="Al") for index in range(count)]
        self.queries = Counter()
        self.downloads = Counter()
        self.query_error = query_error

    def metadata(self):
        return {"provider": self.name, "offline_fixture": True}

    def search_subsystem(self, chemsys, **kwargs):
        self.queries[chemsys] += 1
        if self.query_error:
            raise self.query_error
        return list(self.candidates)

    def search_material_ids(self, material_ids, **kwargs):
        self.queries[tuple(material_ids)] += 1
        return [item for item in self.candidates if item.material_id in material_ids]

    def download_candidates(self, candidates, output_dir, **kwargs):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for candidate in candidates:
            self.downloads[candidate.material_id] += 1
            path = output_dir / f"{candidate.material_id}.cif"
            path.write_text(SYNTHETIC_FCC_CIF, encoding="utf-8")
            artifacts.append(DownloadArtifact(candidate, path))
        return artifacts


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("MP_API_KEY", raising=False)
    return tmp_path / "workspace"


def request_for(inputs, **changes):
    request = {
        "workflow": "analyze", "inputs": [str(path) for path in inputs],
        "analysis": {"step_deg": 0.2, "two_theta_max_deg": 80, "include_elasticity": False},
        "exports": {"include_excel": False},
    }
    request.update(changes)
    return request


def root_for(workspace, status):
    return workspace / "jobs" / status["run_id"]


def instrument_calculations(monkeypatch):
    original = pipeline.simulate_powder_pattern
    calls = Counter()

    def counted(structure, *args, **kwargs):
        calls[structure.cif_path.name] += 1
        return original(structure, *args, **kwargs)

    monkeypatch.setattr(pipeline, "simulate_powder_pattern", counted)
    return calls


def fail_export_once(monkeypatch):
    original = pipeline.export_result_bundle
    attempts = []

    def export(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("Injected export failure after numerical work")
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "export_result_bundle", export)
    return attempts


@pytest.mark.parametrize("count", [1, 2])
def test_local_results_match_existing_pipeline_and_verify(demo_inputs, tmp_path, workspace, count):
    inputs = [demo_inputs / "synthetic_fcc_al.cif"]
    if count == 2:
        second = demo_inputs / "second.cif"
        second.write_text(SYNTHETIC_FCC_CIF.replace("4.000000", "4.100000"), encoding="utf-8")
        inputs.append(second)
    raw = request_for(inputs)
    settings = AnalysisSettings(**raw["analysis"])
    baseline = pipeline.analyze_cifs(inputs, tmp_path / "baseline", settings=settings, include_excel=False)
    status = run_job(raw, workspace=workspace)
    assert status["state"] == "completed", status["diagnostics"]
    result = load_result_object(status["run_id"], workspace=workspace)
    assert len(result.analyses) == count
    for expected, actual in zip(baseline.analyses, result.analyses, strict=True):
        assert expected.phase_name == actual.phase_name
        assert [asdict(row) for row in expected.reflections] == [asdict(row) for row in actual.reflections]
        np.testing.assert_array_equal(expected.two_theta_grid, actual.two_theta_grid)
        np.testing.assert_allclose(expected.intensity_profile, actual.intensity_profile, rtol=0, atol=0)
        assert actual.structure.cif_path.is_file()
    assert verify_bundle(status["output_dir"])["ok"]
    response = get_result(status["run_id"], workspace=workspace, table="peak_reference", limit=1)
    assert len(response["rows"]) == 1
    assert response["integrity"] == "passed"


def test_export_failure_resume_reuses_queries_downloads_and_calculations(workspace, monkeypatch):
    provider = CountingProvider(count=2)
    calculations = instrument_calculations(monkeypatch)
    exports = fail_export_once(monkeypatch)
    status = run_job(request_for([], workflow="run", composition="Al"), workspace=workspace, provider=provider)
    assert status["state"] == "failed", status["diagnostics"]
    assert sum(calculations.values()) == 2
    assert provider.queries == {"Al": 1}
    assert provider.downloads == {"mp-1": 1, "mp-2": 1}
    resumed = resume_job(status["run_id"], workspace=workspace, background=False, provider=provider)
    assert resumed["state"] == "completed", resumed["diagnostics"]
    assert len(exports) == 2
    assert sum(calculations.values()) == 2
    assert provider.queries == {"Al": 1}
    assert provider.downloads == {"mp-1": 1, "mp-2": 1}
    assert resumed["counters"]["reused"] >= 5
    assert verify_bundle(resumed["output_dir"])["ok"]


@pytest.mark.parametrize("explicit_output", [False, True])
def test_partial_phase_resume_recomputes_only_failure(workspace, tmp_path, monkeypatch, explicit_output):
    provider = CountingProvider(count=2)
    original = pipeline.simulate_powder_pattern
    calls = Counter()

    def fail_second_once(structure, *args, **kwargs):
        name = structure.cif_path.name
        calls[name] += 1
        if "mp-2" in name and calls[name] == 1:
            raise ValueError("Injected one-phase calculation failure")
        return original(structure, *args, **kwargs)

    monkeypatch.setattr(pipeline, "simulate_powder_pattern", fail_second_once)
    raw = request_for([], workflow="run", composition="Al")
    if explicit_output:
        raw["output_dir"] = str(tmp_path / "external-result")
    status = run_job(raw, workspace=workspace, provider=provider)
    assert status["state"] == "partial", status["diagnostics"]
    first_output = Path(status["output_dir"])
    assert verify_bundle(first_output)["ok"]
    resumed = resume_job(status["run_id"], workspace=workspace, background=False, provider=provider)
    assert resumed["state"] == "completed", resumed["diagnostics"]
    assert calls["mp-1.cif"] == 1
    assert calls["mp-2.cif"] == 2
    assert provider.queries == {"Al": 1}
    assert provider.downloads == {"mp-1": 1, "mp-2": 1}
    assert Path(resumed["output_dir"]) != first_output
    assert verify_bundle(first_output)["ok"]
    assert verify_bundle(resumed["output_dir"])["ok"]


@pytest.mark.parametrize("mutation", ["change", "remove"])
def test_resume_uses_frozen_sources_after_original_changes(demo_inputs, workspace, monkeypatch, mutation):
    source = demo_inputs / "synthetic_fcc_al.cif"
    original_bytes = source.read_bytes()
    fail_export_once(monkeypatch)
    calculations = instrument_calculations(monkeypatch)
    status = run_job(request_for([source]), workspace=workspace)
    assert status["state"] == "failed", status["diagnostics"]
    if mutation == "change":
        source.write_text("no longer a valid CIF", encoding="utf-8")
    else:
        shutil.rmtree(demo_inputs)
    resumed = resume_job(status["run_id"], workspace=workspace, background=False)
    assert resumed["state"] == "completed", resumed["diagnostics"]
    assert sum(calculations.values()) == 1
    assert (Path(resumed["output_dir"]) / "inputs" / source.name).read_bytes() == original_bytes


@pytest.mark.parametrize("checkpoint_kind", ["analyses", "queries", "downloads", "sources"])
def test_corrupt_checkpoint_is_never_reused(workspace, monkeypatch, checkpoint_kind):
    provider = CountingProvider()
    calculations = instrument_calculations(monkeypatch)
    fail_export_once(monkeypatch)
    status = run_job(request_for([], workflow="run", composition="Al"), workspace=workspace, provider=provider)
    assert status["state"] == "failed", status["diagnostics"]
    directory = root_for(workspace, status) / checkpoint_kind
    sealed = next(directory.rglob("checkpoint.json")).parent
    manifest = json.loads((sealed / "checkpoint.json").read_text(encoding="utf-8"))
    member = sealed / manifest["files"][0]["path"]
    member.write_bytes(member.read_bytes() + b"corruption")
    before = dict(calculations)
    resumed = resume_job(status["run_id"], workspace=workspace, background=False, provider=provider)
    assert resumed["state"] == "blocked", resumed["diagnostics"]
    assert any(item["code"] == "CHECKPOINT_INVALID" for item in resumed["diagnostics"])
    assert calculations == before
    assert not Path(resumed["output_dir"]).exists()


def test_duplicate_submission_is_idempotent_and_rejects_changed_request(demo_inputs, workspace, monkeypatch):
    calculations = instrument_calculations(monkeypatch)
    raw = request_for([demo_inputs / "synthetic_fcc_al.cif"], submission_id="identical-offline-submission")
    first = run_job(raw, workspace=workspace)
    duplicate = run_job(json.loads(json.dumps(raw)), workspace=workspace)
    assert first["state"] == duplicate["state"] == "completed"
    assert duplicate["run_id"] == first["run_id"]
    assert sum(calculations.values()) == 1
    assert len(list_jobs(workspace=workspace)) == 1
    with pytest.raises(ValueError, match="different request"):
        run_job({**raw, "name": "changed request"}, workspace=workspace)
    assert sum(calculations.values()) == 1


def test_parent_run_reuses_only_matching_analysis_inputs(demo_inputs, workspace, monkeypatch):
    calculations = instrument_calculations(monkeypatch)
    raw = request_for([demo_inputs / "synthetic_fcc_al.cif"])
    parent = run_job(raw, workspace=workspace)
    child = run_job({**raw, "parent_run_id": parent["run_id"]}, workspace=workspace)
    assert parent["state"] == child["state"] == "completed"
    assert parent["run_id"] != child["run_id"]
    assert sum(calculations.values()) == 1
    assert child["counters"]["analyses"] == 0
    assert verify_bundle(child["output_dir"])["ok"]
    changed = {**raw, "parent_run_id": parent["run_id"], "analysis": {**raw["analysis"], "step_deg": 0.1}}
    changed_child = run_job(changed, workspace=workspace)
    assert changed_child["state"] == "completed", changed_child["diagnostics"]
    assert changed_child["counters"]["analyses"] == 1
    assert sum(calculations.values()) == 2


def test_cancellation_resumes_from_last_successful_phase(demo_inputs, workspace, monkeypatch):
    inputs = [demo_inputs / "synthetic_fcc_al.cif", demo_inputs / "second.cif"]
    inputs[1].write_text(SYNTHETIC_FCC_CIF, encoding="utf-8")
    original = pipeline.simulate_powder_pattern
    calls = Counter()

    def cancel_after_first(structure, *args, **kwargs):
        calls[structure.cif_path.name] += 1
        result = original(structure, *args, **kwargs)
        if sum(calls.values()) == 1:
            current = list_jobs(workspace=workspace)[0]
            cancel_job(current["run_id"], workspace=workspace)
        return result

    monkeypatch.setattr(pipeline, "simulate_powder_pattern", cancel_after_first)
    status = run_job(request_for(inputs), workspace=workspace)
    assert status["state"] == "cancelled", status["diagnostics"]
    assert sum(calls.values()) == 1
    resumed = resume_job(status["run_id"], workspace=workspace, background=False)
    assert resumed["state"] == "completed", resumed["diagnostics"]
    assert sum(calls.values()) == 2
    events = read_events(status["run_id"], workspace=workspace)["events"]
    assert "cancelled" in {row["event"] for row in events}
    assert [row["sequence"] for row in events] == sorted({row["sequence"] for row in events})


def test_keyboard_interruption_releases_lock_and_can_resume(demo_inputs, workspace, monkeypatch):
    original = pipeline.simulate_powder_pattern
    attempts = []

    def interrupt_once(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise KeyboardInterrupt()
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "simulate_powder_pattern", interrupt_once)
    status = run_job(request_for([demo_inputs / "synthetic_fcc_al.cif"]), workspace=workspace)
    assert status["state"] == "interrupted"
    assert status_job(status["run_id"], workspace=workspace)["active"] is False
    resumed = resume_job(status["run_id"], workspace=workspace, background=False)
    assert resumed["state"] == "completed", resumed["diagnostics"]
    assert len(attempts) == 2


def test_parallel_resume_callers_have_one_calculation_owner(demo_inputs, workspace, monkeypatch):
    monkeypatch.setattr(service, "_launch", lambda *args, **kwargs: None)
    status = submit_job(request_for([demo_inputs / "synthetic_fcc_al.cif"]), workspace=workspace)
    entered, release, second_entered = Event(), Event(), Event()
    original = pipeline.simulate_powder_pattern
    attempts = []

    def hold_calculation(*args, **kwargs):
        attempts.append(1)
        entered.set()
        assert release.wait(10), "test did not release the active worker"
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "simulate_powder_pattern", hold_calculation)

    def competing_resume():
        second_entered.set()
        return resume_job(status["run_id"], workspace=workspace, background=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(resume_job, status["run_id"], workspace=workspace, background=False)
        try:
            assert entered.wait(10), "worker did not reach a calculation"
            other = pool.submit(competing_resume)
            assert second_entered.wait(5)
            assert status_job(status["run_id"], workspace=workspace)["active"] is True
        finally:
            release.set()
        finished = owner.result(timeout=10)
        second_status = other.result(timeout=10)
    assert finished["state"] == "completed", finished["diagnostics"]
    assert second_status["state"] in {"running", "completed"}
    assert len(attempts) == 1


def test_stale_running_state_is_reported_interrupted(demo_inputs, workspace, monkeypatch):
    monkeypatch.setattr(service, "_launch", lambda *args, **kwargs: None)
    status = submit_job(request_for([demo_inputs / "synthetic_fcc_al.cif"]), workspace=workspace)
    state_path = root_for(workspace, status) / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(state="running", stage="analysis", worker_pid=2147483647)
    write_json(state_path, state)
    assert status_job(status["run_id"], workspace=workspace)["state"] == "interrupted"
    resumed = resume_job(status["run_id"], workspace=workspace, background=False)
    assert resumed["state"] == "completed", resumed["diagnostics"]


def test_batch_mixed_success_is_reported_without_losing_success(demo_inputs, workspace):
    response = run_batch([
        request_for([demo_inputs / "synthetic_fcc_al.cif"]),
        request_for([demo_inputs / "missing.cif"]),
    ], workspace=workspace, max_workers=2)
    assert response["state"] == "partial"
    assert response["completed"] == 1
    assert response["total"] == 2
    assert response["jobs"][0]["state"] == "completed"
    assert response["jobs"][1]["state"] in {"blocked", "failed"}
    assert verify_bundle(response["jobs"][0]["output_dir"])["ok"]


def test_empty_discovery_is_distinct_from_query_failure(workspace):
    raw = request_for([], workflow="discover", composition="Al")
    empty = run_job(raw, workspace=workspace, provider=CountingProvider(count=0))
    failed = run_job(raw, workspace=workspace, provider=CountingProvider(count=0, query_error=ValueError("offline query rejected")))
    assert empty["state"] == "completed", empty["diagnostics"]
    assert empty["coverage"]["successful"] == 0
    assert failed["state"] == "failed", failed["diagnostics"]
    assert any(row["code"] == "QUERY_FAILED" for row in failed["diagnostics"])
    assert not any(row["code"] == "QUERY_FAILED" for row in empty["diagnostics"])


def test_offline_preparation_and_analysis_produce_verified_models(workspace):
    status = run_job(request_for([], workflow="prepare_analyze", composition="Ti", preparation={
        "offline": True, "phases": ["beta"],
    }), workspace=workspace)
    assert status["state"] == "completed", status["diagnostics"]
    assert status["counters"]["preparations"] == 1
    assert status["counters"]["analyses"] == 1
    assert status["coverage"] == {"requested": 1, "successful": 1, "failed": 0}
    assert status["counters"]["queries"] == status["counters"]["downloads"] == 0
    assert verify_bundle(status["output_dir"])["ok"]
    assert verify_bundle(status["preparation_bundle"])["ok"]
    result = load_result_object(status["run_id"], workspace=workspace)
    assert len(result.analyses) == 1
    assert result.analyses[0].structure.space_group_number == 229
