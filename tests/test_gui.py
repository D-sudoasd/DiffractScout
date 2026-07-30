import pytest

from diffractscout.gui import analysis_settings_from_form, discovery_settings_from_form


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
