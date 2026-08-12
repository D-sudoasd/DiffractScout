import pytest

import diffractscout.gui as gui_module
from diffractscout.gui import analysis_settings_from_form, create_app, discovery_settings_from_form
from diffractscout.gui_i18n import REQUIRED_KEYS, STRINGS, assert_language_parity, t
from diffractscout.models import AnalysisSettings


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


def _create_test_app():
    try:
        return create_app()
    except RuntimeError as exc:
        if "Tkinter" in str(exc):
            pytest.skip("Tkinter unavailable")
        raise
    except Exception as exc:
        if gui_module.tk is not None and isinstance(exc, gui_module.tk.TclError):
            pytest.skip(f"Tk display unavailable: {exc}")
        raise


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


def test_i18n_required_keys_zh_en_parity() -> None:
    assert_language_parity()
    for key in REQUIRED_KEYS:
        assert key in STRINGS["zh"]
        assert key in STRINGS["en"]
        assert t("zh", key)
        assert t("en", key)
        assert t("zh", key) != key
        assert t("en", key) != key


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
