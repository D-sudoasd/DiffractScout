"""Tk task history backed by the shared durable workflow service."""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any, Callable

try:
    import tkinter as tk
    from tkinter import filedialog, ttk
except ImportError:  # pragma: no cover - optional Tk
    tk = ttk = filedialog = None


def workflow_api() -> Any:
    # Loading the desktop does not require starting the workflow service.
    from . import workflow

    return workflow


ACTIVE_STATES = {"pending", "running", "cancelling"}
RESUMABLE_STATES = {"interrupted", "blocked", "partial", "failed", "cancelled"}


if ttk is not None:
    class TasksView(ttk.Frame):
        """Only queue messages cross threads; Tk updates stay in the event loop."""

        def __init__(self, master: Any, *, translate: Callable[..., str],
                     on_result: Callable[[Any], None], api_key: Callable[[], str],
                     help_view: Any = None) -> None:
            super().__init__(master, padding=8)
            self._t = translate
            self._on_result = on_result
            self._api_key = api_key
            self._messages: queue.Queue = queue.Queue()
            self._closed = False
            self._refreshing = False
            self._generation = 0
            self._workspace_identity: Path | None = None
            self._jobs: dict[str, dict] = {}
            self._follow: set[str] = set()
            self._opening: set[str] = set()
            self._summaries: dict[str, dict] = {}
            self._events: dict[str, dict] = {}
            self._event_cursors: dict[str, int] = {}
            self._targets: list[tuple[Any, str]] = []
            self.workspace = tk.StringVar(value=str(Path.cwd() / "outputs" / "agent-workspace"))
            self.message = tk.StringVar()
            self.columnconfigure(0, weight=1)
            self.rowconfigure(2, weight=1)
            location = ttk.Frame(self)
            location.grid(row=0, column=0, sticky="ew")
            location.columnconfigure(1, weight=1)
            label = ttk.Label(location)
            label.grid(row=0, column=0, padx=(0, 6))
            self._targets.append((label, "tasks_workspace"))
            self.workspace_entry = ttk.Entry(location, textvariable=self.workspace)
            self.workspace_entry.grid(row=0, column=1, sticky="ew")
            self.workspace_entry.bind("<Return>", lambda _e: self.refresh())
            self.browse_button = self._button(location, "tasks_choose", self.choose_workspace)
            self.browse_button.grid(row=0, column=2, padx=(6, 0))
            actions = ttk.Frame(self)
            actions.grid(row=1, column=0, sticky="ew", pady=6)
            self.import_button = self._button(actions, "tasks_import", self.import_request)
            self.refresh_button = self._button(actions, "tasks_refresh", self.refresh)
            self.resume_button = self._button(actions, "tasks_resume", self.resume)
            self.cancel_button = self._button(actions, "tasks_cancel", self.cancel)
            self.open_button = self._button(actions, "tasks_open", self.open_selected)
            self.folder_button = self._button(actions, "tasks_folder", self.open_folder)
            for widget in (self.import_button, self.refresh_button, self.resume_button,
                           self.cancel_button, self.open_button, self.folder_button):
                widget.pack(side="left", padx=(0, 5))
            split = ttk.Panedwindow(self, orient="vertical")
            split.grid(row=2, column=0, sticky="nsew")
            table = ttk.Frame(split)
            table.columnconfigure(0, weight=1)
            table.rowconfigure(0, weight=1)
            self.tree = ttk.Treeview(table, columns=("name", "state", "stage", "counts"),
                                     show="headings", height=4, selectmode="browse")
            for key, width in (("name", 260), ("state", 100), ("stage", 150), ("counts", 95)):
                self.tree.column(key, width=width, minwidth=60, stretch=True)
            self.tree.grid(row=0, column=0, sticky="nsew")
            scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
            scroll.grid(row=0, column=1, sticky="ns")
            self.tree.configure(yscrollcommand=scroll.set)
            self.tree.bind("<<TreeviewSelect>>", self._select)
            self.tree.bind("<Double-1>", lambda _e: self.open_selected())
            split.add(table, weight=2)
            details_host = ttk.Frame(split)
            details_host.columnconfigure(0, weight=1)
            details_host.rowconfigure(0, weight=1)
            self.details = tk.Text(details_host, height=4, wrap="word", state="disabled")
            self.details.grid(row=0, column=0, sticky="nsew")
            details_scroll = ttk.Scrollbar(details_host, command=self.details.yview)
            details_scroll.grid(row=0, column=1, sticky="ns")
            self.details.configure(yscrollcommand=details_scroll.set)
            split.add(details_host, weight=1)
            self.hint = ttk.Label(self, textvariable=self.message, wraplength=760)
            self.hint.grid(row=3, column=0, sticky="ew", pady=(5, 0))
            self.bind("<Configure>", lambda e: self.hint.configure(wraplength=max(180, e.width - 20)))
            self.bind("<Destroy>", self._destroyed, add="+")
            if help_view is not None:
                for widget, key in ((self.workspace_entry, "help_tasks_workspace"),
                                    (self.browse_button, "help_tasks_workspace"),
                                    (self.import_button, "help_tasks_import"),
                                    (self.refresh_button, "help_tasks_refresh"),
                                    (self.resume_button, "help_tasks_resume"),
                                    (self.cancel_button, "help_tasks_cancel"),
                                    (self.open_button, "help_tasks_open"),
                                    (self.folder_button, "help_tasks_folder"),
                                    (self.tree, "help_tasks_list"),
                                    (self.details, "help_tasks_details")):
                    help_view.add(widget, lambda k=key: self._t(k))
                help_view.add_tree(self.tree, lambda: self._t("help_tasks_list"), {
                    "name": lambda: self._t("help_tasks_list"),
                    "state": lambda: self._t("help_tasks_list"),
                    "stage": lambda: self._t("help_tasks_list"),
                    "counts": lambda: self._t("help_tasks_refresh"),
                })
            self.refresh_language()
            self._after_id = self.after(100, self._poll)
            self.refresh()

        def _button(self, parent: Any, key: str, command: Callable) -> Any:
            button = ttk.Button(parent, command=command)
            self._targets.append((button, key))
            return button

        def _background(self, kind: str, function: Callable) -> None:
            messages, generation = self._messages, self._generation

            def work() -> None:
                try:
                    messages.put((generation, kind, function()))
                except Exception as exc:
                    messages.put((generation, "error", str(exc)))

            threading.Thread(target=work, daemon=True, name="workflow-desktop-monitor").start()

        def workspace_path(self) -> Path:
            path = Path(self.workspace.get()).expanduser().absolute()
            if path != self._workspace_identity:
                self._workspace_identity = path
                self._generation += 1
                self._refreshing = False
                self._follow.clear()
                self._opening.clear()
                self._summaries.clear()
                self._events.clear()
                self._event_cursors.clear()
                self._jobs.clear()
            return path

        def choose_workspace(self) -> None:
            value = filedialog.askdirectory(parent=self, title=self._t("tasks_workspace"))
            if value:
                self.workspace.set(value)
                self.refresh()

        def submit(self, request: dict, *, api_key: str | None = None) -> None:
            workspace = self.workspace_path()
            self.message.set(self._t("tasks_submitting"))

            def work() -> dict:
                api = workflow_api()
                parsed = api.WorkflowRequest.from_dict(request)
                return api.submit_job(parsed, workspace=workspace, api_key=api_key)

            self._background("submitted", work)

        def import_request(self) -> None:
            name = filedialog.askopenfilename(parent=self, filetypes=(("JSON", "*.json"),))
            if not name:
                return
            workspace, api_key = self.workspace_path(), self._api_key() or None

            def work() -> dict:
                path = Path(name)
                api = workflow_api()
                request = api.WorkflowRequest.from_dict(json.loads(path.read_text(encoding="utf-8-sig")),
                                                        base_dir=path.parent)
                return api.submit_job(request, workspace=workspace, api_key=api_key)

            self._background("submitted", work)

        def refresh(self) -> None:
            workspace = self.workspace_path()
            if self._refreshing or self._closed:
                return
            self._refreshing = True
            self._background("jobs", lambda: workflow_api().list_jobs(workspace=workspace))

        def selected(self) -> str | None:
            return next(iter(self.tree.selection()), None)

        def resume(self) -> None:
            run_id = self.selected()
            if run_id:
                workspace, api_key = self.workspace_path(), self._api_key() or None
                self._background("submitted", lambda: workflow_api().resume_job(
                    run_id, workspace=workspace, background=True, api_key=api_key))

        def cancel(self) -> None:
            run_id = self.selected()
            if run_id:
                workspace = self.workspace_path()
                self._background("cancelled", lambda: workflow_api().cancel_job(run_id, workspace=workspace))

        def open_selected(self) -> None:
            run_id = self.selected()
            if run_id:
                self._open(run_id)

        def open_folder(self) -> None:
            run_id = self.selected()
            if run_id:
                workspace = self.workspace_path()
                self._background("folder", lambda: workflow_api().get_result(
                    run_id, workspace=workspace, verify=True))

        def _open(self, run_id: str) -> None:
            if run_id in self._opening:
                return
            self._opening.add(run_id)
            workspace = self.workspace_path()

            def work() -> tuple:
                api = workflow_api()
                # Verify even when a workflow produces tables rather than a PipelineResult.
                summary = api.get_result(run_id, workspace=workspace, verify=True)
                job = api.status_job(run_id, workspace=workspace)
                result = (api.load_result_object(run_id, workspace=workspace)
                          if job.get("workflow") not in {"fetch", "adapt"} else None)
                return run_id, result, summary

            self._background("result", work)

        def _select(self, _event: Any = None) -> None:
            run_id = self.selected()
            job = self._jobs.get(run_id or "", {})
            state = job.get("state")
            self.resume_button.configure(state="normal" if state in RESUMABLE_STATES else "disabled")
            self.cancel_button.configure(state="normal" if state in ACTIVE_STATES else "disabled")
            self.open_button.configure(state="normal" if state in {"completed", "partial"} else "disabled")
            self.folder_button.configure(state="normal" if state in {"completed", "partial"} else "disabled")
            self.details.configure(state="normal")
            self.details.delete("1.0", "end")
            if job:
                lines = [f"{job.get('name') or run_id}  [{run_id}]",
                         f"{self._t('tasks_state')}: {self._t('task_state_' + str(state))}   "
                         f"{self._t('tasks_stage')}: {self._stage_text(job.get('stage', ''))}"]
                for diagnostic in job.get("diagnostics", []):
                    fields = diagnostic.get("missing_fields") or []
                    lines.append(f"{diagnostic.get('code', '')}: {diagnostic.get('message', '')}")
                    if fields:
                        lines.append(f"{self._t('tasks_missing')}: {', '.join(fields)}")
                for key in ("output_dir", "integrity", "coverage", "counters", "elapsed_seconds"):
                    if key in job:
                        value = job[key]
                        if isinstance(value, (dict, list)):
                            value = json.dumps(value, ensure_ascii=False)
                        lines.append(f"{self._t('tasks_' + key)}: {value}")
                summary = self._summaries.get(run_id, {})
                for artifact in summary.get("artifacts", job.get("artifacts", [])):
                    lines.append(f"{artifact.get('kind', '')}: {artifact.get('path', '')}")
                if summary.get("tables"):
                    lines.append(f"{self._t('tasks_tables')}: {', '.join(summary['tables'])}")
                for event in self._events.get(run_id, {}).get("events", []):
                    lines.append(" | ".join(str(event[key]) for key in
                                          ("time", "event", "stage", "item", "message") if key in event))
                self.details.insert("1.0", "\n".join(lines))
            self.details.configure(state="disabled")

        def _stage_text(self, stage: str) -> str:
            key = "task_stage_" + stage
            text = self._t(key)
            return stage if text == key else text

        def _read_events(self, run_id: str) -> None:
            workspace = self.workspace_path()
            cursor = self._event_cursors.get(run_id, 0)
            self._background("events", lambda: (run_id, workflow_api().read_events(
                run_id, workspace=workspace, after=cursor, limit=100)))

        def _render(self) -> None:
            selection = self.selected()
            present = set(self.tree.get_children())
            for run_id, job in self._jobs.items():
                state = str(job.get("state", ""))
                counts = f"{job.get('completed_items', 0)} / {job.get('total_items', '—')}"
                values = (job.get("name") or run_id, self._t("task_state_" + state),
                          self._stage_text(job.get("stage", "")), counts)
                if run_id in present:
                    self.tree.item(run_id, values=values)
                    present.remove(run_id)
                else:
                    self.tree.insert("", "end", iid=run_id, values=values)
            for run_id in present:
                self.tree.delete(run_id)
            if selection in self._jobs:
                self.tree.selection_set(selection)
            self._select()

        def refresh_language(self) -> None:
            for widget, key in self._targets:
                widget.configure(text=self._t(key))
            for column in ("name", "state", "stage", "counts"):
                self.tree.heading(column, text=self._t("tasks_" + column))
            self.message.set(self._t("tasks_hint"))
            self._render()

        def _poll(self) -> None:
            if self._closed:
                return
            while True:
                try:
                    generation, kind, payload = self._messages.get_nowait()
                except queue.Empty:
                    break
                if generation != self._generation:
                    continue
                if kind == "error":
                    self._refreshing = False
                    self._opening.clear()
                    self.message.set(self._t("tasks_error", error=payload))
                elif kind == "jobs":
                    self._refreshing = False
                    self._jobs = {job["run_id"]: job for job in payload}
                    self._render()
                    if self.selected():
                        self._read_events(self.selected())
                    for run_id in self._follow.copy():
                        state = self._jobs.get(run_id, {}).get("state")
                        if state in {"completed", "partial"}:
                            self._follow.discard(run_id)
                            self._open(run_id)
                        elif state and state not in ACTIVE_STATES:
                            self._follow.discard(run_id)
                elif kind in {"submitted", "cancelled"}:
                    run_id = payload["run_id"]
                    self._jobs[run_id] = payload
                    if kind == "submitted":
                        self._follow.add(run_id)
                    self._render()
                    self.tree.selection_set(run_id)
                    self.tree.see(run_id)
                    self._select()
                    self.message.set(self._t("tasks_saved", run_id=run_id))
                elif kind == "result":
                    run_id, result, summary = payload
                    self._opening.discard(run_id)
                    self._summaries[run_id] = summary
                    self.message.set(self._t("tasks_verified", run_id=run_id))
                    if result is not None:
                        self._on_result(result)
                    else:
                        self._select()
                elif kind == "folder":
                    from .gui import open_path

                    try:
                        open_path(payload["output_dir"])
                    except OSError as exc:
                        self.message.set(self._t("tasks_error", error=exc))
                elif kind == "events":
                    run_id, events = payload
                    self._event_cursors[run_id] = events.get("next_cursor", 0)
                    previous = self._events.get(run_id, {}).get("events", [])
                    self._events[run_id] = {"events": (previous + events.get("events", []))[-100:]}
                    if run_id == self.selected():
                        self._select()
            self.refresh()
            self._after_id = self.after(1000, self._poll)

        def _destroyed(self, event: Any) -> None:
            if event.widget is self:
                self._closed = True
                self.after_cancel(self._after_id)
