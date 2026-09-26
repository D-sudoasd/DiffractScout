"""Strict persistence for reusable local GUI analysis presets.

Presets intentionally contain only analysis and local-export controls. They
must never capture credentials, input/output paths, overwrite choices, or
per-structure elasticity overrides.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .diffraction import X_RAY_SOURCES_A, validate_analysis_settings
from .models import AnalysisSettings

_PRESET_SCHEMA = "diffractscout_analysis_preset"
_PRESET_VERSION = 1
_MAX_PRESET_BYTES = 64 * 1024

# These names correspond to analysis/local controls in DiffractScoutApp's
# `_create_variables`; keep this allowlist explicit so sensitive GUI state can
# never be serialized by accident.
_PRESET_FIELDS = frozenset(
    {
        "input_mode",
        "source_preset",
        "radiation_value",
        "two_theta_min",
        "two_theta_max",
        "step",
        "fwhm",
        "eta",
        "d_min_A",
        "d_max_A",
        "profile_model",
        "pattern_axis",
        "max_profile_points",
        "max_reflection_estimate",
        "include_excel",
        "include_elasticity",
        "export_lab_views",
        "include_patterns",
        "include_figures",
        "local_recursive",
    }
)
_BOOL_FIELDS = frozenset(
    {
        "include_excel",
        "include_elasticity",
        "export_lab_views",
        "include_patterns",
        "include_figures",
        "local_recursive",
    }
)
_FLOAT_FIELDS = {
    "two_theta_min": "2θ minimum",
    "two_theta_max": "2θ maximum",
    "step": "Profile step",
    "fwhm": "FWHM",
    "eta": "Pseudo-Voigt η",
}
_INTEGER_FIELDS = {
    "max_profile_points": "Maximum profile points",
    "max_reflection_estimate": "Maximum reciprocal candidates",
}


def _error(message: str) -> ValueError:
    return ValueError(f"Invalid analysis preset: {message}")


def _finite_number(value: object, field: str, *, allow_text: bool) -> float:
    if isinstance(value, bool) or (not allow_text and not isinstance(value, (int, float))):
        raise _error(f"{field} must be a finite JSON number.")
    if allow_text and not isinstance(value, (str, int, float)):
        raise _error(f"{field} must be a number.")
    try:
        parsed = float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _error(f"{field} must be a number.") from exc
    if not math.isfinite(parsed):
        raise _error(f"{field} must be finite.")
    return parsed


def _optional_number(value: object, field: str, *, allow_text: bool) -> float | None:
    if allow_text and isinstance(value, str) and not value.strip():
        return None
    if not allow_text and value is None:
        return None
    if value is None:
        raise _error(f"{field} must be a finite number when set.")
    return _finite_number(value, field, allow_text=allow_text)


def _positive_integer(value: object, field: str, *, allow_text: bool) -> int:
    if isinstance(value, bool):
        raise _error(f"{field} must be a positive integer.")
    if allow_text:
        if not isinstance(value, (str, int)):
            raise _error(f"{field} must be an integer.")
        try:
            parsed = int(value.strip() if isinstance(value, str) else value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise _error(f"{field} must be an integer.") from exc
    else:
        if type(value) is not int:
            raise _error(f"{field} must be a positive JSON integer.")
        parsed = value
    if parsed < 1:
        raise _error(f"{field} must be a positive integer.")
    return parsed


def _require_string(values: Mapping[str, object], field: str) -> str:
    value = values[field]
    if not isinstance(value, str):
        raise _error(f"{field} must be a string.")
    return value


def _normalize_values(values: object, *, from_form: bool) -> dict[str, object]:
    if not isinstance(values, Mapping):
        raise _error("values must be a JSON object.")
    supplied = set(values)
    missing = sorted(_PRESET_FIELDS - supplied)
    extra = sorted(supplied - _PRESET_FIELDS)
    if missing:
        raise _error(f"missing required field(s): {', '.join(missing)}.")
    if extra:
        raise _error(f"unknown or unsupported field(s): {', '.join(extra)}.")

    input_mode = _require_string(values, "input_mode")
    if input_mode not in {"source", "wavelength", "energy"}:
        raise _error("input_mode must be source, wavelength, or energy.")
    source_preset = _require_string(values, "source_preset")
    if source_preset not in X_RAY_SOURCES_A:
        raise _error(
            "source_preset must be one of: " + ", ".join(sorted(X_RAY_SOURCES_A)) + "."
        )

    raw_radiation = values["radiation_value"]
    if isinstance(raw_radiation, bool):
        raise _error("radiation_value must be a number or an empty string.")
    if from_form and not isinstance(raw_radiation, (str, int, float)):
        raise _error("radiation_value must be a number or an empty string.")
    if not from_form and raw_radiation is not None and not isinstance(raw_radiation, (int, float)):
        raise _error("radiation_value must be a JSON number or null.")
    consumes_radiation = input_mode != "source" or source_preset == "Custom"
    if consumes_radiation:
        radiation = _optional_number(raw_radiation, "radiation_value", allow_text=from_form)
    else:
        # A built-in source does not consume this disabled entry. Discard stale
        # GUI text, matching analysis_settings_from_form's behavior.
        radiation = None

    normalized: dict[str, object] = {
        "input_mode": input_mode,
        "source_preset": source_preset,
        "radiation_value": radiation,
        "d_min_A": _optional_number(values["d_min_A"], "d_min_A", allow_text=from_form),
        "d_max_A": _optional_number(values["d_max_A"], "d_max_A", allow_text=from_form),
        "profile_model": _require_string(values, "profile_model"),
        "pattern_axis": _require_string(values, "pattern_axis"),
    }
    normalized.update(
        {
            field: _finite_number(values[field], label, allow_text=from_form)
            for field, label in _FLOAT_FIELDS.items()
        }
    )
    normalized.update(
        {
            field: _positive_integer(values[field], label, allow_text=from_form)
            for field, label in _INTEGER_FIELDS.items()
        }
    )
    for field in _BOOL_FIELDS:
        value = values[field]
        if type(value) is not bool:
            raise _error(f"{field} must be a boolean.")
        normalized[field] = value

    analysis = AnalysisSettings(
        input_mode=input_mode,  # type: ignore[arg-type]
        source_preset=source_preset,
        wavelength_A=(
            float(radiation)
            if radiation is not None
            and (input_mode == "wavelength" or (input_mode == "source" and source_preset == "Custom"))
            else None
        ),
        energy_keV=(float(radiation) if radiation is not None and input_mode == "energy" else None),
        two_theta_min_deg=float(normalized["two_theta_min"]),
        two_theta_max_deg=float(normalized["two_theta_max"]),
        step_deg=float(normalized["step"]),
        fwhm_deg=float(normalized["fwhm"]),
        profile_eta=float(normalized["eta"]),
        include_elasticity=bool(normalized["include_elasticity"]),
        max_profile_points=int(normalized["max_profile_points"]),
        max_reflection_estimate=int(normalized["max_reflection_estimate"]),
        d_min_A=normalized["d_min_A"],  # type: ignore[arg-type]
        d_max_A=normalized["d_max_A"],  # type: ignore[arg-type]
        profile_model=normalized["profile_model"],  # type: ignore[arg-type]
        pattern_axis=normalized["pattern_axis"],  # type: ignore[arg-type]
        include_figures=bool(normalized["include_figures"]),
        export_lab_views=bool(normalized["export_lab_views"]),
        include_patterns=bool(normalized["include_patterns"]),
    )
    try:
        validate_analysis_settings(analysis)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _error(str(exc)) from exc

    # Return empty strings for unset optional GUI entries. Tk StringVars accept
    # these normalized numbers directly via `.set()`.
    normalized["radiation_value"] = "" if radiation is None else radiation
    normalized["d_min_A"] = "" if normalized["d_min_A"] is None else normalized["d_min_A"]
    normalized["d_max_A"] = "" if normalized["d_max_A"] is None else normalized["d_max_A"]
    return normalized


def _serialized_values(values: Mapping[str, object]) -> dict[str, object]:
    """Encode blank GUI entries as JSON null for all optional numeric fields."""

    serialized = dict(values)
    for field in ("radiation_value", "d_min_A", "d_max_A"):
        if serialized[field] == "":
            serialized[field] = None
    return serialized


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _error(f"duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise _error(f"non-finite JSON number {value} is not allowed.")


def _target_path(path: str | Path) -> Path:
    try:
        raw = os.fspath(path)
    except TypeError as exc:
        raise TypeError("preset path must be a string or path-like value") from exc
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("preset path must be a non-empty string")
    return Path(raw).expanduser()


def save_analysis_preset(path: str | Path, values: Mapping[str, object]) -> Path:
    """Validate and atomically save a complete local analysis preset."""

    target = _target_path(path)
    normalized = _normalize_values(values, from_form=True)
    document = {
        "schema": _PRESET_SCHEMA,
        "version": _PRESET_VERSION,
        "values": _serialized_values(normalized),
    }
    encoded = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    if len(encoded) > _MAX_PRESET_BYTES:
        raise _error(f"preset exceeds the {_MAX_PRESET_BYTES}-byte size limit.")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".diffractscout-preset-",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                # Keep a write/replace failure as the primary exception.
                pass
    return target


def load_analysis_preset(path: str | Path) -> dict[str, object]:
    """Read, fully validate, and return one flat GUI-ready analysis preset.

    The returned mapping is constructed only after every schema, type, and
    scientific-settings check succeeds, so callers can apply it atomically.
    """

    source = _target_path(path)
    with source.open("rb") as stream:
        raw = stream.read(_MAX_PRESET_BYTES + 1)
    if len(raw) > _MAX_PRESET_BYTES:
        raise _error(f"preset exceeds the {_MAX_PRESET_BYTES}-byte size limit.")
    try:
        text = raw.decode("utf-8")
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonstandard_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error(f"could not parse UTF-8 JSON ({exc}).") from exc
    if not isinstance(document, dict):
        raise _error("document root must be a JSON object.")
    if set(document) != {"schema", "version", "values"}:
        missing = sorted({"schema", "version", "values"} - set(document))
        extra = sorted(set(document) - {"schema", "version", "values"})
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unknown " + ", ".join(extra))
        raise _error("document fields are invalid: " + "; ".join(details) + ".")
    if document["schema"] != _PRESET_SCHEMA:
        raise _error(f"unsupported schema {document['schema']!r}.")
    version = document["version"]
    if type(version) is not int or version != _PRESET_VERSION:
        raise _error(f"unsupported version {version!r}; expected {_PRESET_VERSION}.")
    return _normalize_values(document["values"], from_form=False)
