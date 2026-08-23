"""Responsive Tk desktop interface for the tested DiffractScout pipeline API."""

from __future__ import annotations

import os
import math
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import __version__
from .diffraction import ENERGY_WAVELENGTH_KEV_A, X_RAY_SOURCES_A, validate_analysis_settings
from .elasticity_input import parse_cij_matrix_6x6, parse_cij_paste_text, parse_cubic_cij
from .gui_i18n import DEFAULT_LANG, t
from .models import AnalysisSettings, DiscoverySettings, ElasticTensor, PipelineResult
from .pipeline import analyze_cifs, run_pipeline
from .providers.materials_project import MaterialsProjectProvider
from .selection import validate_discovery_settings

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


def canonical_input_identity(path: str | Path) -> str:
    """Return the stable identity used to bind a user override to one CIF.

    A stem is not an identity: two folders can legitimately contain
    ``sample.cif`` with different structures.  The pipeline receives the
    resolved source path, so the GUI keeps the same absolute representation.
    """

    return str(Path(path).expanduser().resolve(strict=False))


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
    source_preset = str(values.get("source_preset", "Cu Ka") or "Cu Ka")
    needs_radiation_value = mode in {"wavelength", "energy"} or (
        mode == "source" and source_preset == "Custom"
    )
    # A disabled entry can retain stale text from a previous Custom/energy
    # selection.  Do not parse it unless the selected mode actually consumes
    # the value.
    radiation = (
        _optional_float(values.get("radiation_value"), "Radiation value")
        if needs_radiation_value
        else None
    )
    profile_model = str(values.get("profile_model", "pseudo_voigt")).strip()
    if profile_model not in _PROFILE_MODELS:
        raise ValueError(
            f"Profile model must be one of: {', '.join(_PROFILE_MODELS)}."
        )
    pattern_axis = str(values.get("pattern_axis", "two_theta")).strip()
    if pattern_axis not in _PATTERN_AXES:
        raise ValueError(f"Pattern axis must be one of: {', '.join(_PATTERN_AXES)}.")
    settings = AnalysisSettings(
        input_mode=mode,  # type: ignore[arg-type]
        source_preset=source_preset,
        wavelength_A=radiation if mode == "wavelength" or (mode == "source" and source_preset == "Custom") else None,
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
    validate_analysis_settings(settings)
    return settings


def discovery_settings_from_form(values: Mapping[str, object]) -> DiscoverySettings:
    mode = str(values.get("mode", "possible_phases")).strip()
    if mode not in {"possible_phases", "near_stable", "single_chemsys", "mpids_only"}:
        raise ValueError("Unknown discovery mode.")
    settings = DiscoverySettings(
        mode=mode,  # type: ignore[arg-type]
        e_hull_max_eV_atom=_optional_float(values.get("e_hull_max"), "Maximum energy above hull"),
        max_subsystem_order=_optional_int(values.get("max_subsystem_order"), "Maximum subsystem order"),
        max_per_subsystem=_optional_int(values.get("max_per_subsystem"), "Maximum per subsystem"),
        max_total=_optional_int(values.get("max_total"), "Maximum candidates"),
        exclude_deprecated=not bool(values.get("include_deprecated", False)),
    )
    validate_discovery_settings(settings)
    return settings


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
            # Prefer a size that fits common 1080p / laptop viewports; content scrolls.
            self.geometry("1200x820")
            self.minsize(900, 640)
            self.configure(background=BG)
            self.protocol("WM_DELETE_WINDOW", self._on_close)

            self.lang = DEFAULT_LANG
            self.events: queue.Queue[tuple[str, object]] = queue.Queue()
            self.running = False
            self._worker_thread: threading.Thread | None = None
            self._preview_dirs: list[Path] = []
            self.last_output: Path | None = None
            self.local_inputs: list[Path] = []
            self.elastic_overrides: dict[str, ElasticTensor] = {}
            self._run_buttons: list[ttk.Button] = []
            self._radiation_source_widgets: list[ttk.Combobox] = []
            self._radiation_value_widgets: list[ttk.Entry] = []
            self._cij_widgets: list[Any] = []
            self._lab_view_widgets: list[Any] = []
            self._help_bindings: dict[str, tuple[Any, str]] = {}
            self._radiation_value_labels: list[Any] = []
            self._i18n_targets: list[tuple[Any, str, str]] = []
            self._title_pairs: list[tuple[Any, Any, str, str]] = []
            self._labelframes: list[tuple[Any, str]] = []
            self._notebook_tabs: list[tuple[int, str]] = []
            self._wrap_labels: list[tuple[Any, int]] = []
            self._scroll_canvases: list[Any] = []
            self._scroll_interiors: list[Any] = []
            self._scroll_focus_bindings: dict[str, set[str]] = {}
            self._scroll_wheel_bindings: dict[str, set[str]] = {}
            self._syncing_shortcut = False
            self._syncing_radiation = False
            self._radiation_initialized = False
            self._previous_radiation_mode = "source"
            self._previous_source_preset = "Cu Ka"
            self._previous_radiation_value = "1.5406"
            self._lab_views_preference = True
            self._lab_views_forced_off = False
            self._poll_after_id: str | None = None
            self._wrap_after_id: str | None = None
            self._sash_after_id: str | None = None
            self._sash_initialized = False

            self._configure_style()
            self._create_variables()
            self._build_header()
            self._build_status_bar()
            self._build_main_split()
            self._sync_radiation_controls()
            self._sync_output_dependencies()
            self._refresh_cij_status()
            self._apply_language()
            self.bind("<Configure>", self._on_root_configure, add="+")
            self._poll_after_id = self.after(120, self._poll)
            self._log(self._t("log_ready"), "info")

        def _t(self, key: str, **fmt: object) -> str:
            return t(self.lang, key, **fmt)

        def _register_text(self, widget: Any, key: str, attr: str = "text") -> Any:
            self._i18n_targets.append((widget, key, attr))
            if attr == "text":
                widget.configure(text=self._t(key))
            return widget

        def _add_hover_help(self, widget: Any, key: str) -> None:
            """Attach concise help only to controls with consequential units/semantics."""

            binding_id = f"{widget}|{key}"
            if binding_id in self._help_bindings:
                return
            self._help_bindings[binding_id] = (widget, key)
            widget.bind(
                "<Enter>",
                lambda event, target=widget, help_key=key: self._show_hover_help(
                    target, help_key, event
                ),
                add="+",
            )
            widget.bind("<Leave>", lambda _event: self._hide_hover_help(), add="+")

        def _show_hover_help(self, widget: Any, key: str, event: Any) -> None:
            self._hide_hover_help()
            try:
                popup = tk.Toplevel(self)
                popup.wm_overrideredirect(True)
                popup.attributes("-topmost", True)
                label = tk.Label(
                    popup,
                    text=self._t(key),
                    justify="left",
                    wraplength=420,
                    bg="#FFFBEA",
                    fg=TEXT,
                    relief="solid",
                    borderwidth=1,
                    padx=8,
                    pady=5,
                )
                label.pack()
                x = int(getattr(event, "x_root", widget.winfo_rootx())) + 12
                y = int(getattr(event, "y_root", widget.winfo_rooty() + widget.winfo_height())) + 12
                popup.geometry(f"+{x}+{y}")
                self._hover_help_popup = popup
            except tk.TclError:
                self._hover_help_popup = None

        def _hide_hover_help(self) -> None:
            popup = getattr(self, "_hover_help_popup", None)
            self._hover_help_popup = None
            if popup is not None:
                try:
                    popup.destroy()
                except tk.TclError:
                    pass

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
            style.configure("HeaderTitle.TLabel", background=NAVY_DARK, foreground="white", font=("Segoe UI Semibold", 18))
            style.configure("HeaderSub.TLabel", background=NAVY_DARK, foreground="#BFD3E5", font=("Segoe UI", 9))
            style.configure("Badge.TLabel", background=TEAL, foreground="white", font=("Segoe UI Semibold", 9), padding=(8, 3))
            style.configure("TNotebook", background=BG, borderwidth=0)
            style.configure("TNotebook.Tab", background="#DCE6EE", foreground=NAVY, padding=(14, 6), font=("Segoe UI Semibold", 9))
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
            self.include_excel.trace_add("write", lambda *_args: self._sync_output_dependencies())
            self.include_elasticity.trace_add("write", lambda *_args: self._sync_output_dependencies())
            self.export_lab_views.trace_add("write", lambda *_args: self._sync_output_dependencies())

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
            header = tk.Frame(self, bg=NAVY_DARK, height=78)
            header.pack(fill="x")
            header.pack_propagate(False)
            logo = tk.Canvas(header, width=52, height=52, bg=NAVY_DARK, highlightthickness=0)
            logo.pack(side="left", padx=(18, 8), pady=12)
            logo.create_oval(4, 4, 48, 48, outline=TEAL, width=2)
            for x, y in ((16, 18), (36, 16), (20, 36), (38, 35)):
                logo.create_oval(x - 3, y - 3, x + 3, y + 3, fill="white", outline="")
            logo.create_line(16, 18, 36, 16, 38, 35, 20, 36, 16, 18, fill="#8BC6D5", width=2)

            text = tk.Frame(header, bg=NAVY_DARK)
            text.pack(side="left", fill="y", pady=10)
            ttk.Label(text, text="DiffractScout", style="HeaderTitle.TLabel").pack(anchor="w")
            self.header_sub = ttk.Label(text, text=self._t("app_subtitle"), style="HeaderSub.TLabel")
            self.header_sub.pack(anchor="w", pady=(2, 0))
            self._i18n_targets.append((self.header_sub, "app_subtitle", "text"))

            right = tk.Frame(header, bg=NAVY_DARK)
            right.pack(side="right", padx=18)
            ttk.Label(right, text=f"v{__version__}", style="Badge.TLabel").pack(anchor="e", pady=(6, 4))
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

        def _build_main_split(self) -> None:
            """Notebook above, resizable activity log below; both share remaining height."""

            paned = ttk.Panedwindow(self, orient="vertical")
            paned.pack(fill="both", expand=True)
            self._main_paned = paned

            body_host = ttk.Frame(paned, padding=(14, 10, 14, 4))
            activity_host = ttk.Frame(paned, padding=(14, 2, 14, 0))
            paned.add(body_host, weight=5)
            paned.add(activity_host, weight=1)

            notebook = ttk.Notebook(body_host)
            self.notebook = notebook
            notebook.pack(fill="both", expand=True)
            local = ttk.Frame(notebook, style="Card.TFrame", padding=10)
            mp = ttk.Frame(notebook, style="Card.TFrame", padding=10)
            notebook.add(local, text=self._t("tab_local"))
            notebook.add(mp, text=self._t("tab_mp"))
            self._notebook_tabs = [(0, "tab_local"), (1, "tab_mp")]
            self._build_local_tab(local)
            self._build_mp_tab(mp)
            self._build_activity_panel(activity_host)
            # Give the form most of the space only after Tk has assigned real
            # geometry. Calling sashpos against the initial 1-pixel pane can
            # make the activity pane overlap the form on short windows.
            paned.bind("<Configure>", self._schedule_default_sash, add="+")
            self._schedule_default_sash()

        def _schedule_default_sash(self, _event: object | None = None) -> None:
            if self._sash_initialized or self._sash_after_id is not None:
                return
            try:
                self._sash_after_id = self.after_idle(self._set_default_sash)
            except tk.TclError:  # pragma: no cover - teardown race
                self._sash_after_id = None

        def _set_default_sash(self) -> None:
            self._sash_after_id = None
            if self._sash_initialized:
                return
            try:
                self.update_idletasks()
                height = int(self._main_paned.winfo_height())
                if height <= 0:
                    return
                # Keep both panes usable at the minimum window size. The
                # position is relative to the Panedwindow, not the root (the
                # latter includes the header and status bar).
                activity_min = 150
                form_min = 300
                sash = max(form_min, min(height - activity_min, int(height * 0.72)))
                if sash <= 0 or sash >= height:
                    return
                self._main_paned.sashpos(0, sash)
                self._sash_initialized = True
            except (tk.TclError, ValueError):  # pragma: no cover - geometry timing
                return

        def _make_scrollable(self, parent: Any, *, bg: str = CARD) -> tuple[Any, Any]:
            """Return (outer_frame, interior_frame) with vertical scrollbar + mouse wheel."""

            outer = ttk.Frame(parent, style="Card.TFrame")
            canvas = tk.Canvas(outer, bg=bg, highlightthickness=0, bd=0)
            scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)

            interior = ttk.Frame(canvas, style="Card.TFrame")
            window_id = canvas.create_window((0, 0), window=interior, anchor="nw")
            self._scroll_canvases.append(canvas)
            self._scroll_interiors.append(interior)
            focus_bound: set[str] = set()
            self._scroll_focus_bindings[str(canvas)] = focus_bound
            wheel_bound: set[str] = set()
            self._scroll_wheel_bindings[str(canvas)] = wheel_bound

            def _sync_scrollregion(_event: object | None = None) -> None:
                canvas.configure(scrollregion=canvas.bbox("all"))

            def _sync_width(event: Any) -> None:
                canvas.itemconfigure(window_id, width=max(int(event.width), 1))

            interior.bind("<Configure>", _sync_scrollregion)
            canvas.bind("<Configure>", _sync_width)

            def _on_wheel(event: Any) -> str | None:
                if not canvas.winfo_exists():
                    return None
                # Only scroll if content overflows.
                if canvas.bbox("all") is None:
                    return None
                top, bottom = canvas.yview()
                if top <= 0.0 and bottom >= 1.0:
                    return None
                delta = int(getattr(event, "delta", 0) or 0)
                if delta:
                    canvas.yview_scroll(int(-delta / 120), "units")
                elif getattr(event, "num", None) == 4:
                    canvas.yview_scroll(-3, "units")
                elif getattr(event, "num", None) == 5:
                    canvas.yview_scroll(3, "units")
                return "break"

            def _focus_into_view(event: Any) -> None:
                """Reveal a focused descendant without changing its input bindings."""

                widget = getattr(event, "widget", None)
                try:
                    if widget is None or not canvas.winfo_exists() or not widget.winfo_exists():
                        return
                    canvas.update_idletasks()
                    scrollregion = canvas.bbox("all")
                    window_bbox = canvas.bbox(window_id)
                    viewport_height = int(canvas.winfo_height())
                    if (
                        scrollregion is None
                        or window_bbox is None
                        or viewport_height <= 0
                        or scrollregion[3] - scrollregion[1] <= viewport_height
                    ):
                        return
                    visible_top = float(canvas.canvasy(0))
                    visible_bottom = float(canvas.canvasy(viewport_height))
                    widget_top = float(window_bbox[1] + widget.winfo_rooty() - interior.winfo_rooty())
                    widget_bottom = widget_top + max(int(widget.winfo_height()), 1)
                    margin = 4.0
                    desired_top = visible_top
                    if widget_top < visible_top + margin:
                        desired_top = widget_top - margin
                    elif widget_bottom > visible_bottom - margin:
                        desired_top = widget_bottom - viewport_height + margin
                    if desired_top == visible_top:
                        return
                    minimum_top = float(scrollregion[1])
                    maximum_top = max(minimum_top, float(scrollregion[3] - viewport_height))
                    desired_top = min(max(desired_top, minimum_top), maximum_top)
                    # Canvas yview fractions are measured against the full
                    # scrollregion, not only the scrollable remainder.
                    denominator = max(1.0, float(scrollregion[3] - scrollregion[1]))
                    canvas.yview_moveto((desired_top - minimum_top) / denominator)
                except tk.TclError:
                    return

            def _bind_focus_recursive(widget: Any) -> None:
                widget_path = str(widget)
                focusable_classes = {
                    "Button",
                    "Checkbutton",
                    "Entry",
                    "Listbox",
                    "Scale",
                    "Scrollbar",
                    "Spinbox",
                    "TButton",
                    "TCheckbutton",
                    "TCombobox",
                    "TEntry",
                    "TScale",
                    "TScrollbar",
                    "Text",
                }
                if str(widget.winfo_class()) in focusable_classes and widget_path not in focus_bound:
                    widget.bind("<FocusIn>", _focus_into_view, add="+")
                    focus_bound.add(widget_path)
                for child in widget.winfo_children():
                    _bind_focus_recursive(child)

            def _bind_recursive(widget: Any) -> None:
                # Entry-like controls own their wheel gestures. In
                # particular, Tk uses the wheel over a Combobox to change its
                # current value and Text uses it for its own yview; stealing
                # either gesture makes editing a long form frustrating.
                if str(widget.winfo_class()) in {"Text", "TCombobox", "Listbox", "Spinbox"}:
                    return
                widget_path = str(widget)
                for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    binding_key = f"{widget_path}|{sequence}"
                    if binding_key not in wheel_bound:
                        widget.bind(sequence, _on_wheel, add="+")
                        wheel_bound.add(binding_key)
                for child in widget.winfo_children():
                    _bind_recursive(child)

            def _bind_tree(_event: object | None = None) -> None:
                _bind_focus_recursive(interior)
                _bind_recursive(interior)
                _bind_recursive(canvas)

            interior.bind("<Map>", lambda _e: self.after_idle(_bind_tree), add="+")
            self.after_idle(_bind_tree)
            return outer, interior

        def _card_title(self, parent: Any, title_key: str, hint_key: str) -> None:
            title = ttk.Label(parent, text=self._t(title_key), style="Title.TLabel")
            title.pack(anchor="w")
            hint = ttk.Label(parent, text=self._t(hint_key), style="Hint.TLabel", wraplength=420)
            hint.pack(anchor="w", pady=(2, 8))
            self._title_pairs.append((title, hint, title_key, hint_key))
            self._i18n_targets.append((title, title_key, "text"))
            self._i18n_targets.append((hint, hint_key, "text"))
            self._wrap_labels.append((hint, 420))

        def _labeled_frame(self, parent: Any, key: str, **kwargs: Any) -> ttk.LabelFrame:
            frame = ttk.LabelFrame(parent, text=self._t(key), **kwargs)
            self._labelframes.append((frame, key))
            return frame

        def _build_local_tab(self, frame: ttk.Frame) -> None:
            frame.columnconfigure(0, weight=1, minsize=280)
            frame.columnconfigure(1, weight=2, minsize=360)
            frame.rowconfigure(0, weight=1)

            left_shell = ttk.Frame(frame, style="Card.TFrame", padding=(0, 0, 10, 0))
            right_shell = ttk.Frame(frame, style="Card.TFrame", padding=(10, 0, 0, 0))
            left_shell.grid(row=0, column=0, sticky="nsew")
            right_shell.grid(row=0, column=1, sticky="nsew")
            left_shell.rowconfigure(0, weight=1)
            left_shell.columnconfigure(0, weight=1)
            right_shell.rowconfigure(0, weight=1)
            right_shell.columnconfigure(0, weight=1)

            # Left: keep the input list's native scrolling, while allowing
            # the lower controls to remain reachable when the tab is short.
            left_scroll, left = self._make_scrollable(left_shell)
            left_scroll.grid(row=0, column=0, sticky="nsew")
            self._local_left_scroll_canvas = self._scroll_canvases[-1]

            # The outer canvas scrolls the form; the Listbox itself retains
            # native selection and mouse-wheel behavior.
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
            buttons.pack(fill="x", pady=(0, 8))
            buttons.columnconfigure(0, weight=1)
            buttons.columnconfigure(1, weight=1)
            self.btn_add_cif = ttk.Button(
                buttons, text=self._t("btn_add_cif"), style="Secondary.TButton", command=self._add_cif_files
            )
            self.btn_add_cif.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=2)
            self._register_text(self.btn_add_cif, "btn_add_cif")
            self.btn_add_folder = ttk.Button(
                buttons, text=self._t("btn_add_folder"), style="Secondary.TButton", command=self._add_cif_folder
            )
            self.btn_add_folder.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=2)
            self._register_text(self.btn_add_folder, "btn_add_folder")
            self.btn_remove = ttk.Button(
                buttons, text=self._t("btn_remove"), style="Danger.TButton", command=self._remove_inputs
            )
            self.btn_remove.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=2)
            self._register_text(self.btn_remove, "btn_remove")
            self.btn_clear = ttk.Button(
                buttons, text=self._t("btn_clear"), style="Secondary.TButton", command=self._clear_inputs
            )
            self.btn_clear.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=2)
            self._register_text(self.btn_clear, "btn_clear")

            output_box = self._labeled_frame(left, "result_bundle", padding=8)
            output_box.pack(fill="x")
            self.local_output_entry = self._path_entry(
                output_box, self.local_output, self._choose_local_output
            )
            self.chk_recursive = ttk.Checkbutton(
                output_box, text=self._t("scan_recursive"), variable=self.local_recursive
            )
            self.chk_recursive.pack(anchor="w", pady=(6, 0))
            self._register_text(self.chk_recursive, "scan_recursive")
            self.chk_overwrite_local = ttk.Checkbutton(
                output_box, text=self._t("overwrite_bundle"), variable=self.overwrite
            )
            self.chk_overwrite_local.pack(anchor="w", pady=(2, 0))
            self._register_text(self.chk_overwrite_local, "overwrite_bundle")

            # Right: scrollable form + pinned primary action.
            scroll_outer, right = self._make_scrollable(right_shell)
            scroll_outer.grid(row=0, column=0, sticky="nsew")
            footer = ttk.Frame(right_shell, style="Card.TFrame")
            footer.grid(row=1, column=0, sticky="ew", pady=(8, 0))

            self._card_title(right, "scientific_title", "scientific_hint")
            self._analysis_controls(right)
            self._build_cij_panel(right)
            options = self._labeled_frame(right, "outputs", padding=8)
            options.pack(fill="x", pady=(8, 0))
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
            self._lab_view_widgets.append(self.chk_lab_views)
            self._add_hover_help(self.chk_lab_views, "help_lab_views")
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
                footer, text=self._t("analyze_local"), style="Primary.TButton", command=self._run_local
            )
            button.pack(fill="x")
            self._register_text(button, "analyze_local")
            self._run_buttons.append(button)

        def _build_mp_tab(self, frame: ttk.Frame) -> None:
            frame.columnconfigure(0, weight=1, minsize=280)
            frame.columnconfigure(1, weight=2, minsize=360)
            frame.rowconfigure(0, weight=1)

            left_shell = ttk.Frame(frame, style="Card.TFrame", padding=(0, 0, 10, 0))
            right_shell = ttk.Frame(frame, style="Card.TFrame", padding=(10, 0, 0, 0))
            left_shell.grid(row=0, column=0, sticky="nsew")
            right_shell.grid(row=0, column=1, sticky="nsew")
            left_shell.rowconfigure(0, weight=1)
            left_shell.columnconfigure(0, weight=1)
            right_shell.rowconfigure(0, weight=1)
            right_shell.columnconfigure(0, weight=1)

            left_scroll, left = self._make_scrollable(left_shell)
            left_scroll.grid(row=0, column=0, sticky="nsew")
            right_scroll, right = self._make_scrollable(right_shell)
            right_scroll.grid(row=0, column=0, sticky="nsew")
            footer = ttk.Frame(right_shell, style="Card.TFrame")
            footer.grid(row=1, column=0, sticky="ew", pady=(8, 0))

            self._card_title(left, "mp_discover_title", "mp_discover_hint")
            form = self._labeled_frame(left, "mp_query", padding=10)
            form.pack(fill="x")
            form.columnconfigure(1, weight=1)

            self.lbl_composition = ttk.Label(form, text=self._t("composition"), style="Card.TLabel")
            self.lbl_composition.grid(row=0, column=0, sticky="w", pady=4)
            self._register_text(self.lbl_composition, "composition")
            ttk.Entry(form, textvariable=self.mp_composition).grid(
                row=0, column=1, sticky="ew", padx=(12, 0), pady=4
            )
            self.lbl_api_key = ttk.Label(form, text=self._t("api_key"), style="Card.TLabel")
            self.lbl_api_key.grid(row=1, column=0, sticky="w", pady=4)
            self._register_text(self.lbl_api_key, "api_key")
            key_row = ttk.Frame(form, style="Card.TFrame")
            key_row.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=4)
            key_row.columnconfigure(0, weight=1)
            self.mp_key_entry = ttk.Entry(key_row, textvariable=self.mp_key, show="" if self.mp_show_key.get() else "•")
            self.mp_key_entry.grid(row=0, column=0, sticky="ew")
            self.chk_show_key = ttk.Checkbutton(
                key_row, text=self._t("show_key"), variable=self.mp_show_key, command=self._toggle_key
            )
            self.chk_show_key.grid(row=0, column=1, sticky="w", padx=(8, 0))
            self._register_text(self.chk_show_key, "show_key")
            self.lbl_mode = ttk.Label(form, text=self._t("mode"), style="Card.TLabel")
            self.lbl_mode.grid(row=2, column=0, sticky="w", pady=4)
            self._register_text(self.lbl_mode, "mode")
            ttk.Combobox(
                form,
                textvariable=self.mp_mode,
                values=("possible_phases", "near_stable", "single_chemsys", "mpids_only"),
                state="readonly",
                width=24,
            ).grid(row=2, column=1, sticky="ew", padx=(12, 0), pady=4)
            self.lbl_ehull = ttk.Label(form, text=self._t("e_hull_max"), style="Card.TLabel")
            self.lbl_ehull.grid(row=3, column=0, sticky="w", pady=4)
            self._register_text(self.lbl_ehull, "e_hull_max")
            self.mp_e_hull_entry = ttk.Entry(form, textvariable=self.mp_e_hull)
            self.mp_e_hull_entry.grid(row=3, column=1, sticky="ew", padx=(12, 0), pady=4)
            self._add_hover_help(self.lbl_ehull, "help_e_hull")
            self._add_hover_help(self.mp_e_hull_entry, "help_e_hull")
            self.lbl_sub_order = ttk.Label(form, text=self._t("subsystem_order"), style="Card.TLabel")
            self.lbl_sub_order.grid(row=4, column=0, sticky="w", pady=4)
            self._register_text(self.lbl_sub_order, "subsystem_order")
            ttk.Entry(form, textvariable=self.mp_subsystem_order).grid(
                row=4, column=1, sticky="ew", padx=(12, 0), pady=4
            )
            self.lbl_per_sub = ttk.Label(form, text=self._t("per_subsystem"), style="Card.TLabel")
            self.lbl_per_sub.grid(row=5, column=0, sticky="w", pady=4)
            self._register_text(self.lbl_per_sub, "per_subsystem")
            ttk.Entry(form, textvariable=self.mp_per_subsystem).grid(
                row=5, column=1, sticky="ew", padx=(12, 0), pady=4
            )
            self.lbl_max_cand = ttk.Label(form, text=self._t("max_candidates"), style="Card.TLabel")
            self.lbl_max_cand.grid(row=6, column=0, sticky="w", pady=4)
            self._register_text(self.lbl_max_cand, "max_candidates")
            ttk.Entry(form, textvariable=self.mp_limit).grid(row=6, column=1, sticky="ew", padx=(12, 0), pady=4)
            self.chk_deprecated = ttk.Checkbutton(
                form, text=self._t("include_deprecated"), variable=self.mp_include_deprecated
            )
            self.chk_deprecated.grid(row=7, column=0, columnspan=2, sticky="w", pady=4)
            self._register_text(self.chk_deprecated, "include_deprecated")

            output_box = self._labeled_frame(left, "result_bundle", padding=8)
            output_box.pack(fill="x", pady=(10, 0))
            self.mp_output_entry = self._path_entry(output_box, self.mp_output, self._choose_mp_output)
            self.chk_conventional = ttk.Checkbutton(
                output_box, text=self._t("conventional_cells"), variable=self.mp_conventional
            )
            self.chk_conventional.pack(anchor="w", pady=(6, 0))
            self._register_text(self.chk_conventional, "conventional_cells")
            self.chk_overwrite_mp = ttk.Checkbutton(
                output_box, text=self._t("overwrite_bundle"), variable=self.overwrite
            )
            self.chk_overwrite_mp.pack(anchor="w", pady=(2, 0))
            self._register_text(self.chk_overwrite_mp, "overwrite_bundle")
            self.mp_key_hint = ttk.Label(
                left,
                text=self._t("mp_key_hint"),
                style="Hint.TLabel",
                wraplength=400,
            )
            self.mp_key_hint.pack(anchor="w", pady=(8, 4))
            self._register_text(self.mp_key_hint, "mp_key_hint")
            self._wrap_labels.append((self.mp_key_hint, 400))

            self._card_title(right, "mp_analyze_title", "mp_analyze_hint")
            self._analysis_controls(right)
            options = self._labeled_frame(right, "outputs", padding=8)
            options.pack(fill="x", pady=(8, 0))
            self.chk_elasticity_mp = ttk.Checkbutton(
                options, text=self._t("eval_elasticity"), variable=self.include_elasticity
            )
            self.chk_elasticity_mp.pack(anchor="w")
            self._register_text(self.chk_elasticity_mp, "eval_elasticity")
            self.chk_excel_mp = ttk.Checkbutton(
                options, text=self._t("write_excel"), variable=self.include_excel
            )
            self.chk_excel_mp.pack(anchor="w")
            self._register_text(self.chk_excel_mp, "write_excel")
            self.chk_lab_views_mp = ttk.Checkbutton(
                options, text=self._t("export_lab_views"), variable=self.export_lab_views
            )
            self.chk_lab_views_mp.pack(anchor="w")
            self._register_text(self.chk_lab_views_mp, "export_lab_views")
            self._lab_view_widgets.append(self.chk_lab_views_mp)
            self._add_hover_help(self.chk_lab_views_mp, "help_lab_views")
            self.chk_patterns_mp = ttk.Checkbutton(
                options, text=self._t("include_patterns"), variable=self.include_patterns
            )
            self.chk_patterns_mp.pack(anchor="w")
            self._register_text(self.chk_patterns_mp, "include_patterns")
            self.chk_figures_mp = ttk.Checkbutton(
                options, text=self._t("include_figures"), variable=self.include_figures
            )
            self.chk_figures_mp.pack(anchor="w")
            self._register_text(self.chk_figures_mp, "include_figures")

            button = ttk.Button(
                footer, text=self._t("run_mp"), style="Primary.TButton", command=self._run_mp
            )
            button.pack(fill="x")
            self._register_text(button, "run_mp")
            self._run_buttons.append(button)

        def _analysis_controls(self, parent: ttk.Frame) -> None:
            box = self._labeled_frame(parent, "radiation_profile", padding=10)
            box.pack(fill="x")

            # Each control now occupies one label+field row.  This costs a
            # little vertical space, but avoids clipped labels/combobox values
            # when the two-column shell is narrow; the surrounding canvas
            # remains vertically scrollable and the run action stays pinned.
            box.columnconfigure(1, weight=1)

            def add_label_field(row: int, key: str, variable: Any, *, values: tuple[str, ...] | None = None) -> Any:
                label = ttk.Label(box, text=self._t(key), style="Card.TLabel")
                label.grid(row=row, column=0, sticky="w", pady=4)
                self._register_text(label, key)
                if key == "radiation_value":
                    self._radiation_value_labels.append(label)
                    self._add_hover_help(label, "help_radiation")
                if values is None:
                    field: Any = ttk.Entry(box, textvariable=variable)
                else:
                    field = ttk.Combobox(box, textvariable=variable, values=values, state="readonly", width=24)
                field.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=4)
                if key == "radiation_value":
                    self._add_hover_help(field, "help_radiation")
                elif key == "pattern_axis":
                    self._add_hover_help(label, "help_pattern_axis")
                    self._add_hover_help(field, "help_pattern_axis")
                return field

            add_label_field(0, "energy_shortcut", self.energy_shortcut, values=_ENERGY_SHORTCUTS)
            add_label_field(1, "input_mode", self.input_mode, values=("source", "energy", "wavelength"))
            source = add_label_field(
                2,
                "source_preset",
                self.source_preset,
                values=("Cu Ka", "Co Ka", "Fe Ka", "Mo Ka", "Ag Ka", "Custom"),
            )
            value = add_label_field(3, "radiation_value", self.radiation_value)
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
            for row, (key, variable) in enumerate(labels, start=4):
                add_label_field(row, key, variable)
            add_label_field(4 + len(labels), "profile_model", self.profile_model, values=_PROFILE_MODELS)
            add_label_field(5 + len(labels), "pattern_axis", self.pattern_axis, values=_PATTERN_AXES)

            limits = self._labeled_frame(parent, "resource_guards", padding=10)
            limits.pack(fill="x", pady=(8, 0))
            lbl_pp = ttk.Label(limits, text=self._t("profile_points"), style="Card.TLabel")
            lbl_pp.grid(row=0, column=0, sticky="w", pady=4)
            self._register_text(lbl_pp, "profile_points")
            ttk.Entry(limits, textvariable=self.max_profile_points).grid(
                row=0, column=1, sticky="ew", padx=(12, 0), pady=4
            )
            lbl_rc = ttk.Label(limits, text=self._t("reciprocal_candidates"), style="Card.TLabel")
            lbl_rc.grid(row=1, column=0, sticky="w", pady=4)
            self._register_text(lbl_rc, "reciprocal_candidates")
            ttk.Entry(limits, textvariable=self.max_reflection_estimate).grid(
                row=1, column=1, sticky="ew", padx=(12, 0), pady=4
            )
            limits.columnconfigure(1, weight=1)

        def _build_cij_panel(self, parent: ttk.Frame) -> None:
            box = self._labeled_frame(parent, "cij_panel", padding=8)
            box.pack(fill="x", pady=(8, 0))

            cubic = ttk.Frame(box, style="Card.TFrame")
            cubic.pack(fill="x")
            cubic.columnconfigure(1, weight=1)
            for row, (key, var) in enumerate(
                (("c11", self.cij_c11), ("c12", self.cij_c12), ("c44", self.cij_c44))
            ):
                lbl = ttk.Label(cubic, text=self._t(key), style="Card.TLabel")
                lbl.grid(row=row, column=0, sticky="w", pady=2)
                self._register_text(lbl, key)
                entry = ttk.Entry(cubic, textvariable=var, width=7)
                entry.grid(
                    row=row, column=1, sticky="ew", padx=(8, 0), pady=2
                )
                self._cij_widgets.extend((lbl, entry))
                self._add_hover_help(lbl, "help_cij")
                self._add_hover_help(entry, "help_cij")
            btn_cubic = ttk.Button(
                cubic, text=self._t("apply_cubic"), style="Secondary.TButton", command=self._apply_cubic_cij
            )
            btn_cubic.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            self.btn_apply_cubic = btn_cubic
            self._cij_widgets.append(btn_cubic)
            self._add_hover_help(btn_cubic, "help_cij")
            self._register_text(btn_cubic, "apply_cubic")

            paste_lbl = ttk.Label(box, text=self._t("cij_paste_hint"), style="Hint.TLabel", wraplength=400)
            paste_lbl.pack(anchor="w", pady=(8, 2))
            self._register_text(paste_lbl, "cij_paste_hint")
            self._wrap_labels.append((paste_lbl, 400))

            paste_frame = ttk.Frame(box, style="Card.TFrame")
            paste_frame.pack(fill="x")
            self.cij_paste = tk.Text(
                paste_frame,
                height=3,
                wrap="none",
                font=("Cascadia Mono", 8),
                relief="solid",
                borderwidth=1,
                highlightthickness=0,
            )
            yscroll = ttk.Scrollbar(paste_frame, orient="vertical", command=self.cij_paste.yview)
            xscroll = ttk.Scrollbar(paste_frame, orient="horizontal", command=self.cij_paste.xview)
            self.cij_paste.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
            self.cij_paste.grid(row=0, column=0, sticky="nsew")
            self._cij_widgets.append(self.cij_paste)
            self._add_hover_help(self.cij_paste, "help_cij")
            yscroll.grid(row=0, column=1, sticky="ns")
            xscroll.grid(row=1, column=0, sticky="ew")
            paste_frame.columnconfigure(0, weight=1)
            paste_frame.rowconfigure(0, weight=1)

            actions = ttk.Frame(box, style="Card.TFrame")
            actions.pack(fill="x", pady=(6, 0))
            btn_matrix = ttk.Button(
                actions, text=self._t("apply_matrix"), style="Secondary.TButton", command=self._apply_matrix_cij
            )
            btn_matrix.pack(side="left")
            self._register_text(btn_matrix, "apply_matrix")
            self._cij_widgets.append(btn_matrix)
            self._add_hover_help(btn_matrix, "help_cij")
            btn_clear = ttk.Button(
                actions, text=self._t("clear_cij"), style="Danger.TButton", command=self._clear_cij_override
            )
            btn_clear.pack(side="left", padx=(8, 0))
            self._register_text(btn_clear, "clear_cij")
            self._cij_widgets.append(btn_clear)
            self._add_hover_help(btn_clear, "help_cij")
            status = ttk.Label(box, textvariable=self.cij_status, style="Hint.TLabel", wraplength=400)
            status.pack(anchor="w", pady=(6, 0))
            self._wrap_labels.append((status, 400))

        def _path_entry(self, parent: Any, variable: Any, command: Callable[[], None]) -> Any:
            row = ttk.Frame(parent, style="Card.TFrame")
            row.pack(fill="x")
            entry = ttk.Entry(row, textvariable=variable)
            entry.pack(side="left", fill="x", expand=True)
            btn = ttk.Button(row, text=self._t("browse"), style="Secondary.TButton", command=command)
            btn.pack(side="left", padx=(8, 0))
            self._register_text(btn, "browse")
            return entry

        def _build_activity_panel(self, parent: Any | None = None) -> None:
            host = parent if parent is not None else self
            panel = ttk.Frame(host)
            panel.pack(fill="both", expand=True)
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
            log_frame.pack(fill="both", expand=True, pady=(4, 4))
            self.log = tk.Text(
                log_frame,
                height=5,
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
            # Mouse wheel over the log scrolls the log itself.
            def _log_wheel(event: Any) -> str | None:
                delta = int(getattr(event, "delta", 0) or 0)
                if delta:
                    self.log.yview_scroll(int(-delta / 120), "units")
                elif getattr(event, "num", None) == 4:
                    self.log.yview_scroll(-3, "units")
                elif getattr(event, "num", None) == 5:
                    self.log.yview_scroll(3, "units")
                return "break"

            self.log.bind("<MouseWheel>", _log_wheel)
            self.log.bind("<Button-4>", _log_wheel)
            self.log.bind("<Button-5>", _log_wheel)

        def _build_status_bar(self) -> None:
            # Keep the button's requested height inside the bar at the
            # minimum window size; otherwise vertical pack padding clips its
            # native glyph area before the user can resize the window.
            bar = tk.Frame(self, bg="#E5EDF3", height=42)
            bar.pack(fill="x", side="bottom")
            bar.pack_propagate(False)
            ttk.Label(bar, textvariable=self.status_text, background="#E5EDF3", foreground=NAVY).pack(
                side="left", padx=14
            )
            self.progress = ttk.Progressbar(bar, mode="indeterminate", length=140)
            self.progress.pack(side="right", padx=(8, 14), pady=7)
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
            self._sync_radiation_controls()
            self._sync_output_dependencies()
            self._schedule_wrap_update()

        def _on_root_configure(self, event: Any) -> None:
            if event.widget is not self:
                return
            # Throttle wraplength updates while resizing.
            self._schedule_wrap_update(120)

        def _schedule_wrap_update(self, delay: int | None = None) -> None:
            self._cancel_after_id("_wrap_after_id")
            if delay is None:
                self._wrap_after_id = self.after_idle(self._update_wraplengths)
            else:
                self._wrap_after_id = self.after(delay, self._update_wraplengths)

        def _cancel_after_id(self, attribute: str) -> None:
            callback_id = getattr(self, attribute, None)
            setattr(self, attribute, None)
            if callback_id is None:
                return
            try:
                self.after_cancel(callback_id)
            except (tk.TclError, ValueError):
                return

        def _cancel_scheduled_callbacks(self) -> None:
            self._cancel_after_id("_poll_after_id")
            self._cancel_after_id("_wrap_after_id")
            self._cancel_after_id("_sash_after_id")

        def _update_wraplengths(self) -> None:
            self._wrap_after_id = None
            width = max(int(self.winfo_width()), 400)
            # Rough half-column width for two-column forms.
            target = max(220, min(520, width // 2 - 80))
            for widget, _default in self._wrap_labels:
                try:
                    widget.configure(wraplength=target)
                except tk.TclError:
                    continue

        @staticmethod
        def _valid_radiation_value(value: object) -> float | None:
            try:
                parsed = float(str(value).strip())
            except (TypeError, ValueError):
                return None
            return parsed if math.isfinite(parsed) and parsed > 0 else None

        @staticmethod
        def _format_radiation_value(value: float) -> str:
            return f"{value:.10g}"

        def _transition_radiation_value(
            self,
            previous_mode: str,
            previous_source: str,
            current_mode: str,
            current_source: str,
            previous_value: str,
        ) -> str:
            """Carry radiation only through an explicit physical conversion."""

            old_wavelength: float | None = None
            old_energy: float | None = None
            if previous_mode == "energy":
                old_energy = self._valid_radiation_value(previous_value)
                if old_energy is not None:
                    old_wavelength = ENERGY_WAVELENGTH_KEV_A / old_energy
            elif previous_mode == "wavelength":
                old_wavelength = self._valid_radiation_value(previous_value)
                if old_wavelength is not None:
                    old_energy = ENERGY_WAVELENGTH_KEV_A / old_wavelength
            elif previous_mode == "source":
                preset = X_RAY_SOURCES_A.get(previous_source)
                if preset is not None:
                    old_wavelength = float(preset)
                elif previous_source == "Custom":
                    old_wavelength = self._valid_radiation_value(previous_value)
                if old_wavelength is not None:
                    old_energy = ENERGY_WAVELENGTH_KEV_A / old_wavelength

            if current_mode == "source":
                if current_source == "Custom":
                    if previous_mode == "source" and previous_source != "Custom":
                        return ""
                    return (
                        self._format_radiation_value(old_wavelength)
                        if old_wavelength is not None
                        else ""
                    )
                preset = X_RAY_SOURCES_A.get(current_source)
                return self._format_radiation_value(float(preset)) if preset is not None else ""
            if current_mode == "energy":
                return (
                    self._format_radiation_value(old_energy)
                    if old_energy is not None
                    else ""
                )
            if current_mode == "wavelength":
                return (
                    self._format_radiation_value(old_wavelength)
                    if old_wavelength is not None
                    else ""
                )
            return ""

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
                elif shortcut == _SHORTCUT_CUSTOM:
                    # Custom source is wavelength-only in the GUI.  Clear the
                    # old shortcut value so a keV number cannot be consumed as Å.
                    self.input_mode.set("source")
                    self.source_preset.set("Custom")
                    self.radiation_value.set("")
            finally:
                self._syncing_shortcut = False
            self._sync_radiation_controls()

        def _sync_radiation_controls(self) -> None:
            if getattr(self, "_syncing_radiation", False):
                return
            self._syncing_radiation = True
            try:
                mode = self.input_mode.get()
                source = self.source_preset.get()
                previous_mode = self._previous_radiation_mode
                previous_source = self._previous_source_preset
                if (
                    self._radiation_initialized
                    and not self._syncing_shortcut
                    and (mode != previous_mode or source != previous_source)
                ):
                    self.radiation_value.set(
                        self._transition_radiation_value(
                            previous_mode,
                            previous_source,
                            mode,
                            source,
                            self.radiation_value.get(),
                        )
                    )
                custom_source = mode == "source" and source == "Custom"
                for widget in self._radiation_source_widgets:
                    widget.configure(state="readonly" if mode == "source" else "disabled")
                for widget in self._radiation_value_widgets:
                    widget.configure(
                        state="normal"
                        if mode in {"energy", "wavelength"} or custom_source
                        else "disabled"
                    )
                unit_key = "radiation_value_keV" if mode == "energy" else "radiation_value_A"
                for label in self._radiation_value_labels:
                    label.configure(text=self._t(unit_key))
                if not self._syncing_shortcut:
                    # Keep shortcut label coherent when mode is edited manually.
                    if mode == "source" and source == "Cu Ka":
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
                self._previous_radiation_mode = mode
                self._previous_source_preset = source
                self._previous_radiation_value = self.radiation_value.get()
                self._radiation_initialized = True
            finally:
                self._syncing_radiation = False

        def _sync_output_dependencies(self) -> None:
            if getattr(self, "_syncing_output_dependencies", False):
                return
            self._syncing_output_dependencies = True
            try:
                self._sync_output_dependencies_impl()
            finally:
                self._syncing_output_dependencies = False

        def _sync_output_dependencies_impl(self) -> None:
            """Keep controls truthful when optional outputs are disabled."""

            if not hasattr(self, "include_excel"):
                return
            excel_enabled = bool(self.include_excel.get())
            if excel_enabled:
                if self._lab_views_forced_off:
                    self.export_lab_views.set(self._lab_views_preference)
                    self._lab_views_forced_off = False
                else:
                    self._lab_views_preference = bool(self.export_lab_views.get())
            else:
                if not self._lab_views_forced_off:
                    self._lab_views_preference = bool(self.export_lab_views.get())
                    self._lab_views_forced_off = True
                if self.export_lab_views.get():
                    self.export_lab_views.set(False)
            lab_state = "normal" if excel_enabled else "disabled"
            for widget in self._lab_view_widgets:
                try:
                    widget.configure(state=lab_state)
                except tk.TclError:
                    continue

            elasticity_enabled = bool(self.include_elasticity.get())
            elasticity_state = "normal" if elasticity_enabled else "disabled"
            for widget in self._cij_widgets:
                try:
                    if widget is getattr(self, "cij_paste", None):
                        widget.configure(state="normal" if elasticity_enabled else "disabled")
                    else:
                        widget.configure(state=elasticity_state)
                except tk.TclError:
                    continue

        def _toggle_key(self) -> None:
            self.mp_key_entry.configure(show="" if self.mp_show_key.get() else "•")

        def _selected_input_paths(self) -> list[Path]:
            selected = list(self.input_list.curselection())
            paths: list[Path] = []
            for index in selected:
                if index < 0 or index >= len(self.local_inputs):
                    continue
                paths.append(self.local_inputs[index])
            return paths

        def _selected_cif_paths(self) -> list[Path]:
            return [
                path
                for path in self._selected_input_paths()
                if path.is_file() and path.suffix.lower() == ".cif"
            ]

        def _selected_cif_identities(self) -> list[str]:
            return [canonical_input_identity(path) for path in self._selected_cif_paths()]

        def _apply_cubic_cij(self) -> None:
            identities = self._selected_cif_identities()
            if not identities:
                messagebox.showerror(self._t("err_cij_apply"), self._t("err_cij_select"))
                return
            try:
                tensor = parse_cubic_cij(
                    _required_float(self.cij_c11.get(), "C11"),
                    _required_float(self.cij_c12.get(), "C12"),
                    _required_float(self.cij_c44.get(), "C44"),
                    source="gui_cubic",
                )
                if tensor.status == "invalid":
                    raise ValueError(" | ".join(tensor.warnings))
            except ValueError as exc:
                messagebox.showerror(self._t("err_cij_apply"), self._validation_message(exc))
                return
            for identity in identities:
                self.elastic_overrides[identity] = tensor
            self._refresh_cij_status()
            self._log(self._t("log_cij_override", kind="cubic", paths=", ".join(identities)), "info")

        def _apply_matrix_cij(self) -> None:
            identities = self._selected_cif_identities()
            if not identities:
                messagebox.showerror(self._t("err_cij_apply"), self._t("err_cij_select"))
                return
            try:
                matrix = parse_cij_paste_text(self.cij_paste.get("1.0", "end"))
                tensor = parse_cij_matrix_6x6(matrix)
                if tensor.status == "invalid":
                    raise ValueError(" | ".join(tensor.warnings))
            except ValueError as exc:
                messagebox.showerror(self._t("err_cij_apply"), self._validation_message(exc))
                return
            for identity in identities:
                self.elastic_overrides[identity] = tensor
            self._refresh_cij_status()
            self._log(self._t("log_cij_override", kind="matrix", paths=", ".join(identities)), "info")

        def _clear_cij_override(self) -> None:
            selected = self._selected_input_paths()
            if not selected:
                self.elastic_overrides.clear()
            elif any(not (path.is_file() and path.suffix.lower() == ".cif") for path in selected):
                # A selected folder is an explicit selection, not the same
                # as no selection. Never interpret it as permission to wipe
                # overrides for unrelated CIF files.
                messagebox.showwarning(self._t("err_cij_apply"), self._t("err_cij_select"))
                return
            else:
                identities = [canonical_input_identity(path) for path in selected]
                for identity in identities:
                    self.elastic_overrides.pop(identity, None)
            self._refresh_cij_status()

        def _refresh_cij_status(self) -> None:
            if not self.elastic_overrides:
                self.cij_status.set(self._t("cij_none"))
                return
            keys = ", ".join(sorted(self.elastic_overrides))
            self.cij_status.set(self._t("cij_status", paths=keys))

        def _add_cif_files(self) -> None:
            selected = filedialog.askopenfilenames(
                title=self._t("dialog_file_select"),
                filetypes=((self._t("filetype_cif"), "*.cif"), (self._t("filetype_all"), "*.*")),
            )
            self._add_input_paths(Path(item) for item in selected)

        def _add_cif_folder(self) -> None:
            selected = filedialog.askdirectory(title=self._t("dialog_folder_select"))
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
            removed = [path for index, path in enumerate(self.local_inputs) if index in selected]
            for path in removed:
                self.elastic_overrides.pop(canonical_input_identity(path), None)
            self.local_inputs = [path for index, path in enumerate(self.local_inputs) if index not in selected]
            self._refresh_inputs()

        def _clear_inputs(self) -> None:
            self.local_inputs.clear()
            self.elastic_overrides.clear()
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
            selected = filedialog.askdirectory(title=self._t("dialog_output_select"), mustexist=False)
            if selected:
                self.local_output.set(selected)

        def _choose_mp_output(self) -> None:
            selected = filedialog.askdirectory(title=self._t("dialog_output_select"), mustexist=False)
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
                    "export_lab_views": bool(self.include_excel.get() and self.export_lab_views.get()),
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

        def _validation_message(self, exc: Exception) -> str:
            """Map stable validation contracts without hiding unknown failures."""

            detail = str(exc)
            lowered = " ".join(detail.casefold().split())

            def field_label(raw: str) -> str:
                normalized = raw.strip().rstrip(".").casefold().replace("θ", "theta")
                labels = {
                    "2theta minimum": "two_theta_min",
                    "2theta maximum": "two_theta_max",
                    "radiation value": "radiation_value",
                    "profile step": "step",
                    "fwhm": "fwhm",
                    "pseudo-voigt η": "eta",
                    "pseudo-voigt eta": "eta",
                    "d_min_a": "d_min",
                    "d_max_a": "d_max",
                    "maximum profile points": "profile_points",
                    "maximum reciprocal candidates": "reciprocal_candidates",
                    "maximum energy above hull": "e_hull_max",
                    "maximum subsystem order": "subsystem_order",
                    "maximum per subsystem": "per_subsystem",
                    "maximum candidates": "max_candidates",
                    "c11": "c11",
                    "c12": "c12",
                    "c44": "c44",
                }
                key = labels.get(normalized)
                return self._t(key) if key is not None else raw.strip().rstrip(".")

            if "2theta range must satisfy" in lowered or "2θ range must satisfy" in lowered:
                return self._t("validation_range")
            if "diffraction settings must be finite numbers" in lowered:
                return self._t("validation_finite")
            if "step_deg and fwhm_deg must be positive" in lowered:
                return self._t("validation_positive_profile")
            if "profile_eta must lie in [0, 1]" in lowered:
                return self._t("validation_eta")
            if "unknown profile_model" in lowered or "profile model must be one of" in lowered:
                return self._t("validation_profile_model")
            if "unknown pattern_axis" in lowered or "pattern axis must be one of" in lowered:
                return self._t("validation_pattern_axis")
            if "d_min_a must be <= d_max_a" in lowered:
                return self._t("validation_d_order")
            if ("d_min_a" in lowered or "d_max_a" in lowered) and "finite positive number" in lowered:
                field = self._t("d_min") if "d_min_a" in lowered else self._t("d_max")
                return self._t("validation_d_positive", field=field)
            if "custom source preset" in lowered:
                return self._t("validation_custom_radiation")
            if "unknown x-ray source preset" in lowered:
                return self._t("validation_source_preset")
            if "energy_kev" in lowered or "wavelength_a" in lowered:
                if "finite positive number" in lowered or "required" in lowered:
                    return self._t("validation_radiation")
            if "unknown discovery mode" in lowered:
                return self._t("validation_discovery_mode")
            if any(name in lowered for name in ("max_profile_points", "max_reflection_estimate")) and "positive integer" in lowered:
                field = (
                    self._t("profile_points")
                    if "max_profile_points" in lowered
                    else self._t("reciprocal_candidates")
                )
                return self._t("validation_resource_integer", field=field)
            discovery_names = (
                "max_subsystem_order",
                "max_subsystems",
                "max_per_subsystem",
                "max_total",
            )
            if any(name in lowered for name in discovery_names) and "positive integer" in lowered:
                field_keys = {
                    "max_subsystem_order": "subsystem_order",
                    "max_subsystems": "resource_guards",
                    "max_per_subsystem": "per_subsystem",
                    "max_total": "max_candidates",
                }
                name = next(name for name in discovery_names if name in lowered)
                return self._t("validation_discovery_integer", field=self._t(field_keys[name]))
            if lowered.endswith(" must be a number."):
                field = detail[: -len(" must be a number.")]
                return self._t("validation_gui_number", field=field_label(field))
            if lowered.endswith(" must be an integer."):
                field = detail[: -len(" must be an integer.")]
                return self._t("validation_gui_integer", field=field_label(field))
            if "output" in lowered or "result directory" in lowered:
                return self._t("validation_output", error=detail)
            return self._t("validation_generic", error=detail)

        def _run_local(self) -> None:
            if self.running:
                return
            output = self.local_output.get().strip()
            if not self.local_inputs and not output:
                messagebox.showerror(self._t("err_title_missing"), self._t("err_missing_local"))
                return
            if not self.local_inputs:
                messagebox.showerror(self._t("err_title_missing"), self._t("err_missing_local_inputs"))
                return
            if not output:
                messagebox.showerror(self._t("err_title_missing"), self._t("err_missing_output"))
                return
            try:
                settings = self._form_analysis_settings()
            except ValueError as exc:
                messagebox.showerror(self._t("err_title_settings"), self._validation_message(exc))
                return
            inputs = [str(path) for path in self.local_inputs]
            overrides = dict(self.elastic_overrides) if self.elastic_overrides else None
            recursive = bool(self.local_recursive.get())
            include_excel = bool(self.include_excel.get())
            overwrite = bool(self.overwrite.get())
            label = self._t("analyze_local") if hasattr(self, "_t") else "Analyze selected CIFs"
            self._start_task(
                label,
                lambda: analyze_cifs(
                    inputs,
                    output,
                    settings=settings,
                    recursive=recursive,
                    include_excel=include_excel,
                    overwrite=overwrite,
                    elastic_overrides=overrides,
                ),
            )

        def _run_mp(self) -> None:
            if self.running:
                return
            composition = self.mp_composition.get().strip()
            api_key = self.mp_key.get().strip()
            output = self.mp_output.get().strip()
            if not composition and not api_key and not output:
                messagebox.showerror(self._t("err_title_missing"), self._t("err_missing_mp"))
                return
            if not composition:
                messagebox.showerror(self._t("err_title_missing"), self._t("err_missing_mp_composition"))
                return
            if not api_key:
                messagebox.showerror(self._t("err_title_missing"), self._t("err_missing_mp_api_key"))
                return
            if not output:
                messagebox.showerror(self._t("err_title_missing"), self._t("err_missing_mp_output"))
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
                messagebox.showerror(self._t("err_title_settings"), self._validation_message(exc))
                return

            conventional = bool(self.mp_conventional.get())
            include_excel = bool(self.include_excel.get())
            overwrite = bool(self.overwrite.get())

            def run() -> PipelineResult:
                provider = MaterialsProjectProvider(api_key)
                return run_pipeline(
                    composition,
                    provider,
                    output,
                    discovery_settings=discovery,
                    analysis_settings=analysis,
                    conventional_unit_cell=conventional,
                    include_elasticity=analysis.include_elasticity,
                    include_excel=include_excel,
                    overwrite=overwrite,
                    confirm_above=limit,
                    authorize_large_download=True,
                )

            self._start_task(self._t("run_mp"), run)

        def _start_task(self, label: str, function: Callable[[], PipelineResult]) -> None:
            self.running = True
            self.status_text.set(self._t("status_busy", label=label))
            self.progress.start(12)
            DiffractScoutApp._update_open_button_state(self)
            for button in self._run_buttons:
                button.configure(state="disabled")
            self._log(self._t("log_started", label=label), "info")
            self._worker_thread = threading.Thread(target=self._worker, args=(function,), daemon=False)
            self._worker_thread.start()

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
            DiffractScoutApp._update_open_button_state(self)

        def _update_open_button_state(self) -> None:
            if getattr(self, "running", False):
                self.open_button.configure(state="disabled")
                return
            target = getattr(self, "last_output", None)
            usable = False
            if target is not None:
                path = Path(target)
                usable = path.is_dir() and (
                    (path / "manifest.json").is_file()
                    or (path / "results.xlsx").is_file()
                )
            self.open_button.configure(state="normal" if usable else "disabled")

        def _log(self, text: str, level: str = "info") -> None:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log.configure(state="normal")
            self.log.insert("end", f"[{timestamp}] {text.rstrip()}\n", level)
            self.log.see("end")
            self.log.configure(state="disabled")

        def _poll(self) -> None:
            self._poll_after_id = None
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
                        completion = self._t("status_completed_empty")
                        log_level = "warning"
                    elif error_count:
                        completion = self._t("status_completed_diagnostics", n=error_count)
                        log_level = "warning"
                    else:
                        completion = self._t("status_completed")
                        log_level = "success"
                    self.status_text.set(self._t(
                        "status_summary",
                        message=completion,
                        phases=len(result.analyses),
                        diagnostics=len(result.diagnostics),
                    ))
                    DiffractScoutApp._update_open_button_state(self)
                    self._log(self._t("log_completed", message=completion, path=result.output_dir), log_level)
                    self._log(self._t("log_manifest", path=result.manifest_path), "info")
                    for diagnostic in result.diagnostics:
                        self._log(
                            self._t(
                                "log_diagnostic",
                                stage=diagnostic.stage,
                                item=diagnostic.item,
                                message=diagnostic.message,
                            ),
                            "error"
                            if diagnostic.level == "error"
                            else "warning"
                            if diagnostic.level == "warning"
                            else "info",
                        )
                    dialog = messagebox.showwarning if (not result.analyses or error_count) else messagebox.showinfo
                    dialog(
                        self._t("dialog_result_title"),
                        self._t("dialog_result_message", path=result.output_dir),
                    )
                else:
                    exc, details = payload
                    self.status_text.set(self._t("status_failed"))
                    self._log(f"{exc}", "error")
                    self._log(str(details), "error")
                    messagebox.showerror(
                        self._t("dialog_failed_title"),
                        self._t("dialog_failed_message", error=str(exc)),
                    )
            try:
                self._poll_after_id = self.after(120, self._poll)
            except tk.TclError:
                self._poll_after_id = None

        def _copy_log(self) -> None:
            self.clipboard_clear()
            self.clipboard_append(self.log.get("1.0", "end-1c"))
            self.status_text.set(self._t("status_log_copied"))

        def _clear_log(self) -> None:
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            self.log.configure(state="disabled")

        def _preview_workbook(self, workbook: Path) -> Path:
            """Copy a result workbook outside its bundle before opening it.

            Excel creates ``~$results.xlsx`` beside an opened workbook.  The
            bundle is immutable evidence, so opening a preview copy keeps
            verifier inputs unchanged while retaining the user's workbook.
            """

            preview_dir = Path(tempfile.mkdtemp(prefix="diffractscout-preview-"))
            preview_path = preview_dir / workbook.name
            try:
                shutil.copy2(workbook, preview_path)
            except Exception:
                shutil.rmtree(preview_dir, ignore_errors=True)
                raise
            self._preview_dirs.append(preview_dir)
            return preview_path

        def _cleanup_preview_dirs(self) -> None:
            remaining: list[Path] = []
            for preview_dir in list(self._preview_dirs):
                try:
                    if preview_dir.is_dir():
                        shutil.rmtree(preview_dir)
                except OSError:
                    # Excel may still hold a preview open; leaving a temp
                    # directory is safer than touching any user bundle.
                    remaining.append(preview_dir)
                    continue
            self._preview_dirs = remaining

        def _open_last_output(self) -> None:
            if self.last_output is None:
                return
            target: Path = Path(self.last_output)
            if not target.is_dir():
                self._update_open_button_state()
                return
            xlsx = target / "results.xlsx"
            try:
                if xlsx.is_file():
                    target = self._preview_workbook(xlsx)
                open_path(target)
            except Exception as exc:
                messagebox.showerror(self._t("err_open_result"), str(exc))

        def _on_close(self) -> None:
            if self.running or (self._worker_thread is not None and self._worker_thread.is_alive()):
                # Do not destroy a live controller or rely on daemon-thread
                # truncation. The worker owns a transactional pipeline and
                # will publish a safe boundary through the event queue.
                messagebox.showinfo(
                    self._t("msg_close_title"),
                    self._t("msg_close_running"),
                )
                return
            self._cleanup_preview_dirs()
            self.destroy()

        def destroy(self) -> None:
            self._cancel_scheduled_callbacks()
            self._hide_hover_help()
            super().destroy()

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
