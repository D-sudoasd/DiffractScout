"""Read-only presentation of the existing theoretical analysis result."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Callable, Sequence

import numpy as np

try:  # Keep result-model helpers importable on Python builds without Tk.
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import ttk
except ImportError:  # pragma: no cover - platform-dependent
    tk = None  # type: ignore[assignment]
    tkfont = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]

from .gui_theme import BORDER, CARD, ERROR, MUTED, SUCCESS, TEAL_DARK, TEXT, WARNING
from .models import DiagnosticRecord, PhaseAnalysis, PipelineResult, ReflectionRecord


_PAGE_SIZE = 250
_PLOT_CACHE_PIXELS = 1800
_MISSING = object()
_PEAK_COLUMNS = (
    ("hkl", "results_peak_hkl"),
    ("two_theta_deg", "results_peak_two_theta"),
    ("d_spacing_A", "results_peak_d"),
    ("normalized_intensity", "results_peak_intensity"),
    ("q_invA", "results_peak_q"),
    ("young_modulus_hkl_normal_GPa", "results_peak_young_modulus"),
)


@dataclass(frozen=True)
class ResultCounts:
    phases: int | None
    peaks: int | None
    warnings: int | None
    errors: int | None


@dataclass
class ResultViewState:
    """Navigation state that survives language refreshes."""

    phase_index: int = 0
    peak_page: int = 0
    peak_sort_column: str = "two_theta_deg"
    peak_sort_descending: bool = False
    selected_peak_index: int | None = None
    diagnostic_filter: str = "all"
    selected_diagnostic_index: int | None = None


def result_counts(result: object) -> ResultCounts:
    """Count values that the result actually supplies; None means unavailable."""

    raw_analyses = getattr(result, "analyses", _MISSING)
    if raw_analyses is _MISSING or raw_analyses is None:
        phases: int | None = None
        peaks: int | None = None
    else:
        try:
            analyses = tuple(raw_analyses)
        except TypeError:
            analyses = ()
            phases = None
            peaks = None
        else:
            phases = len(analyses)
            peak_total = 0
            peaks_available = True
            for analysis in analyses:
                reflections = getattr(analysis, "reflections", _MISSING)
                if reflections is _MISSING or reflections is None:
                    peaks_available = False
                    break
                try:
                    peak_total += len(reflections)
                except TypeError:
                    peaks_available = False
                    break
            peaks = peak_total if peaks_available else None

    diagnostics = getattr(result, "diagnostics", _MISSING)
    if diagnostics is _MISSING or diagnostics is None:
        warnings = errors = None
    else:
        try:
            records = tuple(diagnostics)
        except TypeError:
            warnings = errors = None
        else:
            warnings = sum(str(getattr(item, "level", "")).lower() == "warning" for item in records)
            errors = sum(str(getattr(item, "level", "")).lower() == "error" for item in records)
    return ResultCounts(phases, peaks, warnings, errors)


def pixel_bucket_envelope(
    x_values: Sequence[float],
    y_values: Sequence[float],
    pixel_width: int,
) -> list[tuple[float, float]]:
    """Return a bounded curve envelope, retaining each pixel bucket's extrema.

    The y values are normalized to the largest finite value, matching the
    per-phase relative-intensity display. At most two points per horizontal
    pixel plus the endpoints are returned, so a dense profile remains cheap to
    paint while narrow peaks and local minima stay visible.
    """

    width = max(1, int(pixel_width))
    x = np.asarray(x_values, dtype=float).reshape(-1)
    y = np.asarray(y_values, dtype=float).reshape(-1)
    length = min(x.size, y.size)
    if length == 0:
        return []
    x = x[:length]
    y = y[:length]
    valid_indexes = np.flatnonzero(np.isfinite(x) & np.isfinite(y))
    if valid_indexes.size == 0:
        return []

    valid_x = x[valid_indexes]
    valid_y = y[valid_indexes]
    x_min = float(valid_x.min())
    x_span = float(valid_x.max()) - x_min
    bins = np.zeros(valid_indexes.size, dtype=np.int64)
    if x_span > 0 and width > 1:
        bins = np.floor((valid_x - x_min) / x_span * (width - 1)).astype(np.int64)
        np.clip(bins, 0, width - 1, out=bins)

    min_values = np.full(width, np.inf, dtype=float)
    max_values = np.full(width, -np.inf, dtype=float)
    np.minimum.at(min_values, bins, valid_y)
    np.maximum.at(max_values, bins, valid_y)
    min_candidates = np.flatnonzero(valid_y == min_values[bins])
    max_candidates = np.flatnonzero(valid_y == max_values[bins])
    min_indexes = np.full(width, length, dtype=np.int64)
    max_indexes = np.full(width, length, dtype=np.int64)
    np.minimum.at(min_indexes, bins[min_candidates], valid_indexes[min_candidates])
    np.minimum.at(max_indexes, bins[max_candidates], valid_indexes[max_candidates])
    retained = np.unique(
        np.concatenate(
            (
                valid_indexes[[0, -1]],
                min_indexes[min_indexes < length],
                max_indexes[max_indexes < length],
            )
        )
    )
    maximum = float(valid_y.max())
    scale = 100.0 / maximum if maximum > 0 else 0.0
    return [(float(x[index]), float(y[index] * scale)) for index in retained]


def sort_peak_indexes(
    reflections: Sequence[object], column: str, descending: bool = False
) -> list[int]:
    """Sort original reflection indexes numerically without moving missing values first."""

    def key(index: int) -> tuple[bool, object]:
        record = reflections[index]
        value = getattr(record, column, _MISSING)
        if column == "hkl" and value is not _MISSING:
            try:
                value = tuple(int(part) for part in value)
            except (TypeError, ValueError):
                value = _MISSING
        if value is _MISSING or value is None:
            return True, 0
        if isinstance(value, tuple) and descending:
            return False, tuple(-part if isinstance(part, Real) else part for part in value)
        if isinstance(value, Real):
            try:
                if not math.isfinite(float(value)):
                    return True, 0
            except (TypeError, ValueError, OverflowError):
                return True, 0
            return False, -value if descending else value
        return False, value

    return sorted(range(len(reflections)), key=key)


def paginate_indexes(
    indexes: Sequence[int], page: int, page_size: int = _PAGE_SIZE
) -> tuple[list[int], int, int]:
    """Return a page, clamped page index, and page count without dropping rows."""

    size = max(1, int(page_size))
    page_count = max(1, (len(indexes) + size - 1) // size)
    current_page = min(page_count - 1, max(0, int(page)))
    start = current_page * size
    return list(indexes[start : start + size]), current_page, page_count


def filtered_diagnostic_indexes(
    diagnostics: Sequence[object], level: str = "all"
) -> list[int]:
    """Return source indexes for the requested diagnostic level."""

    normalized = str(level).lower()
    if normalized not in {"all", "warning", "error"}:
        normalized = "all"
    return [
        index
        for index, record in enumerate(diagnostics)
        if normalized == "all"
        or str(getattr(record, "level", "")).lower() == normalized
    ]


_FrameBase = ttk.Frame if ttk is not None else object


class ResultView(_FrameBase):
    """Tk view for PipelineResult; it only presents supplied scientific data."""

    def __init__(self, master: object, translate: Callable[..., str]) -> None:
        if ttk is None or tk is None:  # pragma: no cover - platform-dependent
            raise RuntimeError("Tk is required to create the result view.")
        super().__init__(master)
        self._translate = translate
        self._result: PipelineResult | None = None
        self._state = ResultViewState()
        self._destroyed = False
        self._draw_after_id: str | None = None
        self._plot_cache_key: tuple[int, int, int, str] | None = None
        self._plot_cache: list[tuple[float, float]] = []
        self._bindings: list[tuple[object, str, str]] = []
        self._font_family = "TkDefaultFont"
        self._configure_styles()
        self._build_widgets()
        self._apply_static_translations()
        self._show_empty()

    def _tr(self, key: str, **fmt: object) -> str:
        try:
            value = self._translate(key, **fmt)
        except (KeyError, TypeError, ValueError):
            value = key
        if not isinstance(value, str) or not value:
            return key
        return value

    def _configure_styles(self) -> None:
        self._font_family = str(tkfont.nametofont("TkDefaultFont", self).actual("family"))
        style = ttk.Style(self)
        style.configure("ResultsStatus.TLabel", background=CARD, foreground=SUCCESS,
                        padding=(6, 2), font=(self._font_family, 9, "bold"))
        style.configure("ResultsError.TLabel", background=CARD, foreground=ERROR,
                        padding=(6, 2), font=(self._font_family, 9, "bold"))
        style.configure("ResultsWarning.TLabel", background=CARD, foreground=WARNING,
                        padding=(6, 2), font=(self._font_family, 9, "bold"))
        style.configure("ResultsCount.TLabel", background=CARD, foreground=TEXT,
                        font=(self._font_family, 9, "bold"))
        style.configure("Results.TEntry", padding=(6, 3))
        style.configure("Results.TCombobox", padding=(6, 3))
        style.configure("Results.TNotebook.Tab", padding=(12, 5))
        self._table_heading_font = tkfont.Font(self, font=style.lookup("Treeview.Heading", "font"))

    def _build_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._heading = ttk.Label(self, style="PageTitle.TLabel")
        self._heading.grid(row=0, column=0, sticky="w", padx=16, pady=(12, 8))

        self._empty_frame = ttk.Frame(self, style="Card.TFrame", padding=24)
        self._empty_frame.columnconfigure(0, weight=1)
        self._empty_title = ttk.Label(
            self._empty_frame, style="Title.TLabel", anchor="center", justify="center"
        )
        self._empty_title.grid(row=0, column=0, sticky="ew", pady=(32, 8))
        self._empty_body = ttk.Label(
            self._empty_frame, style="Hint.TLabel", anchor="center", justify="center",
            wraplength=620,
        )
        self._empty_body.grid(row=1, column=0, sticky="ew", pady=(0, 32))

        self._content = ttk.Frame(self, padding=(12, 0, 12, 4))
        self._content.columnconfigure(0, weight=1)
        self._content.rowconfigure(3, weight=1)

        self._summary = ttk.Frame(self._content)
        self._summary.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._summary_cards: dict[str, tuple[ttk.Label, ttk.Label]] = {}
        count_keys = (
            ("phases", "results_phases"),
            ("peaks", "results_peaks"),
            ("warnings", "results_warnings"),
            ("errors", "results_errors"),
        )
        for column, (name, key) in enumerate(count_keys):
            self._summary.columnconfigure(column, weight=1, uniform="results-count")
            card = ttk.Frame(self._summary, style="Card.TFrame", padding=(8, 4))
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 0))
            value = ttk.Label(card, style="ResultsCount.TLabel", anchor="w")
            value.pack(side="left", anchor="w")
            label = ttk.Label(card, style="Hint.TLabel", anchor="w")
            label.pack(side="left", anchor="w", padx=(6, 0))
            self._summary_cards[name] = (value, label)

        status_output = ttk.Frame(self._content, style="Card.TFrame", padding=(6, 2))
        status_output.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        status_output.columnconfigure(2, weight=1)
        self._status = ttk.Label(status_output, style="ResultsStatus.TLabel", anchor="w")
        self._status.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self._output_label = ttk.Label(status_output, style="Card.TLabel")
        self._output_label.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self._output_var = tk.StringVar(self, value="")
        self._output_entry = ttk.Entry(
            status_output, textvariable=self._output_var, state="readonly", style="Results.TEntry"
        )
        self._output_entry.grid(row=0, column=2, sticky="ew")

        phase_row = ttk.Frame(self._content, style="Card.TFrame", padding=(6, 2))
        phase_row.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        phase_row.columnconfigure(1, weight=1)
        self._phase_label = ttk.Label(phase_row, style="Card.TLabel")
        self._phase_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._phase_var = tk.StringVar(self, value="")
        self._phase_combo = ttk.Combobox(
            phase_row, textvariable=self._phase_var, state="readonly", takefocus=True,
            style="Results.TCombobox",
        )
        self._phase_combo.grid(row=0, column=1, sticky="ew")
        self._bind(self._phase_combo, "<<ComboboxSelected>>", self._on_phase_selected)

        self._notebook = ttk.Notebook(self._content, takefocus=True, style="Results.TNotebook")
        self._notebook.grid(row=3, column=0, sticky="nsew")
        self._pattern_tab = ttk.Frame(self._notebook, padding=8)
        self._pattern_tab.columnconfigure(0, weight=1)
        self._pattern_tab.rowconfigure(1, weight=1)
        self._notebook.add(self._pattern_tab)

        self._plot_note = ttk.Label(
            self._pattern_tab, style="Hint.TLabel", anchor="w", wraplength=700,
            justify="left",
        )
        self._plot_note.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self._canvas = tk.Canvas(
            self._pattern_tab, background=CARD, highlightthickness=1,
            highlightbackground=BORDER, height=190,
        )
        self._canvas.grid(row=1, column=0, sticky="nsew")
        self._bind(self._canvas, "<Configure>", self._schedule_plot)
        self._peaks_tab = ttk.Frame(self._notebook, padding=8)
        self._peaks_tab.columnconfigure(0, weight=1)
        self._peaks_tab.rowconfigure(0, weight=1)
        self._notebook.add(self._peaks_tab)
        self._peak_frame = ttk.Frame(self._peaks_tab)
        self._peak_frame.columnconfigure(0, weight=1)
        self._peak_frame.rowconfigure(0, weight=1)
        self._peak_tree = ttk.Treeview(
            self._peak_frame,
            columns=tuple(column for column, _key in _PEAK_COLUMNS),
            show="headings",
            selectmode="browse",
            takefocus=True,
        )
        self._peak_tree.grid(row=0, column=0, sticky="nsew")
        for column, _key in _PEAK_COLUMNS:
            self._peak_tree.heading(
                column,
                command=lambda selected=column: self._sort_peaks(selected),
            )
        self._peak_scroll = ttk.Scrollbar(
            self._peak_frame, orient="vertical", command=self._peak_tree.yview
        )
        self._peak_scroll.grid(row=0, column=1, sticky="ns")
        self._peak_tree.configure(yscrollcommand=self._peak_scroll.set)
        self._peak_widths = {
            "hkl": (82, "center"),
            "two_theta_deg": (100, "e"),
            "d_spacing_A": (94, "e"),
            "normalized_intensity": (120, "e"),
            "q_invA": (96, "e"),
            "young_modulus_hkl_normal_GPa": (126, "e"),
        }
        self._peak_frame.grid(row=0, column=0, sticky="nsew")
        self._bind(self._peak_tree, "<<TreeviewSelect>>", self._on_peak_selected)
        self._bind(self._peak_tree, "<Return>", self._show_selected_peak)
        self._bind(self._peak_tree, "<Double-1>", lambda event: self._show_selected_peak()
                   if self._peak_tree.identify_region(event.x, event.y) == "cell" else None)

        paging = ttk.Frame(self._peaks_tab)
        paging.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        paging.columnconfigure(1, weight=1)
        self._previous_button = ttk.Button(
            paging, style="Secondary.TButton", command=lambda: self._change_page(-1)
        )
        self._previous_button.grid(row=0, column=0, sticky="w")
        self._page_label = ttk.Label(paging, style="Hint.TLabel", anchor="center")
        self._page_label.grid(row=0, column=1, sticky="ew", padx=8)
        self._locate_button = ttk.Button(
            paging, style="Secondary.TButton", command=self._show_selected_peak, state="disabled"
        )
        self._locate_button.grid(row=0, column=2, sticky="e", padx=(0, 8))
        self._next_button = ttk.Button(
            paging, style="Secondary.TButton", command=lambda: self._change_page(1)
        )
        self._next_button.grid(row=0, column=3, sticky="e")

        self._diagnostics_tab = ttk.Frame(self._notebook, padding=8)
        self._diagnostics_tab.columnconfigure(0, weight=1)
        self._diagnostics_tab.rowconfigure(1, weight=3, minsize=90)
        self._diagnostics_tab.rowconfigure(3, weight=2, minsize=42)
        self._notebook.add(self._diagnostics_tab)
        filter_row = ttk.Frame(self._diagnostics_tab, style="Card.TFrame", padding=(8, 5))
        filter_row.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        filter_row.columnconfigure(1, weight=1)
        self._diagnostic_filter_label = ttk.Label(filter_row, style="Card.TLabel")
        self._diagnostic_filter_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._diagnostic_filter_var = tk.StringVar(self, value="")
        self._diagnostic_filter_combo = ttk.Combobox(
            filter_row, textvariable=self._diagnostic_filter_var, state="readonly", width=18
        )
        self._diagnostic_filter_combo.grid(row=0, column=1, sticky="w")
        self._bind(
            self._diagnostic_filter_combo,
            "<<ComboboxSelected>>",
            self._on_diagnostic_filter_selected,
        )

        diagnostic_frame = ttk.Frame(self._diagnostics_tab)
        diagnostic_frame.grid(row=1, column=0, sticky="nsew")
        diagnostic_frame.columnconfigure(0, weight=1)
        diagnostic_frame.rowconfigure(0, weight=1)
        self._diagnostic_tree = ttk.Treeview(
            diagnostic_frame, columns=("level", "source"), show="headings",
            selectmode="browse", takefocus=True, height=4,
        )
        self._diagnostic_tree.heading("level", anchor="w")
        self._diagnostic_tree.heading("source", anchor="w")
        self._diagnostic_tree.column("level", width=100, minwidth=78, stretch=False, anchor="w")
        self._diagnostic_tree.column("source", width=450, minwidth=120, stretch=True, anchor="w")
        self._diagnostic_tree.grid(row=0, column=0, sticky="nsew")
        self._diagnostic_scroll = ttk.Scrollbar(
            diagnostic_frame, orient="vertical", command=self._diagnostic_tree.yview
        )
        self._diagnostic_scroll.grid(row=0, column=1, sticky="ns")
        self._diagnostic_tree.configure(yscrollcommand=self._diagnostic_scroll.set)
        self._bind(
            self._diagnostic_tree, "<<TreeviewSelect>>", self._on_diagnostic_selected
        )

        details_label = ttk.Label(self._diagnostics_tab, style="Title.TLabel")
        details_label.grid(row=2, column=0, sticky="w", pady=(8, 5))
        self._diagnostic_details_label = details_label
        self._diagnostic_details = tk.Text(
            self._diagnostics_tab, height=3, wrap="word", state="disabled",
            background=CARD, foreground=TEXT, relief="solid", borderwidth=1,
            highlightthickness=0, padx=8, pady=7, font="TkTextFont",
        )
        self._diagnostic_details.grid(row=3, column=0, sticky="nsew")
        self._diagnostic_details_scroll = ttk.Scrollbar(
            self._diagnostics_tab,
            orient="vertical",
            command=self._diagnostic_details.yview,
        )
        self._diagnostic_details_scroll.grid(row=3, column=1, sticky="ns")
        self._diagnostic_details.configure(
            yscrollcommand=self._diagnostic_details_scroll.set
        )
        self._diagnostic_empty = ttk.Label(
            self._diagnostics_tab, style="Hint.TLabel", anchor="center"
        )
        self._bind(self._notebook, "<<NotebookTabChanged>>", self._on_tab_changed)

    def _bind(self, widget: object, sequence: str, callback: Callable[..., object]) -> None:
        bind = getattr(widget, "bind")
        func_id = bind(sequence, callback, add="+")
        if func_id:
            self._bindings.append((widget, sequence, str(func_id)))

    def _show_empty(self) -> None:
        self._content.grid_remove()
        self._heading.grid()
        self._empty_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self._heading.configure(text=self._tr("results_title"))
        self._empty_title.configure(text=self._tr("results_empty_title"))
        self._empty_body.configure(text=self._tr("results_empty_body"))

    def set_result(self, result: PipelineResult | None) -> None:
        """Present the supplied pipeline output without recalculating any data."""

        if self._destroyed:
            return
        self._result = result
        self._state = ResultViewState()
        self._plot_cache_key = None
        self._plot_cache = []
        self._apply_static_translations()
        if result is None:
            self._show_empty()
            return
        self._empty_frame.grid_remove()
        self._heading.grid_remove()
        self._content.grid(row=1, column=0, sticky="nsew")
        counts = result_counts(result)
        analyses = self._analyses()
        if not analyses and counts.errors:
            diagnostics = result.diagnostics or ()
            self._state.selected_diagnostic_index = next(
                (
                    index
                    for index, item in enumerate(diagnostics)
                    if item.level == "error"
                ),
                None,
            )
            self._notebook.select(self._diagnostics_tab)
        else:
            self._notebook.select(self._pattern_tab)
        self._render_result()

    def refresh_language(self) -> None:
        """Refresh labels and rows while preserving phase, page, and selections."""

        if self._destroyed:
            return
        self._apply_static_translations()
        if self._result is None:
            self._show_empty()
            return
        self._heading.configure(text=self._tr("results_title"))
        self._render_result()

    def _apply_static_translations(self) -> None:
        for name, key in (
            ("phases", "results_phases"),
            ("peaks", "results_peaks"),
            ("warnings", "results_warnings"),
            ("errors", "results_errors"),
        ):
            _value, label = self._summary_cards[name]
            label.configure(text=self._tr(key))
        self._output_label.configure(text=self._tr("results_output_path"))
        self._phase_label.configure(text=self._tr("results_phase"))
        self._notebook.tab(self._pattern_tab, text=self._tr("results_tab_pattern"))
        self._notebook.tab(self._peaks_tab, text=self._tr("results_tab_peaks"))
        self._notebook.tab(self._diagnostics_tab, text=self._tr("results_tab_diagnostics"))
        self._plot_note.configure(text=self._plot_caption())
        self._previous_button.configure(text=self._tr("results_previous_page"))
        self._next_button.configure(text=self._tr("results_next_page"))
        self._locate_button.configure(text=self._tr("results_locate_peak"))
        self._diagnostic_filter_label.configure(text=self._tr("results_diag_filter"))
        self._diagnostic_filter_combo.configure(
            values=(
                self._tr("results_diag_all"),
                self._tr("results_diag_warning"),
                self._tr("results_diag_error"),
            )
        )
        self._diagnostic_tree.heading("level", text=self._tr("results_diag_level"))
        self._diagnostic_tree.heading("source", text=self._tr("results_diag_source"))
        self._diagnostic_details_label.configure(text=self._tr("results_diag_details"))
        self._render_peak_headings()
        self._set_diagnostic_filter_label()

    def _render_result(self) -> None:
        if self._result is None:
            self._show_empty()
            return
        self._render_summary()
        self._render_phase_options()
        self._render_selected_phase()
        self._render_diagnostics()

    def _plot_caption(self, phase: PhaseAnalysis | None = None) -> str:
        if phase is None:
            analyses = self._analyses()
            if analyses:
                phase = analyses[min(max(0, self._state.phase_index), len(analyses) - 1)]
        parts = [
            self._tr("results_relative_intensity"),
            self._tr("results_reference_note"),
        ]
        if phase is not None:
            wavelength = self._format_number(phase.wavelength_A, 5)
            source = str(phase.wavelength_source or "").strip()
            if source.startswith("source_preset:"):
                source = self._tr(f"choice_{source.split(':', 1)[1]}")
            elif source == "energy_keV":
                source = f"E = {self._format_number(phase.energy_keV, 3)} keV"
            elif source == "custom_source_wavelength":
                source = self._tr("choice_Custom")
            elif source == "wavelength_A":
                source = ""
            radiation = f"λ = {wavelength} Å"
            if source:
                radiation = f"{radiation} · {source}"
            parts.append(radiation)
        return " · ".join(part for part in parts if part)

    def _render_summary(self) -> None:
        counts = result_counts(self._result)
        for name, value in (
            ("phases", counts.phases),
            ("peaks", counts.peaks),
            ("warnings", counts.warnings),
            ("errors", counts.errors),
        ):
            count_label, _name_label = self._summary_cards[name]
            count_label.configure(text="—" if value is None else str(value))

        analyses = self._analyses()
        if not analyses:
            status_key = "results_status_empty"
            status_style = "ResultsWarning.TLabel"
        elif counts.errors:
            status_key = "results_status_errors"
            status_style = "ResultsError.TLabel"
        elif counts.warnings:
            status_key = "results_status_warnings"
            status_style = "ResultsWarning.TLabel"
        else:
            status_key = "results_status_complete"
            status_style = "ResultsStatus.TLabel"
        self._status.configure(text=self._tr(status_key), style=status_style)
        self._output_var.set(str(self._result.output_dir))

    def _analyses(self) -> list[PhaseAnalysis]:
        return list(self._result.analyses or ()) if self._result is not None else []

    def _render_phase_options(self) -> None:
        analyses = self._analyses()
        labels: list[str] = []
        for index, phase in enumerate(analyses):
            structure = phase.structure
            name = str(phase.phase_name or "").strip()
            if not name:
                name = str(structure.formula or "").strip()
            if not name:
                name = structure.cif_path.stem
            if not name:
                name = self._tr("results_phase_fallback")
            symbol = str(structure.space_group_symbol or "").strip()
            number = structure.space_group_number
            if symbol and number is not None:
                space_group = f"{symbol} ({number})"
            else:
                space_group = symbol or (str(number) if number is not None else "—")
            labels.append(
                self._tr(
                    "results_phase_choice",
                    index=index + 1,
                    name=name,
                    space_group=space_group or "—",
                )
            )
        self._phase_combo.configure(values=labels, state="readonly" if labels else "disabled")
        if labels:
            self._state.phase_index = min(max(0, self._state.phase_index), len(labels) - 1)
            self._phase_combo.current(self._state.phase_index)
        else:
            self._state.phase_index = 0
            self._phase_var.set("")

    def _render_selected_phase(self) -> None:
        analyses = self._analyses()
        if not analyses:
            self._phase_label.configure(text=self._tr("results_phase"))
            self._phase_combo.configure(state="disabled")
            self._phase_combo.configure(values=(self._tr("results_no_phases_title"),))
            self._phase_combo.current(0)
            self._state.peak_page = 0
            self._state.selected_peak_index = None
            self._render_peak_page([], (), 0, 1)
            self._plot_note.configure(text=self._tr("results_no_phases"))
            self._schedule_plot()
            return
        phase = analyses[min(max(0, self._state.phase_index), len(analyses) - 1)]
        self._plot_note.configure(text=self._plot_caption(phase))
        self._phase_combo.configure(state="readonly")
        records = phase.reflections
        indexes = sort_peak_indexes(
            records, self._state.peak_sort_column, self._state.peak_sort_descending
        )
        page_indexes, self._state.peak_page, page_count = paginate_indexes(
            indexes, self._state.peak_page, _PAGE_SIZE
        )
        self._render_peak_page(page_indexes, records, len(records), page_count)
        self._schedule_plot()

    def _render_peak_headings(self) -> None:
        if not hasattr(self, "_peak_tree"):
            return
        for column, key in _PEAK_COLUMNS:
            label = self._tr(key)
            if column == self._state.peak_sort_column:
                label += " ▼" if self._state.peak_sort_descending else " ▲"
            self._peak_tree.heading(column, text=label, anchor="center")
            width, anchor = self._peak_widths[column]
            heading_width = self._table_heading_font.measure(label) + 18
            self._peak_tree.column(column, width=max(width, heading_width), minwidth=heading_width,
                                   stretch=True, anchor=anchor)

    def _render_peak_page(
        self,
        page_indexes: Sequence[int],
        records: Sequence[ReflectionRecord] = (),
        total: int = 0,
        page_count: int = 1,
    ) -> None:
        self._render_peak_headings()
        for item in self._peak_tree.get_children(""):
            self._peak_tree.delete(item)
        for index in page_indexes:
            if index >= len(records):
                continue
            peak = records[index]
            self._peak_tree.insert("", "end", iid=str(index), values=self._peak_values(peak))
        if self._state.selected_peak_index is not None:
            selected = str(self._state.selected_peak_index)
            if selected in self._peak_tree.get_children(""):
                self._peak_tree.selection_set(selected)
                self._peak_tree.focus(selected)
        self._page_label.configure(
            text=self._tr(
                "results_page_status",
                page=self._state.peak_page + 1,
                pages=page_count,
                count=total,
            )
        )
        self._previous_button.configure(
            state="normal" if self._state.peak_page > 0 else "disabled"
        )
        self._next_button.configure(
            state="normal" if self._state.peak_page + 1 < page_count else "disabled"
        )
        self._locate_button.configure(state="normal" if self._peak_tree.selection() else "disabled")

    def _peak_values(self, peak: ReflectionRecord) -> tuple[str, ...]:
        return (
            self._format_hkl(peak),
            self._format_number(peak.two_theta_deg, 4),
            self._format_number(peak.d_spacing_A, 5),
            self._format_number(peak.normalized_intensity, 2),
            self._format_number(peak.q_invA, 5),
            self._format_number(peak.young_modulus_hkl_normal_GPa, 2),
        )

    @staticmethod
    def _format_hkl(peak: ReflectionRecord) -> str:
        return f"({peak.h} {peak.k} {peak.l})"

    @staticmethod
    def _format_number(value: object, decimals: int) -> str:
        if value is None:
            return "—"
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return "—"
        if not math.isfinite(number):
            return "—"
        return f"{number:.{decimals}f}"

    def _render_diagnostics(self) -> None:
        records = self._result.diagnostics or ()
        children = self._diagnostic_tree.get_children("")
        if children:
            self._diagnostic_tree.delete(*children)
        indexes = filtered_diagnostic_indexes(records, self._state.diagnostic_filter)
        for index in indexes:
            record = records[index]
            level = record.level
            level_key = {
                "warning": "results_diag_warning",
                "error": "results_diag_error",
            }.get(level, "results_diag_info")
            stage = record.stage
            item = record.item
            source = " · ".join(part for part in (stage, item) if part)
            self._diagnostic_tree.insert(
                "", "end", iid=str(index),
                values=(self._tr(level_key), source or "—"),
            )
        if not indexes:
            self._diagnostic_empty.configure(text=self._tr("results_diag_empty"))
            if not self._diagnostic_empty.winfo_manager():
                self._diagnostic_empty.grid(row=1, column=0, sticky="ew", pady=8)
            self._set_diagnostic_details(self._tr("results_diag_select_hint"))
            return
        if self._diagnostic_empty.winfo_manager():
            self._diagnostic_empty.grid_remove()
        selected = self._state.selected_diagnostic_index
        if selected in indexes:
            iid = str(selected)
            self._diagnostic_tree.selection_set(iid)
            self._diagnostic_tree.focus(iid)
            self._show_diagnostic(records[selected])
        else:
            self._state.selected_diagnostic_index = None
            first = indexes[0]
            iid = str(first)
            self._diagnostic_tree.selection_set(iid)
            self._diagnostic_tree.focus(iid)
            self._state.selected_diagnostic_index = first
            self._show_diagnostic(records[first])

    def _set_diagnostic_filter_label(self) -> None:
        indexes = {"all": 0, "warning": 1, "error": 2}
        self._diagnostic_filter_combo.current(
            indexes.get(self._state.diagnostic_filter, 0)
        )

    def _set_diagnostic_details(self, message: str) -> None:
        self._diagnostic_details.configure(state="normal")
        self._diagnostic_details.delete("1.0", "end")
        self._diagnostic_details.insert("1.0", message)
        self._diagnostic_details.configure(state="disabled")

    def _show_diagnostic(self, diagnostic: DiagnosticRecord) -> None:
        stage = diagnostic.stage
        item = diagnostic.item
        message = diagnostic.message
        source = " · ".join(part for part in (stage, item) if part)
        details = f"{message}\n\n{source}" if source else message
        self._set_diagnostic_details(details or "—")

    def _schedule_plot(self, _event: object | None = None) -> None:
        if self._destroyed:
            return
        if self._draw_after_id is not None:
            try:
                self.after_cancel(self._draw_after_id)
            except tk.TclError:
                pass
        try:
            self._draw_after_id = self.after_idle(self._draw_pattern)
        except tk.TclError:
            self._draw_after_id = None

    def _profile_points(self, phase: PhaseAnalysis) -> tuple[list[tuple[float, float]], str]:
        x_values = phase.two_theta_grid
        y_values = phase.intensity_profile
        has_profile = len(x_values) > 0 and len(y_values) > 0
        if has_profile:
            cache_key = (id(phase), id(x_values), id(y_values), "profile")
            if cache_key != self._plot_cache_key:
                try:
                    self._plot_cache = pixel_bucket_envelope(
                        x_values, y_values, _PLOT_CACHE_PIXELS
                    )
                except (TypeError, ValueError):
                    self._plot_cache = []
                self._plot_cache_key = cache_key
            if self._plot_cache:
                return self._plot_cache, "profile"

        reflections = phase.reflections
        cache_key = (id(phase), id(reflections), id(reflections), "sticks")
        if cache_key != self._plot_cache_key:
            x_values = [peak.two_theta_deg for peak in reflections]
            y_values = [peak.normalized_intensity for peak in reflections]
            try:
                self._plot_cache = pixel_bucket_envelope(
                    x_values, y_values, _PLOT_CACHE_PIXELS
                )
            except (TypeError, ValueError):
                self._plot_cache = []
            self._plot_cache_key = cache_key
        return self._plot_cache, "sticks"

    def _draw_pattern(self) -> None:
        self._draw_after_id = None
        if self._destroyed:
            return
        canvas = self._canvas
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        analyses = self._analyses()
        if not analyses:
            canvas.create_text(
                width / 2, height / 2, text=self._tr("results_no_phases"),
                fill=MUTED, font=(self._font_family, 10),
            )
            return
        phase = analyses[min(max(0, self._state.phase_index), len(analyses) - 1)]
        points, plot_kind = self._profile_points(phase)
        if not points:
            canvas.create_text(
                width / 2, height / 2, text=self._tr("results_plot_empty"),
                fill=MUTED, font=(self._font_family, 10),
            )
            return

        left, right, top, bottom = 54, max(56, width - 16), 12, max(22, height - 46)
        plot_width = max(1, right - left)
        plot_height = max(1, bottom - top)
        x_min = min(point[0] for point in points)
        x_max = max(point[0] for point in points)
        x_span = x_max - x_min or 1.0
        for tick in range(5):
            y = bottom - plot_height * tick / 4
            canvas.create_line(left, y, right, y, fill=BORDER, dash=(2, 3))
            canvas.create_text(
                left - 8, y, text=str(tick * 25), anchor="e", fill=MUTED,
                font=(self._font_family, 8),
            )
        canvas.create_line(left, top, left, bottom, fill=MUTED)
        canvas.create_line(left, bottom, right, bottom, fill=MUTED)
        coordinates: list[float] = []
        for x_value, y_value in points:
            coordinates.extend(
                (
                    left + (x_value - x_min) / x_span * plot_width,
                    bottom - min(100.0, max(0.0, y_value)) / 100.0 * plot_height,
                )
            )
        if plot_kind == "profile" and len(coordinates) >= 4:
            canvas.create_line(*coordinates, fill=TEAL_DARK, width=2, capstyle="round")
        elif plot_kind == "sticks":
            for index in range(0, len(coordinates), 2):
                x, y = coordinates[index : index + 2]
                if y < bottom:
                    canvas.create_line(x, bottom, x, y, fill=TEAL_DARK, width=2)
        for tick in range(5):
            x_value = x_min + x_span * tick / 4
            x = left + plot_width * tick / 4
            canvas.create_line(x, bottom, x, bottom + 3, fill=MUTED)
            canvas.create_text(
                x, bottom + 6, text=f"{x_value:.1f}", anchor="n", fill=MUTED,
                font=(self._font_family, 8),
            )
        canvas.create_text(
            max(20, width / 2), height - 4, text=self._tr("results_axis_two_theta"),
            anchor="s", fill=TEXT, font=(self._font_family, 9, "bold"),
        )
        self._draw_selected_peak(canvas, phase, x_min, x_max, left, right, top, bottom)

    def _draw_selected_peak(
        self,
        canvas: object,
        phase: PhaseAnalysis,
        x_min: float,
        x_max: float,
        left: float,
        right: float,
        top: float,
        bottom: float,
    ) -> None:
        selected = self._state.selected_peak_index
        reflections = phase.reflections
        if selected is None or selected >= len(reflections):
            return
        peak = reflections[selected]
        peak_x = float(peak.two_theta_deg)
        if not math.isfinite(peak_x) or x_max <= x_min:
            return
        x = left + (peak_x - x_min) / (x_max - x_min) * (right - left)
        if x < left or x > right:
            return
        canvas.create_line(x, top, x, bottom, fill=WARNING, dash=(4, 3), width=2)
        canvas.create_text(
            min(right - 4, max(left + 4, x)), top + 2,
            text=f"{self._format_hkl(peak)} · {peak_x:.3f}°", anchor="n",
            fill=WARNING, font=(self._font_family, 9, "bold"),
        )

    def _on_phase_selected(self, _event: object | None = None) -> None:
        selected = self._phase_combo.current()
        if selected < 0 or selected == self._state.phase_index:
            return
        self._state.phase_index = selected
        self._state.peak_page = 0
        self._state.selected_peak_index = None
        self._render_selected_phase()

    def _sort_peaks(self, column: str) -> None:
        if column == self._state.peak_sort_column:
            self._state.peak_sort_descending = not self._state.peak_sort_descending
        else:
            self._state.peak_sort_column = column
            self._state.peak_sort_descending = False
        self._state.peak_page = 0
        self._state.selected_peak_index = None
        self._render_selected_phase()

    def _change_page(self, delta: int) -> None:
        if self._destroyed:
            return
        self._state.peak_page = max(0, self._state.peak_page + int(delta))
        self._state.selected_peak_index = None
        self._render_selected_phase()

    def _on_peak_selected(self, _event: object | None = None) -> None:
        selected = self._peak_tree.selection()
        try:
            self._state.selected_peak_index = int(selected[0]) if selected else None
        except (ValueError, TypeError):
            self._state.selected_peak_index = None
        self._locate_button.configure(state="normal" if selected else "disabled")
        self._schedule_plot()

    def _show_selected_peak(self, _event: object | None = None) -> str:
        if self._state.selected_peak_index is not None:
            self._notebook.select(self._pattern_tab)
            self._schedule_plot()
        return "break"

    def _on_diagnostic_filter_selected(self, _event: object | None = None) -> None:
        index = self._diagnostic_filter_combo.current()
        self._state.diagnostic_filter = ("all", "warning", "error")[index] if 0 <= index < 3 else "all"
        self._state.selected_diagnostic_index = None
        self._render_diagnostics()

    def _on_diagnostic_selected(self, _event: object | None = None) -> None:
        selected = self._diagnostic_tree.selection()
        try:
            index = int(selected[0]) if selected else None
        except (ValueError, TypeError):
            index = None
        self._state.selected_diagnostic_index = index
        diagnostics = self._result.diagnostics or ()
        diagnostic = diagnostics[index] if index is not None and index < len(diagnostics) else None
        if diagnostic is None:
            self._set_diagnostic_details(self._tr("results_diag_select_hint"))
        else:
            self._show_diagnostic(diagnostic)

    def _on_tab_changed(self, _event: object | None = None) -> None:
        try:
            if self._notebook.select() == str(self._pattern_tab):
                self._schedule_plot()
        except tk.TclError:
            return

    def destroy(self) -> None:
        if not self._destroyed:
            self._destroyed = True
            if self._draw_after_id is not None:
                try:
                    self.after_cancel(self._draw_after_id)
                except tk.TclError:
                    pass
                self._draw_after_id = None
            for widget, sequence, func_id in self._bindings:
                try:
                    widget.unbind(sequence, func_id)
                except tk.TclError:
                    pass
            self._bindings.clear()
        super().destroy()
