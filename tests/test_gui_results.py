from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from diffractscout.gui_results import (
    ResultView,
    ResultViewState,
    filtered_diagnostic_indexes,
    paginate_indexes,
    pixel_bucket_envelope,
    result_counts,
    sort_peak_indexes,
)
from diffractscout.gui_i18n import t
from diffractscout.models import AnalysisSettings, DiagnosticRecord
from diffractscout.pipeline import analyze_cifs


def test_offline_pipeline_result_counts_and_missing_elasticity(
    demo_inputs, tmp_path
) -> None:
    result = analyze_cifs(
        [demo_inputs],
        tmp_path / "results",
        settings=AnalysisSettings(include_elasticity=False),
        include_excel=False,
    )

    counts = result_counts(result)
    assert counts.phases == 1
    assert counts.peaks == len(result.analyses[0].reflections) > 0
    assert counts.warnings == sum(item.level == "warning" for item in result.diagnostics)
    assert counts.errors == sum(item.level == "error" for item in result.diagnostics)
    assert result.analyses[0].elastic_tensor is None
    assert all(
        peak.young_modulus_hkl_normal_GPa is None
        for peak in result.analyses[0].reflections
    )
    assert ResultView._format_number(None, 2) == "—"
    assert ResultView._format_number(float("nan"), 2) == "—"

    phase_without_profile = replace(
        result.analyses[0],
        two_theta_grid=np.array([], dtype=float),
        intensity_profile=np.array([], dtype=float),
    )
    plot_cache = SimpleNamespace(_plot_cache_key=None, _plot_cache=[])
    stick_points, plot_kind = ResultView._profile_points(plot_cache, phase_without_profile)
    assert plot_kind == "sticks"
    assert stick_points
    assert max(intensity for _angle, intensity in stick_points) == 100.0


def test_counts_keep_zero_distinct_from_missing_data() -> None:
    empty_result = SimpleNamespace(analyses=[], diagnostics=[])
    missing_result = SimpleNamespace()

    assert result_counts(empty_result).phases == 0
    assert result_counts(empty_result).peaks == 0
    assert result_counts(empty_result).warnings == 0
    assert result_counts(empty_result).errors == 0
    assert result_counts(missing_result).phases is None
    assert result_counts(missing_result).peaks is None
    assert result_counts(missing_result).warnings is None
    assert result_counts(missing_result).errors is None


def test_pixel_envelope_is_bounded_and_keeps_a_narrow_peak_and_local_minimum() -> None:
    x = np.linspace(10.0, 80.0, 20_001)
    y = np.zeros_like(x)
    spike_index = 10_113
    minimum_index = 10_151
    y[spike_index] = 50.0
    y[minimum_index] = -2.0

    points = pixel_bucket_envelope(x, y, pixel_width=48)

    assert len(points) <= 2 * 48 + 2
    assert (float(x[spike_index]), 100.0) in points
    assert any(point[0] == float(x[minimum_index]) and point[1] == -4.0 for point in points)


def test_peak_sorting_and_pagination_preserve_all_numeric_rows() -> None:
    reflections = [
        SimpleNamespace(two_theta_deg=32.5, hkl=(2, 0, 0)),
        SimpleNamespace(two_theta_deg=14.0, hkl=(1, 1, 1)),
        SimpleNamespace(two_theta_deg=None, hkl=(3, 1, 1)),
    ]
    ascending = sort_peak_indexes(reflections, "two_theta_deg")
    descending = sort_peak_indexes(reflections, "two_theta_deg", descending=True)
    assert ascending == [1, 0, 2]
    assert descending == [0, 1, 2]
    assert sort_peak_indexes(reflections, "hkl") == [1, 0, 2]
    assert sort_peak_indexes(reflections, "hkl", descending=True) == [2, 0, 1]

    indexes = list(range(503))
    page_one, page, pages = paginate_indexes(indexes, 0, page_size=250)
    page_two, _, _ = paginate_indexes(indexes, 1, page_size=250)
    page_three, _, _ = paginate_indexes(indexes, 2, page_size=250)
    assert (page, pages) == (0, 3)
    assert [len(page_one), len(page_two), len(page_three)] == [250, 250, 3]
    assert page_one + page_two + page_three == indexes
    assert paginate_indexes(indexes, 999, page_size=250)[1] == 2


def test_diagnostic_filter_uses_levels_and_keeps_full_records() -> None:
    diagnostics = [
        DiagnosticRecord("analysis", "sample-a", "warning", "warning details"),
        DiagnosticRecord("analysis", "sample-b", "error", "error details"),
        DiagnosticRecord("export", "bundle", "info", "export details"),
    ]

    assert filtered_diagnostic_indexes(diagnostics) == [0, 1, 2]
    assert filtered_diagnostic_indexes(diagnostics, "warning") == [0]
    assert filtered_diagnostic_indexes(diagnostics, "error") == [1]
    assert diagnostics[1].message == "error details"


