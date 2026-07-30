"""Responsive Tk desktop interface for the tested DiffractScout pipeline API."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import __version__
from .models import AnalysisSettings, DiscoverySettings, PipelineResult
from .pipeline import analyze_cifs, run_pipeline
from .providers.materials_project import MaterialsProjectProvider

try:  # Tk remains optional on minimal/headless Python installations.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - platform-dependent
    tk = None  # type: ignore[assignment]
    filedialog = messagebox = ttk = None  # type: ignore[assignment]

NAVY = "#102A43"
NAVY_DARK = "#0B1F33"
TEAL = "#00A6A6"
TEAL_DARK = "#087F8C"
BLUE = "#277DA1"
BG = "#F3F6F9"
CARD = "#FFFFFF"
TEXT = "#203040"
MUTED = "#61758A"
BORDER = "#D7E0E8"
SUCCESS = "#14804A"
WARNING = "#A35A00"
ERROR = "#B42318"
LOG_BG = "#0D1B2A"
LOG_TEXT = "#DCE7F1"


def _required_float(value: object, field: str) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number.") from exc
    return parsed


def _required_int(value: object, field: str) -> int:
    text = str(value).strip()
    try:
        parsed = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc
    return parsed


def _optional_float(value: object, field: str) -> float | None:
    text = str(value or "").strip()
    return None if not text else _required_float(text, field)


def _optional_int(value: object, field: str) -> int | None:
    text = str(value or "").strip()
    return None if not text else _required_int(text, field)


def analysis_settings_from_form(values: Mapping[str, object]) -> AnalysisSettings:
    mode = str(values.get("input_mode", "source")).strip().lower()
    if mode not in {"source", "wavelength", "energy"}:
        raise ValueError("Radiation mode must be source, wavelength, or energy.")
    radiation = _optional_float(values.get("radiation_value"), "Radiation value")
    return AnalysisSettings(
        input_mode=mode,  # type: ignore[arg-type]
        source_preset=str(values.get("source_preset", "Cu Ka")),
        wavelength_A=radiation if mode == "wavelength" or (mode == "source" and str(values.get("source_preset")) == "Custom") else None,
        energy_keV=radiation if mode == "energy" else None,
        two_theta_min_deg=_required_float(values.get("two_theta_min", 5), "2θ minimum"),
        two_theta_max_deg=_required_float(values.get("two_theta_max", 120), "2θ maximum"),
        step_deg=_required_float(values.get("step", 0.02), "Profile step"),
        fwhm_deg=_required_float(values.get("fwhm", 0.15), "FWHM"),
        profile_eta=_required_float(values.get("eta", 0.5), "Pseudo-Voigt η"),
        include_elasticity=bool(values.get("include_elasticity", True)),
        max_profile_points=_required_int(values.get("max_profile_points", 1_000_000), "Maximum profile points"),
        max_reflection_estimate=_required_int(
            values.get("max_reflection_estimate", 2_000_000),
            "Maximum reciprocal candidates",
        ),
    )


def discovery_settings_from_form(values: Mapping[str, object]) -> DiscoverySettings:
    mode = str(values.get("mode", "possible_phases")).strip()
    if mode not in {"possible_phases", "near_stable", "single_chemsys", "mpids_only"}:
        raise ValueError("Unknown discovery mode.")
    return DiscoverySettings(
        mode=mode,  # type: ignore[arg-type]
        e_hull_max_eV_atom=_optional_float(values.get("e_hull_max"), "Maximum energy above hull"),
        max_subsystem_order=_optional_int(values.get("max_subsystem_order"), "Maximum subsystem order"),
        max_per_subsystem=_optional_int(values.get("max_per_subsystem"), "Maximum per subsystem"),
        max_total=_optional_int(values.get("max_total"), "Maximum candidates"),
        exclude_deprecated=not bool(values.get("include_deprecated", False)),
    )


def open_path(path: str | Path) -> None:
    """Open a directory with the platform file manager without invoking a shell."""

    target = str(Path(path).expanduser().resolve())
    if sys.platform.startswith("win"):
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


if tk is not None:

    class DiffractScoutApp(tk.Tk):
        """Desktop controller; all scientific work is delegated to tested pipeline functions."""

        def __init__(self) -> None:
            super().__init__()
            self.title(f"DiffractScout {__version__}")
            self.geometry("1180x900")
            self.minsize(980, 760)
            self.configure(background=BG)
            self.protocol("WM_DELETE_WINDOW", self._on_close)

            self.events: queue.Queue[tuple[str, object]] = queue.Queue()
            self.running = False
            self.last_output: Path | None = None
            self.local_inputs: list[Path] = []
            self._run_buttons: list[ttk.Button] = []
            self._radiation_source_widgets: list[ttk.Combobox] = []
            self._radiation_value_widgets: list[ttk.Entry] = []

            self._configure_style()
            self._create_variables()
            self._build_header()
            self._build_status_bar()
            self._build_activity_panel()
            self._build_body()
            self._sync_radiation_controls()
            self.after(120, self._poll)
            self._log(
                "Ready. Source CIFs and the PhaseScout/CIF2Peaks repositories are read-only inputs.",
                "info",
            )

        def _configure_style(self) -> None:
            style = ttk.Style(self)
            style.theme_use("clam")
            style.configure("TFrame", background=BG)
            style.configure("Card.TFrame", background=CARD, relief="flat")
            style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 9))
            style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 9))
            style.configure("Title.TLabel", background=CARD, foreground=NAVY, font=("Segoe UI Semibold", 12))
            style.configure("Hint.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 8))
            style.configure("Header.TLabel", background=NAVY_DARK, foreground="white")
            style.configure("HeaderTitle.TLabel", background=NAVY_DARK, foreground="white", font=("Segoe UI Semibold", 22))
            style.configure("HeaderSub.TLabel", background=NAVY_DARK, foreground="#BFD3E5", font=("Segoe UI", 10))
            style.configure("Badge.TLabel", background=TEAL, foreground="white", font=("Segoe UI Semibold", 9), padding=(9, 4))
            style.configure("TNotebook", background=BG, borderwidth=0)
            style.configure("TNotebook.Tab", background="#DCE6EE", foreground=NAVY, padding=(18, 9), font=("Segoe UI Semibold", 9))
            style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", TEAL_DARK)])
            style.configure("Primary.TButton", background=TEAL_DARK, foreground="white", padding=(14, 9), font=("Segoe UI Semibold", 10), borderwidth=0)
            style.map("Primary.TButton", background=[("active", TEAL), ("disabled", "#9FB3C3")])
            style.configure("Secondary.TButton", background="#E6EEF4", foreground=NAVY, padding=(10, 7), borderwidth=0)
            style.map("Secondary.TButton", background=[("active", "#D4E3ED")])
            style.configure("Danger.TButton", background="#FDE8E7", foreground=ERROR, padding=(10, 7), borderwidth=0)
            style.configure("TEntry", fieldbackground="white", foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=6)
            style.configure("TCombobox", fieldbackground="white", foreground=TEXT, padding=5)
            style.configure("TLabelframe", background=CARD, bordercolor=BORDER, relief="solid")
            style.configure("TLabelframe.Label", background=CARD, foreground=NAVY, font=("Segoe UI Semibold", 10))
            style.configure("TCheckbutton", background=CARD, foreground=TEXT)
            style.configure("Horizontal.TProgressbar", background=TEAL, troughcolor="#DCE6EE", borderwidth=0)

        def _create_variables(self) -> None:
            self.local_output = tk.StringVar()
            self.local_recursive = tk.BooleanVar(value=True)
            self.include_excel = tk.BooleanVar(value=True)
            self.include_elasticity = tk.BooleanVar(value=True)
            self.overwrite = tk.BooleanVar(value=False)

            self.input_mode = tk.StringVar(value="source")
            self.source_preset = tk.StringVar(value="Cu Ka")
            self.radiation_value = tk.StringVar(value="1.5406")
            self.two_theta_min = tk.StringVar(value="5")
            self.two_theta_max = tk.StringVar(value="120")
            self.step = tk.StringVar(value="0.02")
            self.fwhm = tk.StringVar(value="0.15")
            self.eta = tk.StringVar(value="0.5")
            self.max_profile_points = tk.StringVar(value="1000000")
            self.max_reflection_estimate = tk.StringVar(value="2000000")
            self.input_mode.trace_add("write", lambda *_args: self._sync_radiation_controls())
            self.source_preset.trace_add("write", lambda *_args: self._sync_radiation_controls())

            self.mp_composition = tk.StringVar(value="Ti-6Al-4V")
            self.mp_key = tk.StringVar(value=os.environ.get("MP_API_KEY", ""))
            self.mp_show_key = tk.BooleanVar(value=False)
            self.mp_output = tk.StringVar()
            self.mp_mode = tk.StringVar(value="possible_phases")
            self.mp_e_hull = tk.StringVar()
            self.mp_subsystem_order = tk.StringVar()
            self.mp_per_subsystem = tk.StringVar()
            self.mp_limit = tk.StringVar(value="50")
            self.mp_include_deprecated = tk.BooleanVar(value=False)
            self.mp_conventional = tk.BooleanVar(value=True)

            self.status_text = tk.StringVar(value="Ready")
            self.input_count_text = tk.StringVar(value="No CIF inputs selected")

        def _build_header(self) -> None:
            header = tk.Frame(self, bg=NAVY_DARK, height=102)
            header.pack(fill="x")
            header.pack_propagate(False)
            logo = tk.Canvas(header, width=70, height=70, bg=NAVY_DARK, highlightthickness=0)
            logo.pack(side="left", padx=(24, 10), pady=15)
            logo.create_oval(8, 8, 62, 62, outline=TEAL, width=3)
            for x, y in ((21, 24), (48, 22), (28, 48), (50, 47)):
                logo.create_oval(x - 4, y - 4, x + 4, y + 4, fill="white", outline="")
            logo.create_line(21, 24, 48, 22, 50, 47, 28, 48, 21, 24, fill="#8BC6D5", width=2)

            text = tk.Frame(header, bg=NAVY_DARK)
            text.pack(side="left", fill="y", pady=15)
            ttk.Label(text, text="DiffractScout", style="HeaderTitle.TLabel").pack(anchor="w")
            ttk.Label(
                text,
                text="Candidate phases → validated CIFs → indexed powder diffraction → optional hkl elasticity",
                style="HeaderSub.TLabel",
            ).pack(anchor="w", pady=(3, 0))
            ttk.Label(header, text=f"v{__version__}", style="Badge.TLabel").pack(side="right", padx=24)

        def _build_body(self) -> None:
            body = ttk.Frame(self, padding=(18, 14, 18, 4))
            body.pack(fill="both", expand=True)
            notebook = ttk.Notebook(body)
            self.notebook = notebook
            notebook.pack(fill="both", expand=True)
            local = ttk.Frame(notebook, style="Card.TFrame", padding=16)
            mp = ttk.Frame(notebook, style="Card.TFrame", padding=16)
            notebook.add(local, text="  Local CIF analysis  ")
            notebook.add(mp, text="  Materials Project pipeline  ")
            self._build_local_tab(local)
            self._build_mp_tab(mp)

        def _card_title(self, parent: Any, title: str, hint: str) -> None:
            ttk.Label(parent, text=title, style="Title.TLabel").pack(anchor="w")
            ttk.Label(parent, text=hint, style="Hint.TLabel", wraplength=480).pack(anchor="w", pady=(2, 10))

        def _build_local_tab(self, frame: ttk.Frame) -> None:
            frame.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=1)
            frame.rowconfigure(0, weight=1)

            left = ttk.Frame(frame, style="Card.TFrame", padding=(0, 0, 12, 0))
            right = ttk.Frame(frame, style="Card.TFrame", padding=(12, 0, 0, 0))
            left.grid(row=0, column=0, sticky="nsew")
            right.grid(row=0, column=1, sticky="nsew")
            self._card_title(left, "1. Select structures", "Add individual CIF files or scan one or more folders. Duplicate paths are removed.")

            list_frame = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
            list_frame.pack(fill="both", expand=True)
            self.input_list = tk.Listbox(
                list_frame,
                selectmode="extended",
                bg="white",
                fg=TEXT,
                selectbackground="#D7EEF0",
                selectforeground=NAVY,
                relief="flat",
                highlightthickness=0,
                font=("Segoe UI", 9),
            )
            scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.input_list.yview)
            self.input_list.configure(yscrollcommand=scrollbar.set)
            self.input_list.pack(side="left", fill="both", expand=True, padx=8, pady=8)
            scrollbar.pack(side="right", fill="y")
            ttk.Label(left, textvariable=self.input_count_text, style="Hint.TLabel").pack(anchor="w", pady=(5, 4))

            buttons = ttk.Frame(left, style="Card.TFrame")
            buttons.pack(fill="x", pady=(0, 12))
            ttk.Button(buttons, text="Add CIF files", style="Secondary.TButton", command=self._add_cif_files).pack(side="left", padx=(0, 6))
            ttk.Button(buttons, text="Add folder", style="Secondary.TButton", command=self._add_cif_folder).pack(side="left", padx=6)
            ttk.Button(buttons, text="Remove", style="Danger.TButton", command=self._remove_inputs).pack(side="left", padx=6)
            ttk.Button(buttons, text="Clear", style="Secondary.TButton", command=self._clear_inputs).pack(side="left", padx=6)

            output_box = ttk.LabelFrame(left, text="Result bundle", padding=10)
            output_box.pack(fill="x")
            self._path_entry(output_box, self.local_output, self._choose_local_output)
            ttk.Checkbutton(output_box, text="Scan selected folders recursively", variable=self.local_recursive).pack(anchor="w", pady=(8, 0))
            ttk.Checkbutton(output_box, text="Replace an existing verified DiffractScout bundle", variable=self.overwrite).pack(anchor="w", pady=(4, 0))

            self._card_title(right, "2. Scientific controls", "Theoretical kinematic powder reference. Limits prevent accidental memory-intensive grids.")
            self._analysis_controls(right)
            options = ttk.LabelFrame(right, text="Outputs", padding=10)
            options.pack(fill="x", pady=(10, 0))
            ttk.Checkbutton(options, text="Pair numerical elasticity sidecars", variable=self.include_elasticity).pack(side="left", padx=(0, 14))
            ttk.Checkbutton(options, text="Write Excel workbook", variable=self.include_excel).pack(side="left")
            button = ttk.Button(right, text="Analyze selected CIFs", style="Primary.TButton", command=self._run_local)
            button.pack(fill="x", pady=(14, 0))
            self._run_buttons.append(button)

        def _build_mp_tab(self, frame: ttk.Frame) -> None:
            frame.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=1)
            frame.rowconfigure(0, weight=1)
            left = ttk.Frame(frame, style="Card.TFrame", padding=(0, 0, 12, 0))
            right = ttk.Frame(frame, style="Card.TFrame", padding=(12, 0, 0, 0))
            left.grid(row=0, column=0, sticky="nsew")
            right.grid(row=0, column=1, sticky="nsew")

            self._card_title(left, "1. Discover candidate phases", "Enter an alloy grade, formula, chemical system, or explicit mp-IDs.")
            form = ttk.LabelFrame(left, text="Materials Project query", padding=12)
            form.pack(fill="x")
            ttk.Label(form, text="Composition", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=5)
            ttk.Entry(form, textvariable=self.mp_composition).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=5)
            ttk.Label(form, text="API key", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=5)
            self.mp_key_entry = ttk.Entry(form, textvariable=self.mp_key, show="" if self.mp_show_key.get() else "•")
            self.mp_key_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=5)
            ttk.Checkbutton(form, text="Show", variable=self.mp_show_key, command=self._toggle_key).grid(row=1, column=3, sticky="w")
            ttk.Label(form, text="Mode", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=5)
            ttk.Combobox(
                form,
                textvariable=self.mp_mode,
                values=("possible_phases", "near_stable", "single_chemsys", "mpids_only"),
                state="readonly",
            ).grid(row=2, column=1, sticky="ew", padx=(8, 12), pady=5)
            ttk.Label(form, text="Eₕᵤₗₗ max", style="Card.TLabel").grid(row=2, column=2, sticky="w", pady=5)
            ttk.Entry(form, textvariable=self.mp_e_hull).grid(row=2, column=3, sticky="ew", padx=(8, 0), pady=5)
            ttk.Label(form, text="Subsystem order", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=5)
            ttk.Entry(form, textvariable=self.mp_subsystem_order).grid(row=3, column=1, sticky="ew", padx=(8, 12), pady=5)
            ttk.Label(form, text="Per subsystem", style="Card.TLabel").grid(row=3, column=2, sticky="w", pady=5)
            ttk.Entry(form, textvariable=self.mp_per_subsystem).grid(row=3, column=3, sticky="ew", padx=(8, 0), pady=5)
            ttk.Label(form, text="Maximum candidates", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=5)
            ttk.Entry(form, textvariable=self.mp_limit).grid(row=4, column=1, sticky="ew", padx=(8, 12), pady=5)
            ttk.Checkbutton(form, text="Include deprecated", variable=self.mp_include_deprecated).grid(row=4, column=2, columnspan=2, sticky="w", pady=4)
            form.columnconfigure(1, weight=1)
            form.columnconfigure(3, weight=1)

            output_box = ttk.LabelFrame(left, text="Result bundle", padding=10)
            output_box.pack(fill="x", pady=(12, 0))
            self._path_entry(output_box, self.mp_output, self._choose_mp_output)
            ttk.Checkbutton(output_box, text="Download conventional standard cells", variable=self.mp_conventional).pack(anchor="w", pady=(8, 0))
            ttk.Checkbutton(output_box, text="Replace an existing verified DiffractScout bundle", variable=self.overwrite).pack(anchor="w", pady=(4, 0))
            ttk.Label(
                left,
                text="The key remains in memory. Downloaded structures and Cij records retain provider URLs, identifiers, database metadata, and hashes.",
                style="Hint.TLabel",
                wraplength=480,
            ).pack(anchor="w", pady=(10, 0))

            self._card_title(right, "2. Analyze downloaded structures", "Shared controls match the local workflow; DFT elastic tensors are labeled and frame-checked.")
            self._analysis_controls(right)
            options = ttk.LabelFrame(right, text="Outputs", padding=10)
            options.pack(fill="x", pady=(10, 0))
            ttk.Checkbutton(options, text="Evaluate frame-compatible elasticity", variable=self.include_elasticity).pack(side="left", padx=(0, 14))
            ttk.Checkbutton(options, text="Write Excel workbook", variable=self.include_excel).pack(side="left")
            button = ttk.Button(right, text="Run discovery → diffraction pipeline", style="Primary.TButton", command=self._run_mp)
            button.pack(fill="x", pady=(14, 0))
            self._run_buttons.append(button)

        def _analysis_controls(self, parent: ttk.Frame) -> None:
            box = ttk.LabelFrame(parent, text="Radiation and profile", padding=10)
            box.pack(fill="x")
            ttk.Label(box, text="Input mode", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=4)
            mode = ttk.Combobox(box, textvariable=self.input_mode, values=("source", "energy", "wavelength"), state="readonly", width=13)
            mode.grid(row=0, column=1, sticky="ew", padx=(8, 6), pady=4)
            source = ttk.Combobox(box, textvariable=self.source_preset, values=("Cu Ka", "Co Ka", "Fe Ka", "Mo Ka", "Ag Ka", "Custom"), state="readonly", width=13)
            source.grid(row=0, column=2, sticky="ew", padx=6, pady=4)
            value = ttk.Entry(box, textvariable=self.radiation_value, width=13)
            value.grid(row=0, column=3, sticky="ew", padx=(6, 0), pady=4)
            self._radiation_source_widgets.append(source)
            self._radiation_value_widgets.append(value)

            labels = (
                ("2θ min (°)", self.two_theta_min),
                ("2θ max (°)", self.two_theta_max),
                ("Step (°)", self.step),
                ("FWHM (°)", self.fwhm),
                ("Pseudo-Voigt η", self.eta),
            )
            for index, (label, variable) in enumerate(labels):
                row = 1 + index // 2
                column = (index % 2) * 2
                ttk.Label(box, text=label, style="Card.TLabel").grid(row=row, column=column, sticky="w", pady=4)
                ttk.Entry(box, textvariable=variable, width=13).grid(row=row, column=column + 1, sticky="ew", padx=(8, 10), pady=4)
            for column in range(4):
                box.columnconfigure(column, weight=1)

            limits = ttk.LabelFrame(parent, text="Resource guards", padding=10)
            limits.pack(fill="x", pady=(8, 0))
            ttk.Label(limits, text="Profile points", style="Card.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Entry(limits, textvariable=self.max_profile_points, width=13).grid(row=0, column=1, sticky="ew", padx=(8, 16))
            ttk.Label(limits, text="Reciprocal candidates", style="Card.TLabel").grid(row=0, column=2, sticky="w")
            ttk.Entry(limits, textvariable=self.max_reflection_estimate, width=13).grid(row=0, column=3, sticky="ew", padx=(8, 0))
            limits.columnconfigure(1, weight=1)
            limits.columnconfigure(3, weight=1)

        def _labeled_entry(self, parent: Any, row: int, label: str, variable: Any, **kwargs: Any) -> None:
            ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=5)
            ttk.Entry(parent, textvariable=variable, **kwargs).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=5)

        def _path_entry(self, parent: Any, variable: Any, command: Callable[[], None]) -> None:
            row = ttk.Frame(parent, style="Card.TFrame")
            row.pack(fill="x")
            ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="Browse", style="Secondary.TButton", command=command).pack(side="left", padx=(8, 0))

        def _build_activity_panel(self) -> None:
            panel = ttk.Frame(self, padding=(18, 4, 18, 0))
            panel.pack(fill="x", side="bottom")
            title_row = ttk.Frame(panel)
            title_row.pack(fill="x")
            ttk.Label(title_row, text="Activity", font=("Segoe UI Semibold", 10), foreground=NAVY).pack(side="left")
            ttk.Button(title_row, text="Copy", style="Secondary.TButton", command=self._copy_log).pack(side="right", padx=(6, 0))
            ttk.Button(title_row, text="Clear", style="Secondary.TButton", command=self._clear_log).pack(side="right")
            log_frame = tk.Frame(panel, bg=LOG_BG, highlightbackground=BORDER, highlightthickness=1)
            log_frame.pack(fill="both", expand=True, pady=(5, 6))
            self.log = tk.Text(
                log_frame,
                height=4,
                wrap="word",
                state="disabled",
                bg=LOG_BG,
                fg=LOG_TEXT,
                insertbackground="white",
                relief="flat",
                font=("Cascadia Mono", 8),
                padx=10,
                pady=8,
            )
            scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
            self.log.configure(yscrollcommand=scrollbar.set)
            self.log.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            self.log.tag_configure("info", foreground="#BCD2E8")
            self.log.tag_configure("success", foreground="#7CE3A1")
            self.log.tag_configure("warning", foreground="#FFD166")
            self.log.tag_configure("error", foreground="#FF8F88")

        def _build_status_bar(self) -> None:
            bar = tk.Frame(self, bg="#E5EDF3", height=38)
            bar.pack(fill="x", side="bottom")
            bar.pack_propagate(False)
            ttk.Label(bar, textvariable=self.status_text, background="#E5EDF3", foreground=NAVY).pack(side="left", padx=18)
            self.progress = ttk.Progressbar(bar, mode="indeterminate", length=170)
            self.progress.pack(side="right", padx=(8, 18), pady=9)
            self.open_button = ttk.Button(bar, text="Open result folder", style="Secondary.TButton", command=self._open_last_output, state="disabled")
            self.open_button.pack(side="right", pady=4)

        def _sync_radiation_controls(self) -> None:
            mode = self.input_mode.get()
            custom_source = mode == "source" and self.source_preset.get() == "Custom"
            for widget in self._radiation_source_widgets:
                widget.configure(state="readonly" if mode == "source" else "disabled")
            for widget in self._radiation_value_widgets:
                widget.configure(state="normal" if mode in {"energy", "wavelength"} or custom_source else "disabled")
            defaults = {"energy": "83", "wavelength": "1.5406"}
            if mode in defaults and not self.radiation_value.get().strip():
                self.radiation_value.set(defaults[mode])

        def _toggle_key(self) -> None:
            self.mp_key_entry.configure(show="" if self.mp_show_key.get() else "•")

        def _add_cif_files(self) -> None:
            selected = filedialog.askopenfilenames(title="Select CIF files", filetypes=(("CIF structures", "*.cif"), ("All files", "*.*")))
            self._add_input_paths(Path(item) for item in selected)

        def _add_cif_folder(self) -> None:
            selected = filedialog.askdirectory(title="Select a folder containing CIF files")
            if selected:
                self._add_input_paths([Path(selected)])

        def _add_input_paths(self, paths: Any) -> None:
            existing = {path.resolve() for path in self.local_inputs}
            for path in paths:
                resolved = Path(path).expanduser().resolve()
                if resolved not in existing:
                    self.local_inputs.append(resolved)
                    existing.add(resolved)
            self._refresh_inputs()

        def _remove_inputs(self) -> None:
            selected = set(self.input_list.curselection())
            self.local_inputs = [path for index, path in enumerate(self.local_inputs) if index not in selected]
            self._refresh_inputs()

        def _clear_inputs(self) -> None:
            self.local_inputs.clear()
            self._refresh_inputs()

        def _refresh_inputs(self) -> None:
            self.input_list.delete(0, "end")
            for path in self.local_inputs:
                self.input_list.insert("end", str(path))
            count = len(self.local_inputs)
            self.input_count_text.set(f"{count} input path{'s' if count != 1 else ''} selected" if count else "No CIF inputs selected")

        def _choose_local_output(self) -> None:
            selected = filedialog.askdirectory(title="Choose or create a result directory", mustexist=False)
            if selected:
                self.local_output.set(selected)

        def _choose_mp_output(self) -> None:
            selected = filedialog.askdirectory(title="Choose or create a result directory", mustexist=False)
            if selected:
                self.mp_output.set(selected)

        def _form_analysis_settings(self) -> AnalysisSettings:
            return analysis_settings_from_form(
                {
                    "input_mode": self.input_mode.get(),
                    "source_preset": self.source_preset.get(),
                    "radiation_value": self.radiation_value.get(),
                    "two_theta_min": self.two_theta_min.get(),
                    "two_theta_max": self.two_theta_max.get(),
                    "step": self.step.get(),
                    "fwhm": self.fwhm.get(),
                    "eta": self.eta.get(),
                    "include_elasticity": self.include_elasticity.get(),
                    "max_profile_points": self.max_profile_points.get(),
                    "max_reflection_estimate": self.max_reflection_estimate.get(),
                }
            )

        def _form_discovery_settings(self) -> DiscoverySettings:
            return discovery_settings_from_form(
                {
                    "mode": self.mp_mode.get(),
                    "e_hull_max": self.mp_e_hull.get(),
                    "max_subsystem_order": self.mp_subsystem_order.get(),
                    "max_per_subsystem": self.mp_per_subsystem.get(),
                    "max_total": self.mp_limit.get(),
                    "include_deprecated": self.mp_include_deprecated.get(),
                }
            )

        def _run_local(self) -> None:
            if self.running:
                return
            output = self.local_output.get().strip()
            if not self.local_inputs or not output:
                messagebox.showerror("Missing input", "Add at least one CIF file or folder and choose a result directory.")
                return
            try:
                settings = self._form_analysis_settings()
            except ValueError as exc:
                messagebox.showerror("Invalid settings", str(exc))
                return
            inputs = [str(path) for path in self.local_inputs]
            self._start_task(
                "Analyzing local CIF structures",
                lambda: analyze_cifs(
                    inputs,
                    output,
                    settings=settings,
                    recursive=self.local_recursive.get(),
                    include_excel=self.include_excel.get(),
                    overwrite=self.overwrite.get(),
                ),
            )

        def _run_mp(self) -> None:
            if self.running:
                return
            composition = self.mp_composition.get().strip()
            api_key = self.mp_key.get().strip()
            output = self.mp_output.get().strip()
            if not composition or not api_key or not output:
                messagebox.showerror("Missing input", "Composition, API key, and result directory are required.")
                return
            try:
                discovery = self._form_discovery_settings()
                analysis = self._form_analysis_settings()
                limit = discovery.max_total
                if limit is None:
                    raise ValueError("Maximum candidates is required for the GUI download authorization.")
                if not self.mp_conventional.get() and analysis.include_elasticity:
                    raise ValueError("Disable elasticity before requesting primitive cells.")
            except ValueError as exc:
                messagebox.showerror("Invalid settings", str(exc))
                return

            def run() -> PipelineResult:
                provider = MaterialsProjectProvider(api_key)
                return run_pipeline(
                    composition,
                    provider,
                    output,
                    discovery_settings=discovery,
                    analysis_settings=analysis,
                    conventional_unit_cell=self.mp_conventional.get(),
                    include_elasticity=analysis.include_elasticity,
                    include_excel=self.include_excel.get(),
                    overwrite=self.overwrite.get(),
                    confirm_above=limit,
                    authorize_large_download=True,
                )

            self._start_task("Running Materials Project workflow", run)

        def _start_task(self, label: str, function: Callable[[], PipelineResult]) -> None:
            self.running = True
            self.status_text.set(label + "…")
            self.progress.start(12)
            self.open_button.configure(state="disabled")
            for button in self._run_buttons:
                button.configure(state="disabled")
            self._log(label + "…", "info")
            threading.Thread(target=self._worker, args=(function,), daemon=True).start()

        def _worker(self, function: Callable[[], PipelineResult]) -> None:
            try:
                self.events.put(("done", function()))
            except Exception as exc:  # pragma: no cover - thread/UI path
                self.events.put(("error", (exc, traceback.format_exc())))

        def _finish_task(self) -> None:
            self.running = False
            self.progress.stop()
            for button in self._run_buttons:
                button.configure(state="normal")

        def _log(self, text: str, level: str = "info") -> None:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log.configure(state="normal")
            self.log.insert("end", f"[{timestamp}] {text.rstrip()}\n", level)
            self.log.see("end")
            self.log.configure(state="disabled")

        def _poll(self) -> None:
            while True:
                try:
                    kind, payload = self.events.get_nowait()
                except queue.Empty:
                    break
                self._finish_task()
                if kind == "done":
                    result = payload
                    assert isinstance(result, PipelineResult)
                    self.last_output = result.output_dir
                    error_count = sum(item.level == "error" for item in result.diagnostics)
                    if not result.analyses:
                        completion = "Completed with no analyzable phases"
                        log_level = "warning"
                    elif error_count:
                        completion = f"Completed with {error_count} error diagnostic(s)"
                        log_level = "warning"
                    else:
                        completion = "Completed"
                        log_level = "success"
                    self.status_text.set(
                        f"{completion} · {len(result.analyses)} phases · "
                        f"{len(result.diagnostics)} diagnostics"
                    )
                    self.open_button.configure(state="normal")
                    self._log(f"{completion}: {result.output_dir}", log_level)
                    self._log(f"Manifest: {result.manifest_path}", "info")
                    for diagnostic in result.diagnostics:
                        self._log(
                            f"{diagnostic.stage} · {diagnostic.item}: {diagnostic.message}",
                            "error" if diagnostic.level == "error" else "warning" if diagnostic.level == "warning" else "info",
                        )
                    dialog = messagebox.showwarning if (not result.analyses or error_count) else messagebox.showinfo
                    dialog(
                        "DiffractScout",
                        f"{completion}\n\n{result.output_dir}",
                    )
                else:
                    exc, details = payload
                    self.status_text.set("Failed — see Activity log")
                    self._log(f"{exc}", "error")
                    self._log(str(details), "error")
                    messagebox.showerror("DiffractScout", str(exc))
            self.after(120, self._poll)

        def _copy_log(self) -> None:
            self.clipboard_clear()
            self.clipboard_append(self.log.get("1.0", "end-1c"))
            self.status_text.set("Activity log copied")

        def _clear_log(self) -> None:
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            self.log.configure(state="disabled")

        def _open_last_output(self) -> None:
            if self.last_output is None:
                return
            try:
                open_path(self.last_output)
            except Exception as exc:
                messagebox.showerror("Open result folder", str(exc))

        def _on_close(self) -> None:
            if self.running and not messagebox.askyesno(
                "Close DiffractScout",
                "A workflow is still running. Closing the window will stop displaying progress. Close now?",
            ):
                return
            self.destroy()

else:

    class DiffractScoutApp:  # pragma: no cover - import guard
        def __init__(self) -> None:
            raise RuntimeError("Tkinter is unavailable in this Python installation.")


def create_app() -> DiffractScoutApp:
    return DiffractScoutApp()


def main() -> None:
    app = create_app()
    app.mainloop()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
