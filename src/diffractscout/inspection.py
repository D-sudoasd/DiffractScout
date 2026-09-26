"""Read-only inspection of verified DiffractScout result bundles."""

from __future__ import annotations

import csv
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
from typing import Any, Iterator

from .validation import verify_bundle

INSPECTION_SCHEMA = "diffractscout_inspection_v1"
_MAX_METADATA_JSON_BYTES = 4 * 1024 * 1024
_MAX_PROVENANCE_JSON_BYTES = 64 * 1024 * 1024
_MAX_DIAGNOSTIC_PREVIEW = 30
_MAX_DIAGNOSTIC_TEXT_CHARS = 500
_MAX_ERROR_PREVIEW = 100
_REQUIRED_FILES = (
    "phase_summary.csv",
    "peak_reference.csv",
    "diagnostics.csv",
    "provenance.json",
    "candidate_index.csv",
    "download_index.csv",
)
_OUTPUT_FILES = {
    "phase_summary_csv": "phase_summary.csv",
    "peak_reference_csv": "peak_reference.csv",
    "diagnostics_csv": "diagnostics.csv",
    "results_xlsx": "results.xlsx",
    "provenance_json": "provenance.json",
    "pattern_profiles_csv": "pattern_profiles.csv",
    "elasticity_csv": "elasticity.csv",
    "candidate_index_csv": "candidate_index.csv",
    "download_index_csv": "download_index.csv",
    "readme": "README.md",
}


def _bounded_text(value: object, limit: int = _MAX_DIAGNOSTIC_TEXT_CHARS) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _verification_summary(report: dict[str, Any]) -> dict[str, Any]:
    errors = report.get("errors")
    if not isinstance(errors, list):
        errors = ["Bundle verification returned an invalid error list."]
    return {
        "ok": bool(report.get("ok")),
        "manifest": str(report.get("manifest") or ""),
        "files_checked": len(report.get("files", []))
        if isinstance(report.get("files"), list)
        else 0,
        "error_count": len(errors),
        "errors": [_bounded_text(error, 2_000) for error in errors[:_MAX_ERROR_PREVIEW]],
        "errors_truncated": len(errors) > _MAX_ERROR_PREVIEW,
    }


def _failed_report(
    bundle: Path,
    verification: dict[str, Any],
    inspection_errors: list[str] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": INSPECTION_SCHEMA,
        "bundle": str(bundle),
        "ok": False,
        "verification": verification,
    }
    if inspection_errors is not None:
        report["inspection"] = {
            "ok": False,
            "errors": [_bounded_text(error, 2_000) for error in inspection_errors],
        }
    return report


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON value: {value}")


def _read_limited_json(path: Path, *, label: str, max_bytes: int) -> dict[str, Any]:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"{label} exceeds the {max_bytes}-byte inspection limit."
        )
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"{label} changed while it was being read.")
    payload = json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be a JSON object.")
    return payload


def _read_small_json(path: Path, *, label: str) -> dict[str, Any]:
    return _read_limited_json(
        path,
        label=label,
        max_bytes=_MAX_METADATA_JSON_BYTES,
    )


def _read_provenance_fields(path: Path) -> dict[str, Any]:
    payload = _read_limited_json(
        path,
        label="provenance.json",
        max_bytes=_MAX_PROVENANCE_JSON_BYTES,
    )
    return payload


def _safe_manifest_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_entries = manifest.get("files")
    if not isinstance(raw_entries, list):
        raise ValueError("Manifest 'files' must be a list.")
    entries: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Manifest file entry {index} must be an object.")
        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"Manifest file entry {index} has no path.")
        relative = Path(raw_path)
        normalized = relative.as_posix()
        if (
            relative.is_absolute()
            or normalized in {".", "manifest.json"}
            or ".." in relative.parts
            or any(part in {"", "."} for part in relative.parts)
        ):
            raise ValueError(f"Unsafe manifest path: {raw_path!r}.")
        if normalized in entries:
            raise ValueError(f"Duplicate manifest path: {normalized}.")
        entries[normalized] = entry
    return entries