def test_language_refresh_does_not_reset_navigation_state() -> None:
    class LabelStub:
        def configure(self, **_options) -> None:
            return None

    view = ResultView.__new__(ResultView)
    state = ResultViewState(
        phase_index=2,
        peak_page=3,
        peak_sort_column="q_invA",
        peak_sort_descending=True,
        selected_peak_index=881,
        diagnostic_filter="error",
        selected_diagnostic_index=4,
    )
    view._state = state
    view._destroyed = False
    view._result = object()
    view._translate = lambda key, **_fmt: f"translated:{key}"
    view._heading = LabelStub()
    view.help = SimpleNamespace(hide=lambda: None)
    view._apply_static_translations = lambda: None
    view._render_result = lambda: None
    before = ResultViewState(**vars(state))

    ResultView.refresh_language(view)

    assert view._state == before


def test_real_tk_layout_and_first_result_language(demo_inputs, tmp_path) -> None:
    tkinter = pytest.importorskip("tkinter")
    from tkinter import ttk

    from diffractscout.gui_results import ResultView
    from diffractscout.gui_theme import configure_styles

    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")

    result = analyze_cifs(
        [demo_inputs],
        tmp_path / "ui-results",
        settings=AnalysisSettings(include_elasticity=False),
        include_excel=False,
    )
    long_message = "Complete diagnostic detail. " * 80
    result = replace(
        result,
        diagnostics=[DiagnosticRecord("analysis", "fixture", "error", long_message)],
    )
    language = {"value": "en"}

    def translate(key: str, **fmt: object) -> str:
        return t(language["value"], key, **fmt)

    try:
        configure_styles(root)
        for width, height in ((900, 640), (1200, 820)):
            root.geometry(f"{width}x{height}")
            top = ttk.Frame(root, height=180)
            top.pack(side="top", fill="x")
            top.pack_propagate(False)
            bottom = ttk.Frame(root, height=90)
            bottom.pack(side="bottom", fill="x")
            bottom.pack_propagate(False)
            view = ResultView(root, translate=translate)
            view.pack(fill="both", expand=True)

            # The user can switch language before the first analysis finishes.
            view.refresh_language()
            view.set_result(result)
            root.update()
            assert view._summary_cards["phases"][1].cget("text") == t("en", "results_phases")
            assert view._notebook.tab(view._pattern_tab, "text") == t("en", "results_tab_pattern")
            assert view._previous_button.cget("text") == t("en", "results_previous_page")
            assert "λ = " in view._plot_note.cget("text")
            assert "Cu Kα" in view._plot_note.cget("text")
            assert "source_preset:" not in view._plot_note.cget("text")

            view._notebook.select(view._pattern_tab)
            root.update()
            assert view._canvas.winfo_height() >= 130
            window_right = root.winfo_rootx() + root.winfo_width()
            assert view._plot_note.winfo_rootx() + view._plot_note.winfo_width() <= window_right + 1

            view._notebook.select(view._peaks_tab)
            root.update()
            assert view._peak_tree.winfo_height() >= 160
            assert view._peak_tree.get_children("")
            assert view._peak_tree.winfo_rootx() + view._peak_tree.winfo_width() <= window_right + 1
            assert view._locate_button.instate(("disabled",))
            first_peak = view._peak_tree.get_children("")[0]
            view._peak_tree.selection_set(first_peak)
            view._peak_tree.event_generate("<<TreeviewSelect>>")
            root.update()
            assert view._locate_button.instate(("!disabled",))
            view._locate_button.invoke()
            root.update()
            assert view._notebook.select() == str(view._pattern_tab)
            assert view._state.selected_peak_index == int(first_peak)

            view._state.diagnostic_filter = "error"
            view._state.selected_diagnostic_index = 0
            view._render_diagnostics()
            view._notebook.select(view._diagnostics_tab)
            root.update()
            displayed = view._diagnostic_details.get("1.0", "end-1c")
            assert displayed == f"{long_message}\n\nanalysis · fixture"
            assert view._diagnostic_details_scroll.winfo_ismapped()
            assert view._diagnostic_details.winfo_height() >= 40

            language["value"] = "zh"
            view.refresh_language()
            assert view._notebook.tab(view._pattern_tab, "text") == t("zh", "results_tab_pattern")
            language["value"] = "en"
            view.refresh_language()
            assert view._notebook.tab(view._pattern_tab, "text") == t("en", "results_tab_pattern")
            assert view._state.selected_diagnostic_index == 0

            view.set_result(None)
            assert view._empty_title.cget("text") == t("en", "results_empty_title")
            no_phase_result = replace(result, analyses=[])
            view.set_result(no_phase_result)
            assert view._status.cget("text") == t("en", "results_status_empty")
            assert view._notebook.select() == str(view._diagnostics_tab)
            assert view._phase_combo.get() == t("en", "results_no_phases_title")
            view.destroy()
            root.update_idletasks()
            for widget in (top, bottom):
                widget.destroy()
    finally:
        root.destroy()
