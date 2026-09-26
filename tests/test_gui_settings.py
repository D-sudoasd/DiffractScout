from __future__ import annotations

import json
from pathlib import Path

import pytest

from diffractscout.gui_settings import load_analysis_preset, save_analysis_preset


def _form_values() -> dict[str, object]:
    return {
        "input_mode": "source",
        "source_preset": "Cu Ka",
        "radiation_value": "stale disabled text",
        "two_theta_min": "5",
        "two_theta_max": "120",
        "step": "0.02",
        "fwhm": "0.15",
        "eta": "0.5",
        "d_min_A": "0.8",
        "d_max_A": "4.0",
        "profile_model": "pseudo_voigt",
        "pattern_axis": "q",
        "max_profile_points": "1000000",
        "max_reflection_estimate": "2000000",
        "include_excel": True,
        "include_elasticity": False,
        "export_lab_views": True,
        "include_patterns": False,
        "include_figures": True,
        "local_recursive": False,
    }


def _read_document(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_analysis_preset_round_trip_is_versioned_and_gui_ready(tmp_path: Path) -> None:
    target = tmp_path / "presets" / "local-analysis.json"

    saved_path = save_analysis_preset(target, _form_values())
    document = _read_document(target)
    loaded = load_analysis_preset(target)

    assert saved_path == target
    assert document["schema"] == "diffractscout_analysis_preset"
    assert document["version"] == 1
    saved_values = document["values"]
    assert isinstance(saved_values, dict)
    assert saved_values["radiation_value"] is None  # Inactive built-in source field is discarded.
    assert saved_values["d_min_A"] == pytest.approx(0.8)
    assert saved_values["include_elasticity"] is False
    assert loaded["radiation_value"] == ""
    assert loaded["d_min_A"] == pytest.approx(0.8)
    assert loaded["d_max_A"] == pytest.approx(4.0)
    assert loaded["max_profile_points"] == 1_000_000
    assert loaded["max_reflection_estimate"] == 2_000_000
    assert loaded["pattern_axis"] == "q"
    assert loaded["include_excel"] is True
    assert loaded["export_lab_views"] is True
    assert loaded["local_recursive"] is False


def test_analysis_preset_accepts_custom_radiation_and_unset_d_bounds(tmp_path: Path) -> None:
    values = _form_values()
    values.update(
        input_mode="wavelength",
        radiation_value="1.78897",
        d_min_A="",
        d_max_A="",
    )
    target = save_analysis_preset(tmp_path / "wavelength.json", values)

    loaded = load_analysis_preset(target)

    assert loaded["radiation_value"] == pytest.approx(1.78897)
    assert loaded["d_min_A"] == ""
    assert loaded["d_max_A"] == ""


def test_save_rejects_unsupported_sensitive_fields_without_replacing_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing.json"
    target.write_text("keep this file", encoding="utf-8")
    values = _form_values()
    values["mp_api_key"] = "secret"

    with pytest.raises(ValueError, match="unknown or unsupported field.*mp_api_key"):
        save_analysis_preset(target, values)

    assert target.read_text(encoding="utf-8") == "keep this file"
    assert list(tmp_path.glob(".diffractscout-preset-*.tmp")) == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("two_theta_min", 120, "2theta range"),
        ("eta", float("nan"), "finite"),
        ("d_min_A", -1.0, "finite positive"),
        ("max_profile_points", True, "positive integer"),
        ("include_excel", "false", "must be a boolean"),
        ("profile_model", "unknown", "Unknown profile_model"),
    ],
)
def test_load_rejects_invalid_types_and_scientific_settings(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    target = save_analysis_preset(tmp_path / "valid.json", _form_values())
    document = _read_document(target)
    values = document["values"]
    assert isinstance(values, dict)
    values[field] = value
    target.write_text(json.dumps(document, allow_nan=True), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_analysis_preset(target)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema": "other"}, "unsupported schema"),
        ({"version": 2}, "unsupported version"),
        ({"extra": "value"}, "unknown extra"),
    ],
)
def test_load_rejects_unknown_schema_version_and_document_fields(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    target = save_analysis_preset(tmp_path / "valid.json", _form_values())
    document = _read_document(target)
    document.update(changes)
    target.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_analysis_preset(target)


def test_load_rejects_unknown_preset_fields_and_duplicate_json_keys(tmp_path: Path) -> None:
    target = save_analysis_preset(tmp_path / "valid.json", _form_values())
    document = _read_document(target)
    values = document["values"]
    assert isinstance(values, dict)
    values["output_path"] = "C:/private/output"
    target.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown or unsupported field.*output_path"):
        load_analysis_preset(target)

    target.write_text(
        '{"schema":"diffractscout_analysis_preset",'
        '"schema":"diffractscout_analysis_preset", "version":1,"values":{}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key 'schema'"):
        load_analysis_preset(target)


def test_load_rejects_oversized_preset_and_invalid_json(tmp_path: Path) -> None:
    target = tmp_path / "bad.json"
    target.write_text("{" + " " * (64 * 1024), encoding="utf-8")
    with pytest.raises(ValueError, match="size limit"):
        load_analysis_preset(target)

    target.write_text("not JSON", encoding="utf-8")
    with pytest.raises(ValueError, match="could not parse UTF-8 JSON"):
        load_analysis_preset(target)