@contextmanager
def _csv_rows(path: Path) -> Iterator[tuple[list[str], Iterator[list[str]]]]:
    """Open a CSV as a stream and reject ambiguous or malformed row shapes."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        headers = next(reader, None)
        if not headers or any(not header for header in headers):
            raise ValueError(f"{path.name} has no complete header row.")
        if len(set(headers)) != len(headers):
            raise ValueError(f"{path.name} contains duplicate column names.")

        def rows() -> Iterator[list[str]]:
            for row in reader:
                if not row:
                    continue
                if len(row) != len(headers):
                    raise ValueError(
                        f"{path.name} row {reader.line_num} has {len(row)} fields; "
                        f"expected {len(headers)}."
                    )
                yield row

        yield headers, rows()


def _count_phases(path: Path) -> tuple[int, int]:
    with _csv_rows(path) as (headers, rows):
        required = {"phase_name", "reflection_count"}
        missing = required - set(headers)
        if missing:
            raise ValueError(
                f"{path.name} is missing required columns: {', '.join(sorted(missing))}."
            )
        reflection_index = headers.index("reflection_count")
        count = 0
        reflections = 0
        for row in rows:
            count += 1
            try:
                phase_reflections = int(row[reflection_index])
            except ValueError as exc:
                raise ValueError(
                    f"{path.name} row {count + 1} has an invalid reflection_count."
                ) from exc
            if phase_reflections < 0:
                raise ValueError(
                    f"{path.name} row {count + 1} has a negative reflection_count."
                )
            reflections += phase_reflections
        return count, reflections


def _count_reflections(path: Path) -> int:
    with _csv_rows(path) as (headers, rows):
        if "phase_name" not in headers:
            raise ValueError(f"{path.name} is missing the phase_name column.")
        return sum(1 for _ in rows)


def _count_records(path: Path, *, required_column: str) -> int:
    with _csv_rows(path) as (headers, rows):
        if required_column not in headers:
            raise ValueError(
                f"{path.name} is missing the {required_column} column."
            )
        return sum(1 for _ in rows)


def _inspect_diagnostics(path: Path) -> tuple[dict[str, int], list[dict[str, str]]]:
    levels = {"info": 0, "warning": 0, "error": 0, "other": 0}
    preview: list[dict[str, str]] = []
    with _csv_rows(path) as (headers, rows):
        required = {"stage", "item", "level", "message"}
        missing = required - set(headers)
        if missing:
            raise ValueError(
                f"{path.name} is missing required columns: {', '.join(sorted(missing))}."
            )
        indexes = {key: headers.index(key) for key in required}
        for row in rows:
            level = row[indexes["level"]].strip().lower()
            levels[level if level in {"info", "warning", "error"} else "other"] += 1
            if len(preview) < _MAX_DIAGNOSTIC_PREVIEW:
                preview.append(
                    {
                        "stage": _bounded_text(row[indexes["stage"]]),
                        "item": _bounded_text(row[indexes["item"]]),
                        "level": _bounded_text(row[indexes["level"]], 100),
                        "message": _bounded_text(row[indexes["message"]]),
                    }
                )
    return levels, preview


def _validate_settings(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("provenance.json is missing the analysis_settings object.")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError("analysis_settings keys must be strings.")
        if item is None or isinstance(item, (str, bool, int)):
            result[key] = _bounded_text(item) if isinstance(item, str) else item
        elif isinstance(item, float) and math.isfinite(item):
            result[key] = item
        else:
            raise ValueError(f"analysis setting {key!r} is not a finite scalar value.")
    return result


def inspect_bundle(bundle: str | Path) -> dict[str, Any]:
    """Verify and summarize a result bundle without modifying or executing it.

    A bundle that fails integrity verification is returned without result counts,
    settings, or file conclusions. CSVs are read row by row, and diagnostic text
    is bounded in the report while the severity counts include every row.
    """

    supplied = Path(bundle).expanduser()
    supplied = Path(os.path.abspath(os.fspath(supplied)))
    manifest_path = supplied if supplied.name == "manifest.json" else supplied / "manifest.json"
    root = manifest_path.parent

    try:
        manifest_size = manifest_path.stat().st_size
    except OSError:
        # Missing, inaccessible, and unsafe paths are diagnosed by the bundle
        # verifier; this preflight exists only to bound its JSON input size.
        pass
    else:
        if manifest_size > _MAX_METADATA_JSON_BYTES:
            verification = _verification_summary(
                {
                    "ok": False,
                    "manifest": str(manifest_path),
                    "files": [],
                    "errors": [
                        "manifest.json exceeds the "
                        f"{_MAX_METADATA_JSON_BYTES}-byte inspection limit."
                    ],
                }
            )
            return _failed_report(root, verification)

    try:
        verification_raw = verify_bundle(supplied)
    except (OSError, RecursionError, RuntimeError, UnicodeError, ValueError) as exc:
        verification_raw = {
            "ok": False,
            "manifest": str(manifest_path),
            "files": [],
            "errors": [f"Bundle verification failed: {type(exc).__name__}: {exc}"],
        }
    verification = _verification_summary(verification_raw)
    if not verification["ok"]:
        return _failed_report(root, verification)

    try:
        manifest = _read_small_json(manifest_path, label="manifest.json")
        if manifest.get("schema") != "diffractscout_bundle_manifest_v1":
            raise ValueError("manifest.json has an unsupported bundle schema.")
        entries = _safe_manifest_entries(manifest)
        missing = [name for name in _REQUIRED_FILES if name not in entries]
        if missing:
            raise ValueError(
                "Manifest does not list required bundle files: " + ", ".join(missing) + "."
            )

        # Only fixed, known filenames are opened. Manifest entries are used to
        # confirm presence and describe the inventory; they never select a path
        # that this module will read.
        phase_path = root / "phase_summary.csv"
        peak_path = root / "peak_reference.csv"
        diagnostic_path = root / "diagnostics.csv"
        candidate_path = root / "candidate_index.csv"
        download_path = root / "download_index.csv"
        provenance_path = root / "provenance.json"
        phase_count, phase_reflection_count = _count_phases(phase_path)
        reflection_count = _count_reflections(peak_path)
        candidate_count = _count_records(candidate_path, required_column="material_id")
        download_count = _count_records(download_path, required_column="material_id")
        diagnostic_levels, diagnostic_preview = _inspect_diagnostics(diagnostic_path)
        diagnostic_count = sum(diagnostic_levels.values())
        provenance = _read_provenance_fields(provenance_path)
        if provenance.get("schema") != "diffractscout_provenance_v1":
            raise ValueError("provenance.json has an unsupported schema.")
        software_versions = provenance.get("software_versions")
        if not isinstance(software_versions, dict):
            raise ValueError("provenance.json is missing the software_versions object.")
        version = software_versions.get("diffractscout")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("provenance.json is missing the DiffractScout version.")
        if "analysis_settings" not in provenance:
            raise ValueError("provenance.json is missing the analysis_settings field.")
        settings = _validate_settings(provenance["analysis_settings"])

        inspection_errors: list[str] = []
        if phase_reflection_count != reflection_count:
            inspection_errors.append(
                "phase_summary.csv reflection counts do not match peak_reference.csv rows."
            )
        manifest_summary = manifest.get("summary")
        if manifest_summary is not None and not isinstance(manifest_summary, dict):
            inspection_errors.append("Manifest 'summary' must be an object.")
        if isinstance(manifest_summary, dict):
            actual_counts = {
                "phase_count": phase_count,
                "reflection_count": reflection_count,
                "candidate_count": candidate_count,
                "download_count": download_count,
                "diagnostic_count": diagnostic_count,
                "error_count": diagnostic_levels["error"],
            }
            for key, actual in actual_counts.items():
                declared = manifest_summary.get(key)
                if declared is not None and (
                    isinstance(declared, bool)
                    or not isinstance(declared, int)
                    or declared != actual
                ):
                    inspection_errors.append(
                        f"Manifest summary {key} does not match the verified CSV contents."
                    )

        if inspection_errors:
            return _failed_report(root, verification, inspection_errors)

        outputs = {
            output_key: (
                str(root / filename) if filename in entries else None
            )
            for output_key, filename in _OUTPUT_FILES.items()
        }
        members = []
        verification_paths = {
            item.get("path")
            for item in verification_raw.get("files", [])
            if isinstance(item, dict) and item.get("ok") is True
        }
        for relative, entry in entries.items():
            members.append(
                {
                    "path": relative,
                    "role": entry.get("role") if isinstance(entry.get("role"), str) else None,
                    "size_bytes": entry.get("size_bytes"),
                    "verified": relative in verification_paths,
                }
            )

        report: dict[str, Any] = {
            "schema": INSPECTION_SCHEMA,
            "bundle": str(root),
            "ok": not inspection_errors,
            "verification": verification,
            "inspection": {"ok": not inspection_errors, "errors": inspection_errors},
            "software_version": version.strip(),
            "analysis_settings": settings,
            "counts": {
                "phases": phase_count,
                "reflections": reflection_count,
                "candidates": candidate_count,
                "downloads": download_count,
                "diagnostics": diagnostic_count,
                "diagnostics_by_level": diagnostic_levels,
            },
            "files": {
                "manifest": str(manifest_path),
                "count": len(members),
                "outputs": outputs,
                "members": members,
            },
            "diagnostics_preview": diagnostic_preview,
            "diagnostics_preview_truncated": diagnostic_count > len(diagnostic_preview),
        }
        return report
    except (OSError, csv.Error, RecursionError, RuntimeError, UnicodeError, ValueError) as exc:
        return _failed_report(
            root,
            verification,
            [f"Could not inspect verified bundle: {type(exc).__name__}: {exc}"],
        )


def format_inspection(report: dict[str, Any]) -> str:
    """Return a concise human-readable report for :func:`inspect_bundle`."""

    lines = [f"Bundle: {report.get('bundle', '(unknown)')}"]
    verification = report.get("verification")
    if isinstance(verification, dict):
        if verification.get("ok"):
            lines.append(
                "Verification: passed "
                f"({verification.get('files_checked', 0)} files checked)"
            )
        else:
            lines.append("Verification: failed")
            for error in verification.get("errors", []):
                lines.append(f"  - {error}")
            if verification.get("errors_truncated"):
                lines.append("  - Additional verification errors omitted.")

    inspection = report.get("inspection")
    if isinstance(inspection, dict) and not inspection.get("ok"):
        lines.append("Inspection: failed")
        for error in inspection.get("errors", []):
            lines.append(f"  - {error}")
        return "\n".join(lines)
    if not report.get("ok"):
        return "\n".join(lines)

    lines.append(f"DiffractScout version: {report.get('software_version', 'unknown')}")
    counts = report.get("counts")
    if isinstance(counts, dict):
        levels = counts.get("diagnostics_by_level", {})
        lines.append(
            "Results: "
            f"{counts.get('phases', 0)} phases, "
            f"{counts.get('reflections', 0)} reflections, "
            f"{counts.get('candidates', 0)} candidates, "
            f"{counts.get('downloads', 0)} downloads, "
            f"{counts.get('diagnostics', 0)} diagnostics "
            f"(info {levels.get('info', 0)}, warning {levels.get('warning', 0)}, "
            f"error {levels.get('error', 0)}, other {levels.get('other', 0)})"
        )

    settings = report.get("analysis_settings")
    if isinstance(settings, dict):
        lines.append("Analysis settings:")
        for key, value in settings.items():
            lines.append(f"  {key}: {value}")
    elif settings is None and report.get("ok"):
        lines.append("Analysis settings: not recorded")

    files = report.get("files")
    if isinstance(files, dict):
        lines.append(f"Files: {files.get('count', 0)} verified bundle members")
        outputs = files.get("outputs")
        if isinstance(outputs, dict):
            lines.append("Key outputs:")
            for name, path in outputs.items():
                lines.append(f"  {name}: {path if path is not None else 'not included'}")

    previews = report.get("diagnostics_preview")
    if isinstance(previews, list) and previews:
        lines.append("Diagnostics:")
        for item in previews:
            if isinstance(item, dict):
                lines.append(
                    f"  [{item.get('level', 'unknown')}] "
                    f"{item.get('stage', '')} / {item.get('item', '')}: "
                    f"{item.get('message', '')}"
                )
        if report.get("diagnostics_preview_truncated"):
            lines.append("  Additional diagnostics omitted from display.")
    elif isinstance(counts, dict) and counts.get("diagnostics") == 0:
        lines.append("Diagnostics: none")
    return "\n".join(lines)
