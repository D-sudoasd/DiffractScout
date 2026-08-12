"""Responsive Tk desktop interface for the tested DiffractScout pipeline API."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import __version__
from .elasticity_input import parse_cij_matrix_6x6, parse_cij_paste_text, parse_cubic_cij
from .gui_i18n import DEFAULT_LANG, t
from .models import AnalysisSettings, DiscoverySettings, ElasticTensor, PipelineResult
from .pipeline import analyze_cifs, run_pipeline
from .providers.materials_project import MaterialsProjectProvider

try:  # Tk remains optional on minimal/headless Python installations.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - platform-dependent
    tk = None  # type: ignore[assignment]
    filedialog = messagebox = ttk = None  # type: ignore[assignment]

try:  # Optional drag-and-drop; soft-fail when tkinterdnd2 is absent.
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _HAS_DND = True
except ImportError:  # pragma: no cover - optional dependency
    DND_FILES = None  # type: ignore[assignment]
    TkinterDnD = None  # type: ignore[assignment]
    _HAS_DND = False

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

_PROFILE_MODELS = ("pseudo_voigt", "gaussian", "lorentzian")
_PATTERN_AXES = ("two_theta", "d_spacing", "q", "g")
_SHORTCUT_CU = "Cu Kα"
_SHORTCUT_30 = "30 keV"
_SHORTCUT_83 = "83 keV"
_SHORTCUT_CUSTOM = "Custom"
_ENERGY_SHORTCUTS = (_SHORTCUT_CU, _SHORTCUT_30, _SHORTCUT_83, _SHORTCUT_CUSTOM)


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


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(value)


def analysis_settings_from_form(values: Mapping[str, object]) -> AnalysisSettings:
    mode = str(values.get("input_mode", "source")).strip().lower()
    if mode not in {"source", "wavelength", "energy"}:
        raise ValueError("Radiation mode must be source, wavelength, or energy.")
    radiation = _optional_float(values.get("radiation_value"), "Radiation value")
    profile_model = str(values.get("profile_model", "pseudo_voigt")).strip()
    if profile_model not in _PROFILE_MODELS:
        raise ValueError(
            f"Profile model must be one of: {', '.join(_PROFILE_MODELS)}."
        )
    pattern_axis = str(values.get("pattern_axis", "two_theta")).strip()
    if pattern_axis not in _PATTERN_AXES:
        raise ValueError(f"Pattern axis must be one of: {', '.join(_PATTERN_AXES)}.")
    return AnalysisSettings(
        input_mode=mode,  # type: ignore[arg-type]
        source_preset=str(values.get("source_preset", "Cu Ka")),
        wavelength_A=radiation
        if mode == "wavelength" or (mode == "source" and str(values.get("source_preset")) == "Custom")
        else None,
        energy_keV=radiation if mode == "energy" else None,
        two_theta_min_deg=_required_float(values.get("two_theta_min", 5), "2θ minimum"),
        two_theta_max_deg=_required_float(values.get("two_theta_max", 120), "2θ maximum"),
        step_deg=_required_float(values.get("step", 0.02), "Profile step"),
        fwhm_deg=_required_float(values.get("fwhm", 0.15), "FWHM"),
        profile_eta=_required_float(values.get("eta", 0.5), "Pseudo-Voigt η"),
        include_elasticity=_as_bool(values.get("include_elasticity", True), True),
        max_profile_points=_required_int(values.get("max_profile_points", 1_000_000), "Maximum profile points"),
        max_reflection_estimate=_required_int(
            values.get("max_reflection_estimate", 2_000_000),
            "Maximum reciprocal candidates",
        ),
        d_min_A=_optional_float(values.get("d_min_A"), "d_min_A"),
        d_max_A=_optional_float(values.get("d_max_A"), "d_max_A"),
        profile_model=profile_model,  # type: ignore[arg-type]
        pattern_axis=pattern_axis,  # type: ignore[arg-type]
        include_figures=_as_bool(values.get("include_figures", False), False),
        figure_preset=str(values.get("figure_preset", "publication") or "publication"),
        export_lab_views=_as_bool(values.get("export_lab_views", True), True),
        include_patterns=_as_bool(values.get("include_patterns", True), True),
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
    """Open a file or directory with the platform handler without a shell."""

    target = str(Path(path).expanduser().resolve())
    if sys.platform.startswith("win"):
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def _parse_drop_paths(data: str) -> list[Path]:
    """Parse tkinterdnd2 / Windows brace-wrapped drop payloads into paths."""

    text = str(data or "").strip()
    if not text:
        return []
    # {C:/path with spaces/a.cif} C:/other.cif
    braced = re.findall(r"\{([^}]*)\}|(\S+)", text)
    parts = [a or b for a, b in braced if (a or b)]
    return [Path(item) for item in parts if str(item).strip()]


if tk is not None:
    _TkBase = TkinterDnD.Tk if _HAS_DND and TkinterDnD is not None else tk.Tk

    class DiffractScoutApp(_TkBase):  # type: ignore[valid-type,misc]
        """Desktop controller; all scientific work is delegated to tested pipeline functions."""

        def __init__(self) -> None:
            super().__init__()
            self.title(f"DiffractScout {__version__}")
            self.geometry("1180x920")
            self.minsize(980, 780)
            self.configure(background=BG)
            self.protocol("WM_DELETE_WINDOW", self._on_close)

            self.lang = DEFAULT_LANG
            self.events: queue.Queue[tuple[str, object]] = queue.Queue()
            self.running = False
            self.last_output: Path | None = None
            self.local_inputs: list[Path] = []
            self.elastic_overrides: dict[str, ElasticTensor] = {}
            self._run_buttons: list[ttk.Button] = []
            self._radiation_source_widgets: list[ttk.Combobox] = []
            self._radiation_value_widgets: list[ttk.Entry] = []
            self._i18n_targets: list[tuple[Any, str, str]] = []
            self._title_pairs: list[tuple[Any, Any, str, str]] = []
            self._labelframes: list[tuple[Any, str]] = []
            self._notebook_tabs: list[tuple[int, str]] = []
            self._syncing_shortcut = False

            self._configure_style()
            self._create_variables()
            self._build_header()
            self._build_status_bar()
            self._build_activity_panel()
            self._build_body()
            self._sync_radiation_controls()
            self._refresh_cij_status()
            self._apply_language()
            self.after(120, self._poll)
            self._log(self._t("log_ready"), "info")

        def _t(self, key: str, **fmt: object) -> str:
            return t(self.lang, key, **fmt)

        def _register_text(self, widget: Any, key: str, attr: str = "text") -> Any:
            self._i18n_targets.append((widget, key, attr))
            if attr == "text":
                widget.configure(text=self._t(key))
            return widget

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
            self.lang_var = tk.StringVar(value=self.lang)
            self.local_output = tk.StringVar()
            self.local_recursive = tk.BooleanVar(value=True)
            self.include_excel = tk.BooleanVar(value=True)
            self.include_elasticity = tk.BooleanVar(value=True)
            self.export_lab_views = tk.BooleanVar(value=True)
            self.include_patterns = tk.BooleanVar(value=True)
            self.include_figures = tk.BooleanVar(value=False)
            self.overwrite = tk.BooleanVar(value=False)

            self.energy_shortcut = tk.StringVar(value=_SHORTCUT_CU)
            self.input_mode = tk.StringVar(value="source")
            self.source_preset = tk.StringVar(value="Cu Ka")
            self.radiation_value = tk.StringVar(value="1.5406")
            self.two_theta_min = tk.StringVar(value="5")
            self.two_theta_max = tk.StringVar(value="120")
            self.step = tk.StringVar(value="0.02")
            self.fwhm = tk.StringVar(value="0.15")
            self.eta = tk.StringVar(value="0.5")
            self.d_min_A = tk.StringVar(value="")
            self.d_max_A = tk.StringVar(value="")
            self.profile_model = tk.StringVar(value="pseudo_voigt")
            self.pattern_axis = tk.StringVar(value="two_theta")
            self.max_profile_points = tk.StringVar(value="1000000")
            self.max_reflection_estimate = tk.StringVar(value="2000000")
            self.input_mode.trace_add("write", lambda *_args: self._sync_radiation_controls())
            self.source_preset.trace_add("write", lambda *_args: self._sync_radiation_controls())
            self.energy_shortcut.trace_add("write", lambda *_args: self._on_energy_shortcut())

            self.cij_c11 = tk.StringVar(value="")
            self.cij_c12 = tk.StringVar(value="")
            self.cij_c44 = tk.StringVar(value="")
            self.cij_status = tk.StringVar(value="")

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

            self.status_text = tk.StringVar(value=self._t("status_ready"))
            self.input_count_text = tk.StringVar(value=self._t("inputs_none"))

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
            self.header_sub = ttk.Label(text, text=self._t("app_subtitle"), style="HeaderSub.TLabel")
            self.header_sub.pack(anchor="w", pady=(3, 0))
            self._i18n_targets.append((self.header_sub, "app_subtitle", "text"))

            right = tk.Frame(header, bg=NAVY_DARK)
            right.pack(side="right", padx=24)
            ttk.Label(right, text=f"v{__version__}", style="Badge.TLabel").pack(anchor="e", pady=(8, 6))
            lang_row = tk.Frame(right, bg=NAVY_DARK)
            lang_row.pack(anchor="e")
            self.lang_label = ttk.Label(lang_row, text=self._t("lang_label"), style="HeaderSub.TLabel")
            self.lang_label.pack(side="left", padx=(0, 6))
            self._i18n_targets.append((self.lang_label, "lang_label", "text"))
            lang_box = ttk.Combobox(
                lang_row,
                textvariable=self.lang_var,
                values=("zh", "en"),
                state="readonly",
                width=6,
            )
            lang_box.pack(side="left")
            lang_box.bind("<<ComboboxSelected>>", lambda _e: self._set_language(self.lang_var.get()))

        def _build_body(self) -> None:
            body = ttk.Frame(self, padding=(18, 14, 18, 4))
            body.pack(fill="both", expand=True)
            notebook = ttk.Notebook(body)
            self.notebook = notebook
            notebook.pack(fill="both", expand=True)
            local = ttk.Frame(notebook, style="Card.TFrame", padding=16)
            mp = ttk.Frame(notebook, style="Card.TFrame", padding=16)
            notebook.add(local, text=self._t("tab_local"))
            notebook.add(mp, text=self._t("tab_mp"))
            self._notebook_tabs = [(0, "tab_local"), (1, "tab_mp")]
            self._build_local_tab(local)
            self._build_mp_tab(mp)

        def _card_title(self, parent: Any, title_key: str, hint_key: str) -> None:
            title = ttk.Label(parent, text=self._t(title_key), style="Title.TLabel")
            title.pack(anchor="w")
            hint = ttk.Label(parent, text=self._t(hint_key), style="Hint.TLabel", wraplength=480)
            hint.pack(anchor="w", pady=(2, 10))
            self._title_pairs.append((title, hint, title_key, hint_key))
            self._i18n_targets.append((title, title_key, "text"))
            self._i18n_targets.append((hint, hint_key, "text"))

        def _labeled_frame(self, parent: Any, key: str, **kwargs: Any) -> ttk.LabelFrame:
            frame = ttk.LabelFrame(parent, text=self._t(key), **kwargs)
            self._labelframes.append((frame, key))
            return frame

        def _build_local_tab(self, frame: ttk.Frame) -> None:
            frame.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=1)
            frame.rowconfigure(0, weight=1)

            left = ttk.Frame(frame, style="Card.TFrame", padding=(0, 0, 12, 0))
            right = ttk.Frame(frame, style="Card.TFrame", padding=(12, 0, 0, 0))
            left.grid(row=0, column=0, sticky="nsew")
            right.grid(row=0, column=1, sticky="nsew")
            self._card_title(left, "local_select_title", "local_select_hint")

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
            self._enable_dnd(self.input_list)
            ttk.Label(left, textvariable=self.input_count_text, style="Hint.TLabel").pack(anchor="w", pady=(5, 4))

            buttons = ttk.Frame(left, style="Card.TFrame")
            buttons.pack(fill="x", pady=(0, 12))
            self.btn_add_cif = ttk.Button(
                buttons, text=self._t("btn_add_cif"), style="Secondary.TButton", command=self._add_cif_files
            )
            self.btn_add_cif.pack(side="left", padx=(0, 6))
            self._register_text(self.btn_add_cif, "btn_add_cif")
            self.btn_add_folder = ttk.Button(
                buttons, text=self._t("btn_add_folder"), style="Secondary.TButton", command=self._add_cif_folder
            )
            self.btn_add_folder.pack(side="left", padx=6)
            self._register_text(self.btn_add_folder, "btn_add_folder")
            self.btn_remove = ttk.Button(
                buttons, text=self._t("btn_remove"), style="Danger.TButton", command=self._remove_inputs
            )
            self.btn_remove.pack(side="left", padx=6)
            self._register_text(self.btn_remove, "btn_remove")
            self.btn_clear = ttk.Button(
                buttons, text=self._t("btn_clear"), style="Secondary.TButton", command=self._clear_inputs
            )
            self.btn_clear.pack(side="left", padx=6)
            self._register_text(self.btn_clear, "btn_clear")

            output_box = self._labeled_frame(left, "result_bundle", padding=10)
            output_box.pack(fill="x")
            self._path_entry(output_box, self.local_output, self._choose_local_output)
            self.chk_recursive = ttk.Checkbutton(
                output_box, text=self._t("scan_recursive"), variable=self.local_recursive
            )
            self.chk_recursive.pack(anchor="w", pady=(8, 0))
            self._register_text(self.chk_recursive, "scan_recursive")
            self.chk_overwrite_local = ttk.Checkbutton(
                output_box, text=self._t("overwrite_bundle"), variable=self.overwrite
            )
            self.chk_overwrite_local.pack(anchor="w", pady=(4, 0))
            self._register_text(self.chk_overwrite_local, "overwrite_bundle")

            self._card_title(right, "scientific_title", "scientific_hint")
            self._analysis_controls(right)
            self._build_cij_panel(right)
            options = self._labeled_frame(right, "outputs", padding=10)
            options.pack(fill="x", pady=(10, 0))
            self.chk_elasticity_local = ttk.Checkbutton(
                options, text=self._t("pair_elasticity"), variable=self.include_elasticity
            )
            self.chk_elasticity_local.pack(anchor="w")
            self._register_text(self.chk_elasticity_local, "pair_elasticity")
            self.chk_excel_local = ttk.Checkbutton(
                options, text=self._t("write_excel"), variable=self.include_excel
            )
            self.chk_excel_local.pack(anchor="w")
            self._register_text(self.chk_excel_local, "write_excel")
            self.chk_lab_views = ttk.Checkbutton(
                options, text=self._t("export_lab_views"), variable=self.export_lab_views
            )
            self.chk_lab_views.pack(anchor="w")
            self._register_text(self.chk_lab_views, "export_lab_views")
            self.chk_patterns = ttk.Checkbutton(
                options, text=self._t("include_patterns"), variable=self.include_patterns
            )
            self.chk_patterns.pack(anchor="w")
            self._register_text(self.chk_patterns, "include_patterns")
            self.chk_figures = ttk.Checkbutton(
                options, text=self._t("include_figures"), variable=self.include_figures
            )
            self.chk_figures.pack(anchor="w")
            self._register_text(self.chk_figures, "include_figures")
            button = ttk.Button(
                right, text=self._t("analyze_local"), style="Primary.TButton", command=self._run_local
            )
            button.pack(fill="x", pady=(14, 0))
            self._register_text(button, "analyze_local")
            self._run_buttons.append(button)

        def _build_mp_tab(self, frame: ttk.Frame) -> None:
            frame.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=1)
            frame.rowconfigure(0, weight=1)
            left = ttk.Frame(frame, style="Card.TFrame", padding=(0, 0, 12, 0))
            right = ttk.Frame(frame, style="Card.TFrame", padding=(12, 0, 0, 0))
            left.grid(row=0, column=0, sticky="nsew")
            right.grid(row=0, column=1, sticky="nsew")

            self._card_title(left, "mp_discover_title", "mp_discover_hint")
            form = self._labeled_frame(left, "mp_query", padding=12)
            form.pack(fill="x")
            self.lbl_composition = ttk.Label(form, text=self._t("composition"), style="Card.TLabel")
            self.lbl_composition.grid(row=0, column=0, sticky="w", pady=5)
            self._register_text(self.lbl_composition, "composition")
            ttk.Entry(form, textvariable=self.mp_composition).grid(
                row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=5
            )
            self.lbl_api_key = ttk.Label(form, text=self._t("api_key"), style="Card.TLabel")
            self.lbl_api_key.grid(row=1, column=0, sticky="w", pady=5)
            self._register_text(self.lbl_api_key, "api_key")
            self.mp_key_entry = ttk.Entry(form, textvariable=self.mp_key, show="" if self.mp_show_key.get() else "•")
            self.mp_key_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=5)
            self.chk_show_key = ttk.Checkbutton(
                form, text=self._t("show_key"), variable=self.mp_show_key, command=self._toggle_key
            )
            self.chk_show_key.grid(row=1, column=3, sticky="w")
            self._register_text(self.chk_show_key, "show_key")
            self.lbl_mode = ttk.Label(form, text=self._t("mode"), style="Card.TLabel")
            self.lbl_mode.grid(row=2, column=0, sticky="w", pady=5)
            self._register_text(self.lbl_mode, "mode")
            ttk.Combobox(
                form,
                textvariable=self.mp_mode,
                values=("possible_phases", "near_stable", "single_chemsys", "mpids_only"),
                state="readonly",
            ).grid(row=2, column=1, sticky="ew", padx=(8, 12), pady=5)
            self.lbl_ehull = ttk.Label(form, text=self._t("e_hull_max"), style="Card.TLabel")
            self.lbl_ehull.grid(row=2, column=2, sticky="w", pady=5)
            self._register_text(self.lbl_ehull, "e_hull_max")
            ttk.Entry(form, textvariable=self.mp_e_hull).grid(row=2, column=3, sticky="ew", padx=(8, 0), pady=5)
            self.lbl_sub_order = ttk.Label(form, text=self._t("subsystem_order"), style="Card.TLabel")
            self.lbl_sub_order.grid(row=3, column=0, sticky="w", pady=5)
            self._register_text(self.lbl_sub_order, "subsystem_order")
            ttk.Entry(form, textvariable=self.mp_subsystem_order).grid(
                row=3, column=1, sticky="ew", padx=(8, 12), pady=5
            )
            self.lbl_per_sub = ttk.Label(form, text=self._t("per_subsystem"), style="Card.TLabel")
            self.lbl_per_sub.grid(row=3, column=2, sticky="w", pady=5)
            self._register_text(self.lbl_per_sub, "per_subsystem")
            ttk.Entry(form, textvariable=self.mp_per_subsystem).grid(
                row=3, column=3, sticky="ew", padx=(8, 0), pady=5
            )
            self.lbl_max_cand = ttk.Label(form, text=self._t("max_candidates"), style="Card.TLabel")
            self.lbl_max_cand.grid(row=4, column=0, sticky="w", pady=5)
            self._register_text(self.lbl_max_cand, "max_candidates")
            ttk.Entry(form, textvariable=self.mp_limit).grid(row=4, column=1, sticky="ew", padx=(8, 12), pady=5)
            self.chk_deprecated = ttk.Checkbutton(
                form, text=self._t("include_deprecated"), variable=self.mp_include_deprecated
            )
            self.chk_deprecated.grid(row=4, column=2, columnspan=2, sticky="w", pady=4)
            self._register_text(self.chk_deprecated, "include_deprecated")
            form.columnconfigure(1, weight=1)
            form.columnconfigure(3, weight=1)

            output_box = self._labeled_frame(left, "result_bundle", padding=10)
            output_box.pack(fill="x", pady=(12, 0))
            self._path_entry(output_box, self.mp_output, self._choose_mp_output)
            self.chk_conventional = ttk.Checkbutton(
                output_box, text=self._t("conventional_cells"), variable=self.mp_conventional
            )
            self.chk_conventional.pack(anchor="w", pady=(8, 0))
            self._register_text(self.chk_conventional, "conventional_cells")
            self.chk_overwrite_mp = ttk.Checkbutton(
                output_box, text=self._t("overwrite_bundle"), variable=self.overwrite
            )
            self.chk_overwrite_mp.pack(anchor="w", pady=(4, 0))
            self._register_text(self.chk_overwrite_mp, "overwrite_bundle")
            self.mp_key_hint = ttk.Label(
                left,
                text=self._t("mp_key_hint"),
                style="Hint.TLabel",
                wraplength=480,
            )
            self.mp_key_hint.pack(anchor="w", pady=(10, 0))
            self._register_text(self.mp_key_hint, "mp_key_hint")

            self._card_title(right, "mp_analyze_title", "mp_analyze_hint")
            self._analysis_controls(right)
            options = self._labeled_frame(right, "outputs", padding=10)
            options.pack(fill="x", pady=(10, 0))
            self.chk_elasticity_mp = ttk.Checkbutton(
                options, text=self._t("eval_elasticity"), variable=self.include_elasticity
            )
            self.chk_elasticity_mp.pack(side="left", padx=(0, 14))
            self._register_text(self.chk_elasticity_mp, "eval_elasticity")
            self.chk_excel_mp = ttk.Checkbutton(
                options, text=self._t("write_excel"), variable=self.include_excel
            )
            self.chk_excel_mp.pack(side="left")
            self._register_text(self.chk_excel_mp, "write_excel")
            button = ttk.Button(
                right, text=self._t("run_mp"), style="Primary.TButton", command=self._run_mp
            )
            button.pack(fill="x", pady=(14, 0))
            self._register_text(button, "run_mp")
            self._run_buttons.append(button)

        def _analysis_controls(self, parent: ttk.Frame) -> None:
            box = self._labeled_frame(parent, "radiation_profile", padding=10)
            box.pack(fill="x")

            lbl_sc = ttk.Label(box, text=self._t("energy_shortcut"), style="Card.TLabel")
            lbl_sc.grid(row=0, column=0, sticky="w", pady=4)
            self._register_text(lbl_sc, "energy_shortcut")
            shortcut = ttk.Combobox(
                box,
                textvariable=self.energy_shortcut,
                values=_ENERGY_SHORTCUTS,
                state="readonly",
                width=13,
            )
            shortcut.grid(row=0, column=1, sticky="ew", padx=(8, 6), pady=4)

            lbl_mode = ttk.Label(box, text=self._t("input_mode"), style="Card.TLabel")
            lbl_mode.grid(row=0, column=2, sticky="w", pady=4)
            self._register_text(lbl_mode, "input_mode")
            mode = ttk.Combobox(
                box,
                textvariable=self.input_mode,
                values=("source", "energy", "wavelength"),
                state="readonly",
                width=13,
            )
            mode.grid(row=0, column=3, sticky="ew", padx=(6, 0), pady=4)

            source = ttk.Combobox(
                box,
                textvariable=self.source_preset,
                values=("Cu Ka", "Co Ka", "Fe Ka", "Mo Ka", "Ag Ka", "Custom"),
                state="readonly",
                width=13,
            )
            source.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=4)
            value = ttk.Entry(box, textvariable=self.radiation_value, width=13)
            value.grid(row=1, column=1, sticky="ew", padx=(8, 6), pady=4)
            self._radiation_source_widgets.append(source)
            self._radiation_value_widgets.append(value)

            labels = (
                ("two_theta_min", self.two_theta_min),
                ("two_theta_max", self.two_theta_max),
                ("step", self.step),
                ("fwhm", self.fwhm),
                ("eta", self.eta),
                ("d_min", self.d_min_A),
                ("d_max", self.d_max_A),
            )
            for index, (key, variable) in enumerate(labels):
                row = 2 + index // 2
                column = (index % 2) * 2
                label = ttk.Label(box, text=self._t(key), style="Card.TLabel")
                label.grid(row=row, column=column, sticky="w", pady=4)
                self._register_text(label, key)
                ttk.Entry(box, textvariable=variable, width=13).grid(
                    row=row, column=column + 1, sticky="ew", padx=(8, 10), pady=4
                )

            row_pm = 2 + (len(labels) + 1) // 2
            lbl_pm = ttk.Label(box, text=self._t("profile_model"), style="Card.TLabel")
            lbl_pm.grid(row=row_pm, column=0, sticky="w", pady=4)
            self._register_text(lbl_pm, "profile_model")
            ttk.Combobox(
                box,
                textvariable=self.profile_model,
                values=_PROFILE_MODELS,
                state="readonly",
                width=13,
            ).grid(row=row_pm, column=1, sticky="ew", padx=(8, 10), pady=4)
            lbl_axis = ttk.Label(box, text=self._t("pattern_axis"), style="Card.TLabel")
            lbl_axis.grid(row=row_pm, column=2, sticky="w", pady=4)
            self._register_text(lbl_axis, "pattern_axis")
            ttk.Combobox(
                box,
                textvariable=self.pattern_axis,
                values=_PATTERN_AXES,
                state="readonly",
                width=13,
            ).grid(row=row_pm, column=3, sticky="ew", padx=(8, 0), pady=4)

            for column in range(4):
                box.columnconfigure(column, weight=1)

            limits = self._labeled_frame(parent, "resource_guards", padding=10)
            limits.pack(fill="x", pady=(8, 0))
            lbl_pp = ttk.Label(limits, text=self._t("profile_points"), style="Card.TLabel")
            lbl_pp.grid(row=0, column=0, sticky="w")
            self._register_text(lbl_pp, "profile_points")
            ttk.Entry(limits, textvariable=self.max_profile_points, width=13).grid(
                row=0, column=1, sticky="ew", padx=(8, 16)
            )
            lbl_rc = ttk.Label(limits, text=self._t("reciprocal_candidates"), style="Card.TLabel")
            lbl_rc.grid(row=0, column=2, sticky="w")
            self._register_text(lbl_rc, "reciprocal_candidates")
            ttk.Entry(limits, textvariable=self.max_reflection_estimate, width=13).grid(
                row=0, column=3, sticky="ew", padx=(8, 0)
            )
            limits.columnconfigure(1, weight=1)
            limits.columnconfigure(3, weight=1)

        def _build_cij_panel(self, parent: ttk.Frame) -> None:
            box = self._labeled_frame(parent, "cij_panel", padding=10)
            box.pack(fill="x", pady=(8, 0))

            cubic = ttk.Frame(box, style="Card.TFrame")
            cubic.pack(fill="x")
            for key, var in (("c11", self.cij_c11), ("c12", self.cij_c12), ("c44", self.cij_c44)):
                lbl = ttk.Label(cubic, text=self._t(key), style="Card.TLabel")
                lbl.pack(side="left")
                self._register_text(lbl, key)
                ttk.Entry(cubic, textvariable=var, width=8).pack(side="left", padx=(4, 10))
            btn_cubic = ttk.Button(
                cubic, text=self._t("apply_cubic"), style="Secondary.TButton", command=self._apply_cubic_cij
            )
            btn_cubic.pack(side="left")
            self._register_text(btn_cubic, "apply_cubic")

            paste_lbl = ttk.Label(box, text=self._t("cij_paste_hint"), style="Hint.TLabel")
            paste_lbl.pack(anchor="w", pady=(8, 2))
            self._register_text(paste_lbl, "cij_paste_hint")
            self.cij_paste = tk.Text(
                box,
                height=4,
                wrap="none",
                font=("Cascadia Mono", 8),
                relief="solid",
                borderwidth=1,
                highlightthickness=0,
            )
            self.cij_paste.pack(fill="x")

            actions = ttk.Frame(box, style="Card.TFrame")
            actions.pack(fill="x", pady=(6, 0))
            btn_matrix = ttk.Button(
                actions, text=self._t("apply_matrix"), style="Secondary.TButton", command=self._apply_matrix_cij
            )
            btn_matrix.pack(side="left")
            self._register_text(btn_matrix, "apply_matrix")
            btn_clear = ttk.Button(
                actions, text=self._t("clear_cij"), style="Danger.TButton", command=self._clear_cij_override
            )
            btn_clear.pack(side="left", padx=(8, 0))
            self._register_text(btn_clear, "clear_cij")
            ttk.Label(box, textvariable=self.cij_status, style="Hint.TLabel", wraplength=420).pack(
                anchor="w", pady=(6, 0)
            )

        def _path_entry(self, parent: Any, variable: Any, command: Callable[[], None]) -> None:
            row = ttk.Frame(parent, style="Card.TFrame")
            row.pack(fill="x")
            ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
            btn = ttk.Button(row, text=self._t("browse"), style="Secondary.TButton", command=command)
            btn.pack(side="left", padx=(8, 0))
            self._register_text(btn, "browse")

        def _build_activity_panel(self) -> None:
            panel = ttk.Frame(self, padding=(18, 4, 18, 0))
            panel.pack(fill="x", side="bottom")
            title_row = ttk.Frame(panel)
            title_row.pack(fill="x")
            self.activity_label = ttk.Label(
                title_row, text=self._t("activity"), font=("Segoe UI Semibold", 10), foreground=NAVY
            )
            self.activity_label.pack(side="left")
            self._register_text(self.activity_label, "activity")
            btn_copy = ttk.Button(
                title_row, text=self._t("copy"), style="Secondary.TButton", command=self._copy_log
            )
            btn_copy.pack(side="right", padx=(6, 0))
            self._register_text(btn_copy, "copy")
            btn_clear = ttk.Button(
                title_row, text=self._t("clear_log"), style="Secondary.TButton", command=self._clear_log
            )
            btn_clear.pack(side="right")
            self._register_text(btn_clear, "clear_log")
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
            ttk.Label(bar, textvariable=self.status_text, background="#E5EDF3", foreground=NAVY).pack(
                side="left", padx=18
            )
            self.progress = ttk.Progressbar(bar, mode="indeterminate", length=170)
            self.progress.pack(side="right", padx=(8, 18), pady=9)
            self.open_button = ttk.Button(
                bar,
                text=self._t("open_result"),
                style="Secondary.TButton",
                command=self._open_last_output,
                state="disabled",
            )
            self.open_button.pack(side="right", pady=4)
            self._register_text(self.open_button, "open_result")

        def _enable_dnd(self, widget: Any) -> None:
            if not _HAS_DND or DND_FILES is None:
                return
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop_files)
            except Exception:  # pragma: no cover - optional path
                return

        def _on_drop_files(self, event: Any) -> None:
            raw = getattr(event, "data", "")
            try:
                parts = list(self.tk.splitlist(raw))
                paths = [Path(item) for item in parts if str(item).strip()]
            except Exception:
                paths = _parse_drop_paths(str(raw))
            if paths:
                self._add_input_paths(paths)

        def _set_language(self, lang: str) -> None:
            code = str(lang or DEFAULT_LANG).strip().lower()
            if code not in {"zh", "en"}:
                code = DEFAULT_LANG
            self.lang = code
            self.lang_var.set(code)
            self._apply_language()

        def _apply_language(self) -> None:
            for widget, key, attr in self._i18n_targets:
                try:
                    if attr == "text":
                        widget.configure(text=self._t(key))
                except tk.TclError:
                    continue
            for frame, key in self._labelframes:
                try:
                    frame.configure(text=self._t(key))
                except tk.TclError:
                    continue
            for index, key in self._notebook_tabs:
                try:
                    self.notebook.tab(index, text=self._t(key))
                except tk.TclError:
                    continue
            if not self.running and self.status_text.get() in {
                t("zh", "status_ready"),
                t("en", "status_ready"),
                "Ready",
                "就绪",
            }:
                self.status_text.set(self._t("status_ready"))
            self._refresh_inputs()
            self._refresh_cij_status()

        def _on_energy_shortcut(self) -> None:
            if self._syncing_shortcut:
                return
            shortcut = self.energy_shortcut.get()
            self._syncing_shortcut = True
            try:
                if shortcut == _SHORTCUT_CU:
                    self.input_mode.set("source")
                    self.source_preset.set("Cu Ka")
                    self.radiation_value.set("1.5406")
                elif shortcut == _SHORTCUT_30:
                    self.input_mode.set("energy")
                    self.radiation_value.set("30")
                elif shortcut == _SHORTCUT_83:
                    self.input_mode.set("energy")
                    self.radiation_value.set("83")
                # Custom: leave mode/value editable without forcing values.
            finally:
                self._syncing_shortcut = False
            self._sync_radiation_controls()

        def _sync_radiation_controls(self) -> None:
            mode = self.input_mode.get()
            custom_source = mode == "source" and self.source_preset.get() == "Custom"
            for widget in self._radiation_source_widgets:
                widget.configure(state="readonly" if mode == "source" else "disabled")
            for widget in self._radiation_value_widgets:
                widget.configure(
                    state="normal" if mode in {"energy", "wavelength"} or custom_source else "disabled"
                )
            defaults = {"energy": "83", "wavelength": "1.5406"}
            if mode in defaults and not self.radiation_value.get().strip():
                self.radiation_value.set(defaults[mode])
            if not self._syncing_shortcut:
                # Keep shortcut label coherent when mode is edited manually.
                expected = None
                if mode == "source" and self.source_preset.get() == "Cu Ka":
                    expected = _SHORTCUT_CU
                elif mode == "energy" and self.radiation_value.get().strip() == "30":
                    expected = _SHORTCUT_30
                elif mode == "energy" and self.radiation_value.get().strip() == "83":
                    expected = _SHORTCUT_83
                else:
                    expected = _SHORTCUT_CUSTOM
                if self.energy_shortcut.get() != expected:
                    self._syncing_shortcut = True
                    try:
                        self.energy_shortcut.set(expected)
                    finally:
                        self._syncing_shortcut = False

        def _toggle_key(self) -> None:
            self.mp_key_entry.configure(show="" if self.mp_show_key.get() else "•")

        def _selected_cif_stems(self) -> list[str]:
            selected = list(self.input_list.curselection())
            stems: list[str] = []
            for index in selected:
                if index < 0 or index >= len(self.local_inputs):
                    continue
                path = self.local_inputs[index]
                if path.is_file() and path.suffix.lower() == ".cif":
                    stems.append(path.stem)
            return stems

        def _apply_cubic_cij(self) -> None:
            stems = self._selected_cif_stems()
            if not stems:
                messagebox.showerror(self._t("err_cij_apply"), self._t("err_cij_select"))
                return
            try:
                tensor = parse_cubic_cij(
                    _required_float(self.cij_c11.get(), "C11"),
                    _required_float(self.cij_c12.get(), "C12"),
                    _required_float(self.cij_c44.get(), "C44"),
                    source="gui_cubic",
                )
            except ValueError as exc:
                messagebox.showerror(self._t("err_cij_apply"), str(exc))
                return
            for stem in stems:
                self.elastic_overrides[stem] = tensor
            self._refresh_cij_status()
            self._log(f"Cij cubic override → {', '.join(stems)}", "info")

        def _apply_matrix_cij(self) -> None:
            stems = self._selected_cif_stems()
            if not stems:
                messagebox.showerror(self._t("err_cij_apply"), self._t("err_cij_select"))
                return
            try:
                matrix = parse_cij_paste_text(self.cij_paste.get("1.0", "end"))
                tensor = parse_cij_matrix_6x6(matrix)
            except ValueError as exc:
                messagebox.showerror(self._t("err_cij_apply"), str(exc))
                return
            for stem in stems:
                self.elastic_overrides[stem] = tensor
            self._refresh_cij_status()
            self._log(f"Cij matrix override → {', '.join(stems)}", "info")

        def _clear_cij_override(self) -> None:
            stems = self._selected_cif_stems()
            if stems:
                for stem in stems:
                    self.elastic_overrides.pop(stem, None)
            else:
                self.elastic_overrides.clear()
            self._refresh_cij_status()

        def _refresh_cij_status(self) -> None:
            if not self.elastic_overrides:
                self.cij_status.set(self._t("cij_none"))
                return
            keys = ", ".join(sorted(self.elastic_overrides))
            self.cij_status.set(f"Cij: {keys}")

        def _add_cif_files(self) -> None:
            selected = filedialog.askopenfilenames(
                title="Select CIF files",
                filetypes=(("CIF structures", "*.cif"), ("All files", "*.*")),
            )
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
            if count:
                self.input_count_text.set(self._t("inputs_count", n=count))
            else:
                self.input_count_text.set(self._t("inputs_none"))

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
                    "d_min_A": self.d_min_A.get(),
                    "d_max_A": self.d_max_A.get(),
                    "profile_model": self.profile_model.get(),
                    "pattern_axis": self.pattern_axis.get(),
                    "include_figures": self.include_figures.get(),
                    "export_lab_views": self.export_lab_views.get(),
                    "include_patterns": self.include_patterns.get(),
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
                messagebox.showerror(self._t("err_title_missing"), self._t("err_missing_local"))
                return
            try:
                settings = self._form_analysis_settings()
            except ValueError as exc:
                messagebox.showerror(self._t("err_title_settings"), str(exc))
                return
            inputs = [str(path) for path in self.local_inputs]
            overrides = dict(self.elastic_overrides) if self.elastic_overrides else None
            self._start_task(
                "Analyzing local CIF structures",
                lambda: analyze_cifs(
                    inputs,
                    output,
                    settings=settings,
                    recursive=self.local_recursive.get(),
                    include_excel=self.include_excel.get(),
                    overwrite=self.overwrite.get(),
                    elastic_overrides=overrides,
                ),
            )

        def _run_mp(self) -> None:
            if self.running:
                return
            composition = self.mp_composition.get().strip()
            api_key = self.mp_key.get().strip()
            output = self.mp_output.get().strip()
            if not composition or not api_key or not output:
                messagebox.showerror(self._t("err_title_missing"), self._t("err_missing_mp"))
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
                messagebox.showerror(self._t("err_title_settings"), str(exc))
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
                            "error"
                            if diagnostic.level == "error"
                            else "warning"
                            if diagnostic.level == "warning"
                            else "info",
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
            target: Path = Path(self.last_output)
            xlsx = target / "results.xlsx"
            if xlsx.is_file():
                target = xlsx
            try:
                open_path(target)
            except Exception as exc:
                messagebox.showerror(self._t("err_open_result"), str(exc))

        def _on_close(self) -> None:
            if self.running and not messagebox.askyesno(
                self._t("msg_close_title"),
                self._t("msg_close_running"),
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
