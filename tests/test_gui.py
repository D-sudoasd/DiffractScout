from pathlib import Path

import hashlib
import json

import pytest

import diffractscout.gui as gui_module
from diffractscout.gui import (
    analysis_settings_from_form,
    canonical_input_identity,
    create_app,
    discovery_settings_from_form,
)
from diffractscout.gui_i18n import REQUIRED_KEYS, STRINGS, assert_language_parity, t
from diffractscout.models import AnalysisSettings
from diffractscout.diffraction import ENERGY_WAVELENGTH_KEV_A, resolve_wavelength
from diffractscout.validation import verify_bundle


def test_analysis_form_builds_energy_settings() -> None:
    settings = analysis_settings_from_form(
        {
            "input_mode": "energy",
            "source_preset": "Cu Ka",
            "radiation_value": "83",
            "two_theta_min": "3",
            "two_theta_max": "100",
            "step": "0.02",
            "fwhm": "0.1",
            "eta": "0.4",
            "include_elasticity": False,
            "max_profile_points": "200000",
            "max_reflection_estimate": "300000",
        }
    )
    assert settings.energy_keV == 83
    assert settings.wavelength_A is None
    assert not settings.include_elasticity


def test_analysis_form_includes_d_min_and_profile_model() -> None:
    settings = analysis_settings_from_form(
        {
            "input_mode": "source",
            "source_preset": "Cu Ka",
            "radiation_value": "",
            "two_theta_min": "5",
            "two_theta_max": "120",
            "step": "0.02",
            "fwhm": "0.15",
            "eta": "0.5",
            "max_profile_points": "1000000",
            "max_reflection_estimate": "2000000",
            "d_min_A": "0.8",
            "d_max_A": "4.0",
            "profile_model": "gaussian",
            "pattern_axis": "q",
            "include_figures": True,
            "export_lab_views": False,
            "include_patterns": False,
        }
    )
    assert settings.d_min_A == pytest.approx(0.8)
    assert settings.d_max_A == pytest.approx(4.0)
    assert settings.profile_model == "gaussian"
    assert settings.pattern_axis == "q"
    assert settings.include_figures is True
    assert settings.export_lab_views is False
    assert settings.include_patterns is False


def test_analysis_form_ignores_stale_non_numeric_source_radiation() -> None:
    """A built-in source does not consume the disabled custom-value field."""

    settings = analysis_settings_from_form(
        {
            "input_mode": "source",
            "source_preset": "Cu Ka",
            "radiation_value": "not-a-number",
            "two_theta_min": "5",
            "two_theta_max": "120",
            "step": "0.02",
            "fwhm": "0.15",
            "eta": "0.5",
            "max_profile_points": "1000000",
            "max_reflection_estimate": "2000000",
        }
    )

    assert settings.input_mode == "source"
    assert settings.source_preset == "Cu Ka"
    assert settings.wavelength_A is None
    assert settings.energy_keV is None


def test_gui_radiation_transitions_keep_units_and_resolved_physics() -> None:
    app = _create_test_app()
    try:
        app.input_mode.set("energy")
        app.update_idletasks()
        energy_value = float(app.radiation_value.get())
        energy_settings = app._form_analysis_settings()
        wavelength, energy, _source = resolve_wavelength(energy_settings)
        assert energy_settings.input_mode == "energy"
        assert energy == pytest.approx(ENERGY_WAVELENGTH_KEV_A / 1.5406)
        assert wavelength == pytest.approx(1.5406)
        assert "keV" in app._radiation_value_labels[0].cget("text")
        assert energy_value == pytest.approx(ENERGY_WAVELENGTH_KEV_A / 1.5406)

        app.radiation_value.set("20")
        app.input_mode.set("wavelength")
        app.update_idletasks()
        assert float(app.radiation_value.get()) == pytest.approx(ENERGY_WAVELENGTH_KEV_A / 20.0)
        assert "Å" in app._radiation_value_labels[0].cget("text")

        app.energy_shortcut.set("83 keV")
        app.update_idletasks()
        assert app.input_mode.get() == "energy"
        assert app.radiation_value.get() == "83"
        assert "keV" in app._radiation_value_labels[0].cget("text")

        app.energy_shortcut.set("Custom")
        app.update_idletasks()
        assert app.input_mode.get() == "source"
        assert app.source_preset.get() == "Custom"
        assert app.radiation_value.get() == ""
        assert "Å" in app._radiation_value_labels[0].cget("text")
        with pytest.raises(ValueError, match="finite positive wavelength_A"):
            app._form_analysis_settings()
    finally:
        app.destroy()


