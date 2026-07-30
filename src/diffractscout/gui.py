"""Small Tk desktop front end over the tested pipeline API."""

from __future__ import annotations

import os
import queue
import threading
import traceback

from .models import DiscoverySettings
from .pipeline import analyze_cifs, run_pipeline
from .providers.materials_project import MaterialsProjectProvider


def main() -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as exc:  # pragma: no cover - platform-dependent
        raise RuntimeError("Tkinter is unavailable in this Python installation.") from exc

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("DiffractScout")
            self.geometry("900x650")
            self.minsize(760, 520)
            self.events: queue.Queue[tuple[str, object]] = queue.Queue()

            heading = ttk.Label(
                self,
                text="DiffractScout — phase scouting to indexed diffraction references",
                font=("TkDefaultFont", 14, "bold"),
            )
            heading.pack(anchor="w", padx=14, pady=(12, 4))
            ttk.Label(
                self,
                text="Theoretical references with source hashes, explicit model boundaries, and optional hkl-normal elasticity.",
            ).pack(anchor="w", padx=14, pady=(0, 10))

            notebook = ttk.Notebook(self)
            notebook.pack(fill="both", expand=True, padx=12, pady=4)
            local = ttk.Frame(notebook, padding=12)
            mp = ttk.Frame(notebook, padding=12)
            notebook.add(local, text="Local CIF analysis")
            notebook.add(mp, text="Materials Project pipeline")
            self._build_local(local, filedialog)
            self._build_mp(mp, filedialog)

            self.log = tk.Text(self, height=10, wrap="word", state="disabled")
            self.log.pack(fill="both", padx=12, pady=(4, 12))
            self.after(150, self._poll)
            self._message("Ready. Existing source repositories and input directories are never modified.")

        @staticmethod
        def _path_row(parent: object, row: int, label: str, variable: object, chooser: object) -> None:
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8)
            ttk.Button(parent, text="Browse", command=chooser).grid(row=row, column=2)

        def _build_local(self, frame: object, filedialog_module: object) -> None:
            frame.columnconfigure(1, weight=1)
            self.local_input = tk.StringVar()
            self.local_output = tk.StringVar()
            self._path_row(
                frame,
                0,
                "CIF file/folder",
                self.local_input,
                lambda: self.local_input.set(filedialog_module.askdirectory() or self.local_input.get()),
            )
            self._path_row(
                frame,
                1,
                "New output folder",
                self.local_output,
                lambda: self.local_output.set(filedialog_module.askdirectory() or self.local_output.get()),
            )
            ttk.Label(
                frame,
                text="The output folder must be empty. CIF files and paired elasticity JSON are copied into the result bundle.",
                wraplength=720,
            ).grid(row=2, column=0, columnspan=3, sticky="w", pady=8)
            ttk.Button(frame, text="Analyze local CIFs", command=self._run_local).grid(
                row=3, column=0, columnspan=3, sticky="ew", pady=10
            )

        def _build_mp(self, frame: object, filedialog_module: object) -> None:
            frame.columnconfigure(1, weight=1)
            self.mp_composition = tk.StringVar(value="Ti-6Al-4V")
            self.mp_key = tk.StringVar(value=os.environ.get("MP_API_KEY", ""))
            self.mp_output = tk.StringVar()
            self.mp_limit = tk.StringVar(value="50")
            ttk.Label(frame, text="Alloy / chemical system / mp-IDs").grid(row=0, column=0, sticky="w", pady=5)
            ttk.Entry(frame, textvariable=self.mp_composition).grid(row=0, column=1, columnspan=2, sticky="ew", padx=8)
            ttk.Label(frame, text="Materials Project API key").grid(row=1, column=0, sticky="w", pady=5)
            ttk.Entry(frame, textvariable=self.mp_key, show="•").grid(row=1, column=1, columnspan=2, sticky="ew", padx=8)
            self._path_row(
                frame,
                2,
                "New output folder",
                self.mp_output,
                lambda: self.mp_output.set(filedialog_module.askdirectory() or self.mp_output.get()),
            )
            ttk.Label(frame, text="Maximum candidates").grid(row=3, column=0, sticky="w", pady=5)
            ttk.Entry(frame, textvariable=self.mp_limit, width=12).grid(row=3, column=1, sticky="w", padx=8)
            ttk.Label(
                frame,
                text=(
                    "The API key is used in memory and is not written to the bundle. The button authorizes downloads "
                    "up to the stated maximum. Materials Project Cij is labeled as DFT-derived."
                ),
                wraplength=720,
            ).grid(row=4, column=0, columnspan=3, sticky="w", pady=8)
            ttk.Button(frame, text="Run complete pipeline", command=self._run_mp).grid(
                row=5, column=0, columnspan=3, sticky="ew", pady=10
            )

        def _start(self, function: object) -> None:
            thread = threading.Thread(target=self._worker, args=(function,), daemon=True)
            thread.start()

        def _worker(self, function: object) -> None:
            try:
                result = function()
                self.events.put(("done", result))
            except Exception as exc:  # pragma: no cover - UI path
                self.events.put(("error", (exc, traceback.format_exc())))

        def _run_local(self) -> None:
            source = self.local_input.get().strip()
            output = self.local_output.get().strip()
            if not source or not output:
                messagebox.showerror("Missing input", "Choose an input and a new output folder.")
                return
            self._message("Starting local analysis…")
            self._start(lambda: analyze_cifs([source], output))

        def _run_mp(self) -> None:
            composition = self.mp_composition.get().strip()
            api_key = self.mp_key.get().strip()
            output = self.mp_output.get().strip()
            try:
                limit = int(self.mp_limit.get())
            except ValueError:
                messagebox.showerror("Invalid maximum", "Maximum candidates must be an integer.")
                return
            if not composition or not api_key or not output:
                messagebox.showerror("Missing input", "Composition, API key, and output folder are required.")
                return
            self._message("Starting Materials Project discovery and download…")

            def run() -> object:
                provider = MaterialsProjectProvider(api_key)
                return run_pipeline(
                    composition,
                    provider,
                    output,
                    discovery_settings=DiscoverySettings(max_total=limit),
                    confirm_above=limit,
                    authorize_large_download=True,
                )

            self._start(run)

        def _message(self, text: str) -> None:
            self.log.configure(state="normal")
            self.log.insert("end", text.rstrip() + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")

        def _poll(self) -> None:
            while True:
                try:
                    kind, payload = self.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "done":
                    self._message(f"Completed: {payload.output_dir}")
                    self._message(f"Manifest: {payload.manifest_path}")
                    if payload.warnings:
                        for warning in payload.warnings:
                            self._message(f"WARNING: {warning}")
                    messagebox.showinfo("DiffractScout", f"Completed\n{payload.output_dir}")
                else:
                    exc, details = payload
                    self._message(f"ERROR: {exc}\n{details}")
                    messagebox.showerror("DiffractScout", str(exc))
            self.after(150, self._poll)

    App().mainloop()


if __name__ == "__main__":
    main()
