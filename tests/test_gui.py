import pytest

from diffractscout.gui import analysis_settings_from_form, discovery_settings_from_form
from diffractscout.gui_i18n import REQUIRED_KEYS, STRINGS, assert_language_parity, t


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


def test_discovery_form_rejects_zero_limit() -> None:
    settings = discovery_settings_from_form(
        {"mode": "possible_phases", "max_total": "0"}
    )
    assert settings.max_total == 0
    # Domain validation occurs before provider access in search_candidates.


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