def test_gui_output_dependencies_preserve_lab_and_cij_state() -> None:
    app = _create_test_app()
    try:
        app.export_lab_views.set(True)
        app.include_excel.set(False)
        app.update_idletasks()
        assert not app.export_lab_views.get()
        assert str(app.chk_lab_views.cget("state")) == "disabled"
        assert str(app.chk_lab_views_mp.cget("state")) == "disabled"
        assert app._form_analysis_settings().export_lab_views is False

        app.include_excel.set(True)
        app.update_idletasks()
        assert app.export_lab_views.get()
        assert str(app.chk_lab_views.cget("state")) == "normal"
        assert str(app.chk_lab_views_mp.cget("state")) == "normal"

        marker = object()
        app.elastic_overrides["sample"] = marker
        app.include_elasticity.set(False)
        app.update_idletasks()
        assert all(str(widget.cget("state")) == "disabled" for widget in app._cij_widgets)
        assert app.elastic_overrides["sample"] is marker
        app.include_elasticity.set(True)
        app.update_idletasks()
        assert all(str(widget.cget("state")) == "normal" for widget in app._cij_widgets)
        assert app.elastic_overrides["sample"] is marker
    finally:
        app.destroy()


def test_gui_open_result_survives_failed_retry_only_when_bundle_exists(tmp_path) -> None:
    class Widget:
        def __init__(self):
            self.states = []

        def configure(self, **kwargs):
            self.states.append(kwargs)

    class Progress:
        def stop(self):
            return None

    good = tmp_path / "good"
    good.mkdir()
    payload = good / "payload.txt"
    payload.write_text("valid committed bundle target\n", encoding="utf-8")
    (good / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "diffractscout_bundle_manifest_v1",
                "files": [
                    {
                        "path": "payload.txt",
                        "size_bytes": payload.stat().st_size,
                        "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert verify_bundle(good)["ok"]
    controller = type("Controller", (), {})()
    controller.last_output = good
    controller.running = True
    controller.open_button = Widget()
    controller.progress = Progress()
    controller._run_buttons = []
    gui_module.DiffractScoutApp._update_open_button_state(controller)
    assert controller.open_button.states[-1]["state"] == "disabled"

    controller.running = False
    gui_module.DiffractScoutApp._finish_task(controller)
    assert controller.open_button.states[-1]["state"] == "normal"

    (good / "manifest.json").unlink()
    gui_module.DiffractScoutApp._finish_task(controller)
    assert controller.open_button.states[-1]["state"] == "disabled"


def test_analysis_form_rejects_unknown_profile_model() -> None:
    with pytest.raises(ValueError, match="Profile model"):
        analysis_settings_from_form(
            {
                "input_mode": "source",
                "source_preset": "Cu Ka",
                "two_theta_min": "5",
                "two_theta_max": "120",
                "step": "0.02",
                "fwhm": "0.15",
                "eta": "0.5",
                "max_profile_points": "1000000",
                "max_reflection_estimate": "2000000",
                "profile_model": "not_a_model",
            }
        )


def _is_expected_gui_unavailable(exc: BaseException) -> bool:
    if isinstance(exc, RuntimeError):
        return str(exc) == "Tkinter is unavailable in this Python installation."
    tcl_error = getattr(gui_module.tk, "TclError", None)
    if tcl_error is None or not isinstance(exc, tcl_error):
        return False
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "no display name and no $display environment variable",
            "couldn't connect to display",
            "can't open display",
            "unable to connect to display",
        )
    )


def _create_test_app():
    try:
        return create_app()
    except RuntimeError as exc:
        if _is_expected_gui_unavailable(exc):
            pytest.skip("Tkinter unavailable")
        raise
    except Exception as exc:
        if _is_expected_gui_unavailable(exc):
            pytest.skip(f"Tk display unavailable: {exc}")
        raise


def test_gui_main_converts_constructor_failure_to_actionable_exit(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def fail() -> object:
        if gui_module.tk is not None:
            raise gui_module.tk.TclError(
                "no display name and no $DISPLAY environment variable"
            )
        raise RuntimeError("Tkinter is unavailable in this Python installation.")

    monkeypatch.setattr(gui_module, "create_app", fail)
    assert gui_module.main() == 2
    error = capsys.readouterr().err
    assert error.startswith("ERROR: Could not start the DiffractScout GUI:")
    assert "Tk support" in error
    assert "graphical display" in error
    assert "Traceback" not in error


@pytest.mark.parametrize(
    "message",
    (
        "can't find a usable tk.tcl in the following directories",
        'can\'t read "clamTheme.tcl": no such file or directory',
        'couldn\'t read "scrlbar.tcl": no such file or directory',
        'can\'t find "ttk/fonts.tcl"',
        'couldn\'t read "ttk/vistaTheme.tcl": no such file or directory',
    ),
)
def test_gui_main_converts_known_tcl_resource_failure_to_actionable_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    message: str,
) -> None:
    if gui_module.tk is None:
        pytest.skip("Tkinter unavailable")

    def fail() -> object:
        raise gui_module.tk.TclError(message)

    monkeypatch.setattr(gui_module, "create_app", fail)
    assert gui_module.main() == 2
    error = capsys.readouterr().err
    assert "Tcl/Tk" in error
    assert ".tcl resource files" in error
    assert "Traceback" not in error


def test_gui_main_does_not_swallow_mainloop_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenApp:
        def mainloop(self) -> None:
            raise RuntimeError("worker failure")

    monkeypatch.setattr(gui_module, "create_app", lambda: BrokenApp())
    with pytest.raises(RuntimeError, match="worker failure"):
        gui_module.main()


def test_gui_main_reraises_unexpected_tcl_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if gui_module.tk is None:
        pytest.skip("Tkinter unavailable")

    def fail() -> object:
        raise gui_module.tk.TclError("widget setup failed")

    monkeypatch.setattr(gui_module, "create_app", fail)
    with pytest.raises(gui_module.tk.TclError, match="widget setup failed"):
        gui_module.main()


def test_gui_setup_does_not_skip_unexpected_tcl_or_resource_errors() -> None:
    if gui_module.tk is None:
        pytest.skip("Tkinter unavailable")
    for message in ("widget setup failed", "can't find a usable tk.tcl", "ttk/cursors.tcl"):
        error = gui_module.tk.TclError(message)
        assert not _is_expected_gui_unavailable(error)


def test_gui_main_reraises_unexpected_constructor_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> object:
        raise RuntimeError("unexpected GUI construction failure")

    monkeypatch.setattr(gui_module, "create_app", fail)
    with pytest.raises(RuntimeError, match="unexpected GUI construction failure"):
        gui_module.main()


def test_discovery_form_rejects_zero_limit() -> None:
    with pytest.raises(ValueError, match="max_total"):
        discovery_settings_from_form(
            {"mode": "possible_phases", "max_total": "0"}
        )


def test_analysis_form_rejects_non_numeric_value() -> None:
    with pytest.raises(ValueError, match="Profile step"):
        analysis_settings_from_form(
            {
                "input_mode": "source",
                "source_preset": "Cu Ka",
                "radiation_value": "",
                "two_theta_min": "5",
                "two_theta_max": "120",
                "step": "many",
                "fwhm": "0.15",
                "eta": "0.5",
                "max_profile_points": "1000000",
                "max_reflection_estimate": "2000000",
            }
        )


def test_canonical_input_identity_distinguishes_same_named_files(tmp_path) -> None:
    first = tmp_path / "first" / "sample.cif"
    second = tmp_path / "second" / "sample.cif"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("data_first\n", encoding="utf-8")
    second.write_text("data_second\n", encoding="utf-8")

    first_key = canonical_input_identity(first)
    second_key = canonical_input_identity(second)
    assert first_key == str(first.resolve())
    assert second_key == str(second.resolve())
    assert first_key != second_key


def test_clear_cij_does_not_wipe_overrides_for_selected_folder(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "cifs"
    folder.mkdir()
    other_identity = str((tmp_path / "other.cif").resolve())

    class InputList:
        selection = (0,)

        def curselection(self):
            return self.selection

    controller = type("Controller", (), {})()
    controller.input_list = InputList()
    controller.local_inputs = [folder]
    controller.elastic_overrides = {other_identity: object()}
    controller._selected_input_paths = gui_module.DiffractScoutApp._selected_input_paths.__get__(controller)
    controller._t = lambda key: key
    controller._refresh_cij_status = lambda: None
    warnings: list[tuple[object, ...]] = []
    monkeypatch.setattr(gui_module.messagebox, "showwarning", lambda *args: warnings.append(args))

    gui_module.DiffractScoutApp._clear_cij_override(controller)

    assert controller.elastic_overrides == {other_identity: controller.elastic_overrides[other_identity]}
    assert warnings == [("err_cij_apply", "err_cij_select")]

    controller.input_list.selection = ()
    gui_module.DiffractScoutApp._clear_cij_override(controller)
    assert controller.elastic_overrides == {}


def test_preview_workbook_is_copied_outside_bundle(tmp_path, monkeypatch) -> None:
    """Opening a workbook must not make Excel lock files part of the bundle."""

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    workbook = bundle / "results.xlsx"
    workbook.write_bytes(b"xlsx placeholder")
    controller = type("Controller", (), {"_preview_dirs": []})()

    opened: list[str] = []
    monkeypatch.setattr(gui_module, "open_path", lambda path: opened.append(str(path)))
    preview = gui_module.DiffractScoutApp._preview_workbook(controller, workbook)

    assert preview.is_file()
    assert preview.parent != workbook.parent
    assert preview.read_bytes() == workbook.read_bytes()
    assert not list(bundle.glob("~$*"))
    gui_module.DiffractScoutApp._cleanup_preview_dirs(controller)
    assert not preview.parent.exists()


def test_preview_cleanup_retains_busy_directory_for_retry(tmp_path, monkeypatch) -> None:
    preview_dir = tmp_path / "preview"
    preview_dir.mkdir()
    controller = type("Controller", (), {"_preview_dirs": [preview_dir]})()
    real_rmtree = gui_module.shutil.rmtree
    calls: list[Path] = []

    def fail_once(path, *args, **kwargs):
        calls.append(Path(path))
        if len(calls) == 1:
            raise OSError("preview is still open")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(gui_module.shutil, "rmtree", fail_once)
    gui_module.DiffractScoutApp._cleanup_preview_dirs(controller)
    assert controller._preview_dirs == [preview_dir]
    assert preview_dir.is_dir()

    gui_module.DiffractScoutApp._cleanup_preview_dirs(controller)
    assert controller._preview_dirs == []
    assert not preview_dir.exists()


def test_i18n_required_keys_zh_en_parity() -> None:
    assert_language_parity()
    for key in REQUIRED_KEYS:
        assert key in STRINGS["zh"]
        assert key in STRINGS["en"]
        assert t("zh", key)
        assert t("en", key)
        assert t("zh", key) != key
        assert t("en", key) != key
    assert "CSV/Excel" in t("zh", "pattern_axis")
    assert "CSV/Excel" in t("en", "pattern_axis")
    assert "2θ" in t("zh", "include_figures")
    assert "2theta" in t("en", "include_figures")
    assert t("zh", "radiation_value_A") == "辐射值 (Å)"
    assert t("en", "radiation_value_A") == "Radiation value (Å)"
    assert t("zh", "radiation_value_keV") == "辐射值 (keV)"
    assert t("en", "radiation_value_keV") == "Radiation value (keV)"
    assert "eV/atom" in t("zh", "help_e_hull") and "0.05" in t("en", "help_e_hull")
    assert "GPa" in t("zh", "help_cij") and "GPa" in t("en", "help_cij")
    assert "q=2π/d" in t("zh", "help_pattern_axis") and "g=1/d" in t("en", "help_pattern_axis")


def _validation_controller(lang: str):
    controller = type("ValidationController", (), {})()
    controller.lang = lang
    controller._t = lambda key, **fmt: t(controller.lang, key, **fmt)
    return controller


def test_validation_message_localizes_known_range_in_zh_and_en() -> None:
    error = ValueError("2theta range must satisfy 0 <= minimum < maximum <= 180 degrees.")
    zh = gui_module.DiffractScoutApp._validation_message(_validation_controller("zh"), error)
    en = gui_module.DiffractScoutApp._validation_message(_validation_controller("en"), error)

    assert "2theta range" not in zh.lower()
    assert "范围" in zh
    assert "2θ range" in en
    assert "minimum" in en and "maximum" in en


def test_validation_message_keeps_unknown_detail_with_localized_fallback() -> None:
    detail = "new backend invariant 42"
    for lang in ("zh", "en"):
        message = gui_module.DiffractScoutApp._validation_message(
            _validation_controller(lang), ValueError(detail)
        )
        assert detail in message
        assert message == t(lang, "validation_generic", error=detail)


def test_gui_layout_has_scrollable_regions_and_run_buttons() -> None:
    """Smoke: app builds with scroll helpers and always-visible run buttons."""

    app = _create_test_app()
    try:
        app.geometry("960x640")
        app.update_idletasks()
        assert hasattr(app, "_main_paned")
        assert getattr(app, "_scroll_canvases", None)
        assert len(app._scroll_canvases) >= 2
        assert len(app._run_buttons) >= 2
        for button in app._run_buttons:
            assert str(button.winfo_manager()) in {"pack", "grid", "place"}
            # Footer-pinned buttons should report a positive height after layout.
            assert int(button.winfo_reqheight()) > 0
    finally:
        app.destroy()


def test_scrollable_focus_reveals_focused_descendant() -> None:
    app = _create_test_app()
    try:
        app.geometry("900x640")
        app.update_idletasks()
        app.update()
        canvas = app._local_left_scroll_canvas
        canvas.yview_moveto(0.0)
        app.update_idletasks()
        before = canvas.yview()
        app.local_output_entry.focus_force()
        app.update_idletasks()
        app.update()
        after = canvas.yview()
        assert after[0] > before[0]
        canvas_top = canvas.winfo_rooty()
        canvas_bottom = canvas_top + canvas.winfo_height()
        entry_top = app.local_output_entry.winfo_rooty()
        entry_bottom = entry_top + app.local_output_entry.winfo_height()
        assert canvas_top <= entry_top
        assert entry_bottom <= canvas_bottom
    finally:
        app.destroy()


def test_default_sash_waits_for_configure_when_geometry_is_invalid(monkeypatch) -> None:
    app = _create_test_app()
    try:
        app._cancel_after_id("_sash_after_id")
        app._sash_initialized = False
        monkeypatch.setattr(app._main_paned, "winfo_height", lambda: 0)
        app._set_default_sash()
        assert app._sash_after_id is None
        assert not app._sash_initialized

        monkeypatch.undo()
        app._schedule_default_sash()
        assert app._sash_after_id is not None
        app.update()
        assert app._sash_initialized
        assert app._sash_after_id is None
    finally:
        app.destroy()


def test_default_sash_is_initialized_once_and_not_reset(monkeypatch) -> None:
    app = _create_test_app()
    try:
        app.geometry("900x640")
        app.update_idletasks()
        app.update()
        assert app._sash_initialized
        calls = []
        sashpos = app._main_paned.sashpos

        def track_sashpos(index, position=None):
            if position is not None:
                calls.append((index, position))
            return sashpos(index, position) if position is not None else sashpos(index)

        monkeypatch.setattr(app._main_paned, "sashpos", track_sashpos)
        app._schedule_default_sash()
        app.update()
        assert app._sash_after_id is None
        assert calls == []
    finally:
        app.destroy()


def test_default_sash_callback_is_cancelled_on_destroy() -> None:
    app = _create_test_app()
    try:
        assert app._sash_after_id is not None
    finally:
        app.destroy()
    assert app._sash_after_id is None


@pytest.mark.parametrize("geometry", ["900x640", "1200x820"])
def test_scrollable_focus_bindings_are_idempotent_and_cover_all_tabs(geometry: str) -> None:
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

    def descendants(widget):
        yield widget
        for child in widget.winfo_children():
            yield from descendants(child)

    def inside(widget, canvas) -> bool:
        top = canvas.winfo_rooty()
        bottom = top + canvas.winfo_height()
        widget_top = widget.winfo_rooty()
        return top <= widget_top and widget_top + max(widget.winfo_height(), 1) <= bottom

    app = _create_test_app()
    try:
        app.geometry(geometry)
        app.update_idletasks()
        app.update()
        for tab, first_canvas in ((0, 0), (1, 2)):
            app.notebook.select(tab)
            app.update_idletasks()
            app.update()
            for index in range(first_canvas, first_canvas + 2):
                canvas = app._scroll_canvases[index]
                interior = app._scroll_interiors[index]
                targets = [
                    widget
                    for widget in descendants(interior)
                    if widget is not interior
                    and widget.winfo_ismapped()
                    and widget.winfo_class() in focusable_classes
                    and widget.winfo_height() > 0
                ]
                bindings = app._scroll_focus_bindings[str(canvas)]
                assert len(bindings) == len(targets)
                for _ in range(3):
                    interior.event_generate("<Map>")
                    app.update_idletasks()
                    app.update()
                assert len(bindings) == len(targets)
                for widget in targets:
                    assert widget.bind("<FocusIn>").count("_focus_into_view") == 1
                    if widget.winfo_class() not in {"Text", "TCombobox", "Listbox", "Spinbox"}:
                        assert widget.bind("<MouseWheel>").count("_on_wheel") == 1
                        assert widget.bind("<Button-4>").count("_on_wheel") == 1
                        assert widget.bind("<Button-5>").count("_on_wheel") == 1
                    widget.focus_force()
                    app.update_idletasks()
                    app.update()
                    assert inside(widget, canvas), (str(widget), index, canvas.yview())

        # The outer form must not steal native wheel ownership from these
        # editing controls while focus bindings are installed.
        assert "_on_wheel" not in app.cij_paste.bind("<MouseWheel>")
        combobox = next(
            widget
            for widget in descendants(app._scroll_interiors[1])
            if widget.winfo_class() == "TCombobox"
        )
        assert "_on_wheel" not in combobox.bind("<MouseWheel>")
    finally:
        app.destroy()


@pytest.mark.parametrize("lang", ["zh", "en"])
@pytest.mark.parametrize("geometry", ["900x640", "1200x820"])
def test_action_button_geometry_has_no_clipped_glyph_area(geometry: str, lang: str) -> None:
    app = _create_test_app()
    try:
        app.geometry(geometry)
        app.update_idletasks()
        app.update()
        app._set_language(lang)
        app.update_idletasks()
        app.update()
        buttons = [app.open_button, app.btn_apply_cubic]
        buttons.extend(button for button in app._run_buttons if button.winfo_ismapped())
        for button in buttons:
            assert button.winfo_width() >= button.winfo_reqwidth(), str(button)
            assert button.winfo_height() >= button.winfo_reqheight(), str(button)
    finally:
        app.destroy()


def test_sequential_create_destroy_has_no_stale_tk_callbacks(capsys) -> None:
    first = _create_test_app()
    first.geometry("900x640")
    first.update_idletasks()
    first.update()
    first.destroy()

    second = _create_test_app()
    try:
        second.geometry("1200x820")
        second.update_idletasks()
        second.update()
    finally:
        second.destroy()

    captured = capsys.readouterr()
    assert "invalid command name" not in captured.err


@pytest.mark.parametrize("geometry", ["1352x1008", "900x640"])
def test_local_left_form_controls_are_reachable_after_scroll(geometry: str) -> None:
    """The local input list must not push output/CTA controls off the form."""

    app = _create_test_app()
    try:
        app.geometry(geometry)
        app.update_idletasks()
        app.update()
        canvas = app._local_left_scroll_canvas
        assert canvas.winfo_height() > 0
        assert canvas.bbox("all") is not None
        before = canvas.yview()
        canvas_top = canvas.winfo_rooty()
        canvas_bottom = canvas_top + canvas.winfo_height()
        before_overwrite = app.chk_overwrite_local.winfo_rooty()
        canvas.yview_moveto(1.0)
        app.update_idletasks()
        after = canvas.yview()
        if before[1] < 1.0:
            assert after[0] > before[0]
            assert before_overwrite >= canvas_bottom
            assert canvas_top <= app.chk_overwrite_local.winfo_rooty() < canvas_bottom
        for widget in (app.local_output_entry, app.chk_recursive, app.chk_overwrite_local):
            assert widget.winfo_height() > 0
            assert widget.winfo_ismapped()
    finally:
        app.destroy()


def test_local_worker_uses_ui_state_snapshot(tmp_path, monkeypatch) -> None:
    """Worker options are frozen without needing a live Tk display."""

    if not hasattr(gui_module.DiffractScoutApp, "_run_local"):
        pytest.skip("Tkinter unavailable")

    class Variable:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    class Controller:
        pass

    controller = Controller()
    sentinel = object()
    observed: dict[str, object] = {}
    scheduled: dict[str, object] = {}

    def fake_analyze(inputs, output, **kwargs):
        observed.update({"inputs": inputs, "output": output, **kwargs})
        return sentinel

    monkeypatch.setattr(gui_module, "analyze_cifs", fake_analyze)
    controller.running = False
    controller.local_inputs = [tmp_path / "input.cif"]
    controller.local_output = Variable(str(tmp_path / "bundle"))
    controller.elastic_overrides = {}
    controller.local_recursive = Variable(True)
    controller.include_excel = Variable(False)
    controller.overwrite = Variable(False)
    controller._form_analysis_settings = lambda: AnalysisSettings()
    controller._start_task = lambda label, function: scheduled.update(
        {"label": label, "function": function}
    )

    gui_module.DiffractScoutApp._run_local(controller)
    function = scheduled["function"]
    controller.local_recursive.set(False)
    controller.include_excel.set(True)
    controller.overwrite.set(True)

    assert callable(function)
    assert function() is sentinel
    assert observed["recursive"] is True
    assert observed["include_excel"] is False
    assert observed["overwrite"] is False
