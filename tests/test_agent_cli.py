from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

import diffractscout
from diffractscout import agent_cli
from diffractscout.cli import main as cli_main


@pytest.fixture
def service(monkeypatch):
    calls = []

    class Request:
        @classmethod
        def from_dict(cls, payload, base_dir=None):
            if not isinstance(payload, dict):
                raise ValueError("Request must be an object")
            return {"payload": payload, "base_dir": base_dir}

    def record(name, result):
        def call(*args, **kwargs):
            calls.append((name, args, kwargs))
            return result
        return call

    api = SimpleNamespace(WorkflowRequest=Request)
    results = {"context": {"workflows": ["analyze"]}, "schema": {"type": "object"},
               "plan_workflow": {"stages": ["analyze"]},
               "run_job": {"run_id": "job-1", "state": "completed"},
               "submit_job": {"run_id": "job-1", "state": "pending"},
               "resume_job": {"run_id": "job-1", "state": "pending"},
               "cancel_job": {"run_id": "job-1", "state": "cancelling"},
               "status_job": {"run_id": "job-1", "state": "running"},
               "read_events": {"events": [], "next_after": 0},
               "get_result": {"artifacts": [], "rows": []},
               "list_jobs": [{"run_id": "job-1"}],
               "run_batch": {"state": "completed", "jobs": []}}
    for name, result in results.items():
        setattr(api, name, record(name, result))
    monkeypatch.setattr(diffractscout, "workflow", api, raising=False)
    return api, calls


def test_agent_context_routes_through_existing_cli(service, capsys):
    assert cli_main(["agent", "context"]) == 0
    assert json.loads(capsys.readouterr().out) == {"workflows": ["analyze"]}


@pytest.mark.parametrize("arguments", [[], ["unknown"], ["status"], ["events", "job", "--limit", "no"]])
def test_argument_errors_are_json(arguments, capsys):
    assert agent_cli.main(arguments) == 2
    output = capsys.readouterr()
    assert json.loads(output.out)["error"]["type"] == "ValueError"


@pytest.mark.parametrize("source", ["[]", "{broken", "missing-request.json"])
def test_request_read_errors_are_json(service, source, capsys):
    assert agent_cli.main(["run", source]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_request_file_parent_is_resolution_base(service, tmp_path, capsys):
    path = tmp_path / "request.json"
    path.write_text(json.dumps({"workflow": "analyze", "inputs": ["sample.cif"]}), encoding="utf-8")
    assert agent_cli.main(["run", str(path), "--workspace", str(tmp_path / "jobs")]) == 0
    call = service[1][-1]
    assert call[0] == "run_job"
    assert call[1][0]["base_dir"] == tmp_path
    assert call[2]["workspace"] == str(tmp_path / "jobs")
    assert json.loads(capsys.readouterr().out)["state"] == "completed"


def test_submit_uses_background_service(service, capsys):
    assert agent_cli.main(["--workspace", "jobs", "submit", '{"workflow":"analyze"}']) == 0
    assert service[1][-1][0] == "submit_job"
    assert service[1][-1][2] == {"workspace": "jobs"}
    assert json.loads(capsys.readouterr().out)["state"] == "pending"


def test_stdin_and_provider_progress_do_not_contaminate_json(service, monkeypatch, capsys):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO('{"workflow":"analyze"}'))

    def run(*args, **kwargs):
        print("provider progress")
        return {"state": "partial"}

    service[0].run_job = run
    assert agent_cli.main(["run", "-"]) == 3
    output = capsys.readouterr()
    assert json.loads(output.out) == {"state": "partial"}
    assert "provider progress" in output.err


@pytest.mark.parametrize("state,code", [("completed", 0), ("partial", 3), ("failed", 2),
                                       ("blocked", 2), ("cancelled", 2), ("interrupted", 2),
                                       ("pending", 0), ("running", 0)])
def test_state_exit_codes(service, capsys, state, code):
    service[0].status_job = lambda *args, **kwargs: {"state": state}
    assert agent_cli.main(["status", "job-1"]) == code
    assert json.loads(capsys.readouterr().out)["state"] == state


