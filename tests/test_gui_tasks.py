"""Task controls exercised through real Tk widgets with offline workflow doubles."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from diffractscout import gui, gui_cifs, gui_tasks
from diffractscout.gui_i18n import t
from diffractscout.workflow.contracts import WorkflowRequest
from diffractscout.models import AnalysisSettings, DiscoverySettings


def pump(root, predicate, timeout=5):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        root.update()
        time.sleep(0.01)
    assert predicate()


def make_app():
    try:
        return gui.create_app()
    except RuntimeError as exc:
        if str(exc) == "Tkinter is unavailable in this Python installation.":
            pytest.skip(str(exc))
        raise
    except Exception as exc:
        if gui._is_known_gui_startup_tcl_error(exc):
            pytest.skip(str(exc))
        raise


class FakeWorkflow:
    WorkflowRequest = WorkflowRequest

    def __init__(self):
        self.jobs = {"old-run": dict(run_id="old-run", name="Saved analysis", workflow="analyze",
                                    state="interrupted", stage="analysis", completed_items=2,
                                    total_items=3, diagnostics=[{"code": "missing_input", "message": "missing.cif"}])}
        self.calls = []
        self.result = object()
        self.bad_integrity = False

    def record(self, action, **kwargs):
        self.calls.append((action, kwargs, threading.get_ident()))

    def list_jobs(self, **kwargs):
        self.record("list", **kwargs)
        return [dict(job) for job in self.jobs.values()]

    def submit_job(self, request, **kwargs):
        self.record("submit", request=request.to_dict(), **kwargs)
        job = dict(run_id="new-run", workflow=request.workflow, name=request.name,
                   state="running", stage="analysis", completed_items=0, total_items=3)
        self.jobs[job["run_id"]] = job
        return dict(job)

    def status_job(self, run_id, **kwargs):
        return dict(self.jobs[run_id])

    def resume_job(self, run_id, **kwargs):
        self.record("resume", run_id=run_id, **kwargs)
        self.jobs[run_id]["state"] = "running"
        return dict(self.jobs[run_id])

    def cancel_job(self, run_id, **kwargs):
        self.record("cancel", run_id=run_id, **kwargs)
        self.jobs[run_id]["state"] = "cancelled"
        return dict(self.jobs[run_id])

    def get_result(self, run_id, **kwargs):
        self.record("verify", run_id=run_id, **kwargs)
        if self.bad_integrity:
            raise ValueError("Result hash changed")
        return {"run_id": run_id, "artifacts": []}

    def load_result_object(self, run_id, **kwargs):
        self.record("load", run_id=run_id, **kwargs)
        return self.result

    def read_events(self, run_id, **kwargs):
        return {"events": [{"message": "checkpoint written"}]}


@pytest.fixture
def task_window(monkeypatch, tmp_path):
    if gui_tasks.tk is None:
        pytest.skip("Tk is unavailable")
    try:
        root = gui_tasks.tk.Tk()
    except gui_tasks.tk.TclError as exc:
        pytest.skip(str(exc))
    root.withdraw()
    api = FakeWorkflow()
    monkeypatch.setattr(gui_tasks, "workflow_api", lambda: api)
    lang = ["zh"]
    delivered = []
    view = gui_tasks.TasksView(root, translate=lambda key, **fmt: t(lang[0], key, **fmt),
                              on_result=lambda result: delivered.append((result, threading.get_ident())),
                              api_key=lambda: "runtime-key")
    view.workspace.set(str(tmp_path / "workspace"))
    view.pack(fill="both", expand=True)
    view.refresh()
    pump(root, lambda: bool(view.tree.get_children()))
    yield root, view, api, lang, delivered
    root.destroy()


def test_history_resume_cancel_counts_and_thread_boundary(task_window):
    root, view, api, lang, delivered = task_window
    view.tree.selection_set("old-run")
    view.tree.event_generate("<<TreeviewSelect>>")
    root.update()
    assert view.tree.set("old-run", "counts") == "2 / 3"
    assert "missing.cif" in view.details.get("1.0", "end")
    assert view.resume_button.instate(("!disabled",))
    view.resume_button.invoke()
    pump(root, lambda: api.jobs["old-run"]["state"] == "running")
    pump(root, lambda: view.cancel_button.instate(("!disabled",)))
    view.cancel_button.invoke()
    pump(root, lambda: api.jobs["old-run"]["state"] == "cancelled")
    assert all(thread != threading.get_ident() for _, _, thread in api.calls)
    assert not delivered
    lang[0] = "en"
    view.refresh_language()
    assert view.resume_button.cget("text") == "Resume"
    assert view.tree.heading("counts", "text") == "Done / total"


def test_import_resolves_relative_paths_and_keeps_key_out_of_request(task_window, tmp_path, monkeypatch):
    root, view, api, lang, delivered = task_window
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps({"schema": "diffractscout_workflow_v1", "workflow": "analyze",
                                        "inputs": ["structure.cif"], "output_dir": "results"}), encoding="utf-8")
    monkeypatch.setattr(gui_tasks.filedialog, "askopenfilename", lambda **_: str(request_file))
    view.import_button.invoke()
    pump(root, lambda: any(action == "submit" for action, _, _ in api.calls))
    call = next(data for action, data, _ in api.calls if action == "submit")
    assert call["request"]["inputs"] == [str((tmp_path / "structure.cif").resolve())]
    assert call["request"]["output_dir"] == str((tmp_path / "results").resolve())
    assert call["api_key"] == "runtime-key"
    assert "runtime-key" not in json.dumps(call["request"])


def test_verified_open_and_corruption_stays_out_of_results(task_window):
    root, view, api, lang, delivered = task_window
    api.jobs["old-run"]["state"] = "completed"
    view.refresh()
    pump(root, lambda: view._jobs["old-run"]["state"] == "completed")
    view.tree.selection_set("old-run")
    view._select()
    api.bad_integrity = True
    view.open_button.invoke()
    pump(root, lambda: "hash changed" in view.message.get())
    assert not delivered
    assert not any(action == "load" for action, _, _ in api.calls)
    api.bad_integrity = False
    view.open_button.invoke()
    pump(root, lambda: bool(delivered))
    assert delivered == [(api.result, threading.get_ident())]
    assert next(data for action, data, _ in api.calls if action == "verify")["verify"] is True


def test_verified_folder_never_opens_changed_result(task_window, monkeypatch, tmp_path):
    root, view, api, lang, delivered = task_window
    api.jobs["old-run"]["state"] = "completed"
    view.refresh()
    pump(root, lambda: view._jobs["old-run"]["state"] == "completed")
    view.tree.selection_set("old-run")
    view._select()
    opened = []
    monkeypatch.setattr(gui, "open_path", lambda path: opened.append(path))
    api.bad_integrity = True
    view.folder_button.invoke()
    pump(root, lambda: "hash changed" in view.message.get())
    assert not opened
    api.bad_integrity = False
    monkeypatch.setattr(api, "get_result", lambda *a, **kw: {"output_dir": str(tmp_path)})
    view.folder_button.invoke()
    pump(root, lambda: bool(opened))
    assert opened == [str(tmp_path)]


def test_workspace_switch_discards_old_monitor_messages_and_history_returns(task_window, tmp_path):
    root, view, api, lang, delivered = task_window
    old_generation = view._generation
    view.workspace.set(str(tmp_path / "another-workspace"))
    view.refresh()
    view._messages.put((old_generation, "submitted", {"run_id": "stale", "state": "running"}))
    pump(root, lambda: view._jobs.get("old-run") is not None)
    assert "stale" not in view._jobs
    # A newly constructed view loads saved history without submitting anything.
    restored = gui_tasks.TasksView(root, translate=lambda key, **fmt: t("en", key, **fmt),
                                  on_result=lambda _: None, api_key=lambda: "")
    restored.pack()
    pump(root, lambda: "old-run" in restored.tree.get_children())
    assert not any(action == "submit" for action, _, _ in api.calls)
    restored.destroy()


def test_preparation_uses_durable_job_without_saving_credentials(monkeypatch, tmp_path):
    api = FakeWorkflow()
    monkeypatch.setattr(gui_tasks, "workflow_api", lambda: api)
    submitted = api.submit_job

    def completed(request, **kwargs):
        job = submitted(request, **kwargs)
        job["state"] = "completed"
        return job

    monkeypatch.setattr(api, "submit_job", completed)
    result = gui_cifs._prepare_cifs(composition="Ti-Al-V", output_dir=tmp_path / "prepared",
                                    nominal="TC4", offline=True, phases=["alpha"],
                                    api_key="private-key", _workspace=tmp_path / "workspace")
    assert result is api.result
    data = next(data for action, data, _ in api.calls if action == "submit")
    assert data["request"]["workflow"] == "prepare"
    assert data["request"]["preparation"]["nominal"] == "TC4"
    assert data["workspace"] == tmp_path / "workspace"
    assert data["api_key"] == "private-key"
    assert "private-key" not in json.dumps(data["request"])


def test_mp_form_keeps_analysis_download_authorization_and_runtime_key(tmp_path):
    def variable(value):
        return SimpleNamespace(get=lambda: value)

    submitted = []
    controller = SimpleNamespace(
        running=False, mp_composition=variable("Ti-Al-V"), mp_key=variable("private-mp-key"),
        mp_output=variable(str(tmp_path / "results")), mp_conventional=variable(False),
        include_excel=variable(False), overwrite=variable(False),
        _form_analysis_settings=lambda: AnalysisSettings(input_mode="energy", energy_keV=83,
                                                        include_elasticity=False, include_patterns=False),
        _form_discovery_settings=lambda: DiscoverySettings(max_total=20),
        _t=lambda key, **fmt: t("en", key, **fmt),
        _submit_workflow=lambda request, **kwargs: submitted.append((request, kwargs)),
    )
    gui.DiffractScoutApp._run_mp(controller)
    request, runtime = submitted[0]
    parsed = WorkflowRequest.from_dict(request)
    assert parsed.workflow == "run"
    assert parsed.analysis["energy_keV"] == 83
    assert parsed.analysis["include_patterns"] is False
    assert parsed.analysis["include_elasticity"] is False
    assert parsed.execution["conventional_unit_cell"] is False
    assert parsed.execution["confirm_above"] == 20
    assert parsed.execution["authorize_large_download"] is True
    assert runtime == {"api_key": "private-mp-key"}
    assert "private-mp-key" not in json.dumps(parsed.to_dict())


def test_main_window_tasks_at_minimum_size_and_language_toggle(monkeypatch):
    api = FakeWorkflow()
    monkeypatch.setattr(gui_tasks, "workflow_api", lambda: api)
    app = make_app()
    closed = False
    try:
        # Map only this test window off screen; do not interact with other apps.
        app.geometry("900x640+20000+20000")
        app.notebook.select(app.tasks_view)
        app.update()
        assert app.winfo_width() == 900 and app.winfo_height() == 640
        view = app.tasks_view
        for language in ("en", "zh"):
            app._set_language(language)
            app.update()
            assert app.notebook.tab(view, "text") == t(language, "tab_tasks")
            assert view.open_button.cget("text") == t(language, "tasks_open")
            for button in (view.import_button, view.refresh_button, view.resume_button,
                           view.cancel_button, view.open_button, view.folder_button):
                assert button.winfo_ismapped()
                assert button.winfo_rootx() >= view.winfo_rootx()
                assert button.winfo_rootx() + button.winfo_width() <= view.winfo_rootx() + view.winfo_width()
            assert view.details.winfo_height() > 30
            assert view.tree.winfo_height() > 30
        app.running = True
        app._on_close()
        closed = True
        assert view._closed
    finally:
        if not closed:
            app.destroy()


def test_real_local_job_survives_close_and_reopens_verified_result(tmp_path):
    from pathlib import Path
    from diffractscout import workflow

    source = Path(gui.__file__).parent / "benchmark_data" / "bcc_fe.cif"
    workspace = tmp_path / "workspace"
    output = tmp_path / "results"
    app = make_app()
    closed = False
    try:
        app.withdraw()
        app.tasks_view.workspace.set(str(workspace))
        app._add_input_paths([source])
        app.local_output.set(str(output))
        app.energy_shortcut.set("83 keV")
        app.include_excel.set(False)
        app.include_patterns.set(False)
        app.elastic_overrides[str(source.resolve())] = gui.parse_cubic_cij(230, 135, 116, "GUI override")
        app._run_local()
        pump(app, lambda: bool(app.tasks_view._jobs), timeout=15)
        run_id = next(iter(app.tasks_view._jobs))
        at_close = workflow.status_job(run_id, workspace=workspace)
        assert at_close["state"] in gui_tasks.ACTIVE_STATES
        app._on_close()
        closed = True
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = workflow.status_job(run_id, workspace=workspace)
            if status["state"] not in gui_tasks.ACTIVE_STATES:
                break
            time.sleep(0.1)
        assert status["state"] == "completed", status
        result = workflow.load_result_object(run_id, workspace=workspace)
        assert result.output_dir == output
        assert len(result.analyses) == 1
        analysis = result.analyses[0]
        assert analysis.energy_keV == 83
        assert analysis.elastic_tensor.stiffness_GPa[0, 0] == 230
        assert analysis.elastic_tensor.source_record_id == "GUI override"
        assert not (output / "results.xlsx").exists()
        assert workflow.get_result(run_id, workspace=workspace)["integrity"] == "passed"
        # Restart the real task monitor against the same saved workspace.
        root = gui_tasks.tk.Tk()
        root.withdraw()
        loaded = []
        try:
            view = gui_tasks.TasksView(root, translate=lambda key, **fmt: t("en", key, **fmt),
                                      on_result=loaded.append, api_key=lambda: "")
            view.workspace.set(str(workspace))
            view.refresh()
            pump(root, lambda: run_id in view.tree.get_children())
            view.tree.selection_set(run_id)
            view._select()
            view.open_button.invoke()
            pump(root, lambda: bool(loaded))
            assert loaded[0].output_dir == output
        finally:
            root.destroy()
    finally:
        if not closed:
            app.destroy()