def test_batch_file_normalizes_each_request(service, tmp_path, capsys):
    manifest = {"schema": "diffractscout_batch_v1", "requests": [
        {"workflow": "analyze", "inputs": ["one.cif"]},
        {"workflow": "analyze", "inputs": ["two.cif"]}], "max_workers": 2}
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert agent_cli.main(["run", str(path)]) == 0
    name, args, kwargs = service[1][-1]
    assert name == "run_batch"
    assert len(args[0]) == 2
    assert all(item["base_dir"] == tmp_path for item in args[0])
    assert kwargs == {"workspace": None, "max_workers": 2, "background": False}
    json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("payload", [
    {"schema": "diffractscout_batch_v1", "requests": []},
    {"schema": "diffractscout_batch_v1", "requests": {}, "max_workers": 1},
    {"schema": "diffractscout_batch_v1", "requests": [{}], "api_key": "forbidden"},
])
def test_invalid_batch_is_rejected(service, payload, capsys):
    assert agent_cli.main(["run", json.dumps(payload)]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert not service[1]


@pytest.mark.parametrize("argv,name,options", [
    (["schema", "request"], "schema", {}),
    (["plan", '{}'], "plan_workflow", {}),
    (["list"], "list_jobs", {"workspace": None}),
    (["cancel", "job-1"], "cancel_job", {"workspace": None}),
    (["resume", "job-1"], "resume_job", {"workspace": None, "background": True}),
    (["resume", "job-1", "--foreground"], "resume_job", {"workspace": None, "background": False}),
    (["events", "job-1", "--after", "5", "--limit", "3"], "read_events",
     {"workspace": None, "after": 5, "limit": 3}),
    (["result", "job-1", "--table", "reflections", "--offset", "4", "--limit", "2"],
     "get_result", {"workspace": None, "table": "reflections", "offset": 4, "limit": 2, "verify": True}),
])
def test_service_dispatch(service, capsys, argv, name, options):
    assert agent_cli.main(argv) == 0
    assert service[1][-1][0] == name
    assert service[1][-1][2] == options
    json.loads(capsys.readouterr().out)


def test_error_does_not_echo_environment_key(service, monkeypatch, capsys):
    monkeypatch.setenv("MP_API_KEY", "sensitive-value")

    def fail(*args, **kwargs):
        raise ValueError("Provider rejected sensitive-value")

    service[0].status_job = fail
    assert agent_cli.main(["status", "job-1"]) == 2
    output = capsys.readouterr().out
    assert "sensitive-value" not in output
    assert "[redacted]" in output


def test_package_exports_do_not_import_optional_mcp():
    import subprocess

    process = subprocess.run([sys.executable, "-c", "import sys, diffractscout; assert 'mcp' not in sys.modules"],
                             env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
                             capture_output=True, text=True)
    assert process.returncode == 0, process.stderr


def test_real_workflow_cli_plan_run_progress_and_result(demo_inputs, tmp_path, capsys):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "schema": "diffractscout_workflow_v1", "workflow": "analyze",
        "inputs": [demo_inputs.name], "output_dir": "bundle",
        "analysis": {"include_elasticity": False, "include_patterns": False},
        "exports": {"include_excel": False},
    }), encoding="utf-8")
    workspace = str(tmp_path / "jobs")
    assert cli_main(["agent", "plan", str(request)]) == 0
    assert isinstance(json.loads(capsys.readouterr().out), dict)
    assert not (tmp_path / "bundle").exists()
    assert cli_main(["agent", "run", str(request), "--workspace", workspace]) == 0
    completed = json.loads(capsys.readouterr().out)
    assert completed["state"] == "completed"
    assert (tmp_path / "bundle").is_dir()
    run_id = completed["run_id"]
    for operation in ("status", "events", "result"):
        assert cli_main(["agent", operation, run_id, "--workspace", workspace]) == 0
        assert isinstance(json.loads(capsys.readouterr().out), dict)


def test_real_workflow_partial_exit_code(demo_inputs, tmp_path, capsys):
    (demo_inputs / "empty.cif").write_text("", encoding="utf-8")
    request = {"workflow": "analyze", "inputs": [str(demo_inputs)],
               "output_dir": str(tmp_path / "partial"),
               "analysis": {"include_elasticity": False, "include_patterns": False},
               "exports": {"include_excel": False}}
    assert cli_main(["agent", "run", json.dumps(request),
                     "--workspace", str(tmp_path / "jobs")]) == 3
    assert json.loads(capsys.readouterr().out)["state"] == "partial"
