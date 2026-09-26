from __future__ import annotations

import csv
import json
from pathlib import Path
import pickle

import diffractscout.inspection as inspection_module
from diffractscout.inspection import format_inspection, inspect_bundle
from diffractscout.models import AnalysisSettings, CandidateRecord, DiscoverySettings
from diffractscout.pipeline import analyze_cifs, export_discovery
from diffractscout.utils import sha256_file


def _make_bundle(
    output: Path,
    inputs: Path,
    *,
    settings: AnalysisSettings | None = None,
    include_excel: bool = True,
) -> Path:
    analyze_cifs(
        [inputs],
        output,
        settings=settings,
        include_excel=include_excel,
    )
    return output


def _rewrite_manifest_member(bundle: Path, relative: str) -> None:
    path = bundle / relative
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [
        entry for entry in manifest["files"] if entry["path"] != relative
    ]
    manifest["files"].append(
        {
            "path": relative,
            "role": "documentation",
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_sentinel(path: str) -> None:
    Path(path).write_text("unpickled", encoding="utf-8")


class _PickleCanary:
    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def __reduce__(self) -> tuple[object, tuple[str]]:
        return (_write_sentinel, (self.path,))


class _DiscoveryProvider:
    name = "offline-inspection-fixture"

    def search_subsystem(self, chemsys: str, **_kwargs: object) -> list[CandidateRecord]:
        return [
            CandidateRecord(
                material_id="fixture-1",
                formula="Al",
                queried_chemsys=chemsys,
                source_provider=self.name,
            )
        ]

    def metadata(self) -> dict[str, object]:
        return {"provider": self.name, "offline": True}


def test_inspect_verified_bundle_reports_settings_counts_and_files(
    demo_inputs: Path, tmp_path: Path
) -> None:
    bundle = _make_bundle(tmp_path / "result", demo_inputs)

    report = inspect_bundle(bundle)

    assert report["ok"] is True
    assert report["verification"]["ok"] is True
    assert report["software_version"]
    assert report["analysis_settings"]["input_mode"] == "source"
    assert report["counts"]["phases"] == 1
    assert report["counts"]["reflections"] > 0
    assert report["counts"]["diagnostics"] == 0
    assert report["files"]["outputs"]["results_xlsx"] == str(bundle / "results.xlsx")
    assert all(item["verified"] for item in report["files"]["members"])
    assert "Verification: passed" in format_inspection(report)


def test_inspect_multiphase_bundle_counts_warnings(
    tmp_path: Path,
) -> None:
    benchmark_inputs = Path(__file__).parents[1] / "src" / "diffractscout" / "benchmark_data"
    bundle = _make_bundle(
        tmp_path / "multiphase",
        benchmark_inputs,
        settings=AnalysisSettings(step_deg=0.1, include_elasticity=False),
        include_excel=False,
    )

    report = inspect_bundle(bundle)

    assert report["ok"] is True
    assert report["counts"]["phases"] == 4
    assert report["counts"]["reflections"] == 43
    assert report["counts"]["diagnostics_by_level"]["warning"] == 4
    assert report["files"]["outputs"]["results_xlsx"] is None
    assert len(report["diagnostics_preview"]) == 4


def test_partial_error_bundle_is_still_inspectable(
    demo_inputs: Path, tmp_path: Path
) -> None:
    (demo_inputs / "invalid.cif").write_text("not a CIF\n", encoding="utf-8")
    bundle = _make_bundle(tmp_path / "partial", demo_inputs, include_excel=False)

    report = inspect_bundle(bundle)

    assert report["ok"] is True
    assert report["counts"]["phases"] == 1
    assert report["counts"]["diagnostics_by_level"]["error"] == 1
    assert report["diagnostics_preview"][0]["level"] == "error"
    assert "[error]" in format_inspection(report)


def test_inspect_discovery_bundle_with_zero_phases_and_missing_settings(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "discovery"
    export_discovery(
        "Al",
        _DiscoveryProvider(),  # type: ignore[arg-type]
        bundle,
        discovery_settings=DiscoverySettings(mode="single_chemsys", max_total=1),
        include_excel=False,
    )
    provenance_path = bundle / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["analysis_settings"] = None
    provenance["discovery"]["opaque_provider_payload"] = "x" * (5 * 1024 * 1024)
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    _rewrite_manifest_member(bundle, "provenance.json")

    report = inspect_bundle(bundle)

    assert report["ok"] is True
    assert report["counts"]["phases"] == 0
    assert report["counts"]["reflections"] == 0
    assert report["counts"]["candidates"] == 1
    assert report["counts"]["downloads"] == 0
    assert report["analysis_settings"] is None
    assert "Analysis settings: not recorded" in format_inspection(report)


def test_provenance_over_limit_returns_readable_inspection_error(
    demo_inputs: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = _make_bundle(tmp_path / "limited-provenance", demo_inputs, include_excel=False)
    monkeypatch.setattr(inspection_module, "_MAX_PROVENANCE_JSON_BYTES", 1)

    report = inspect_bundle(bundle)

    assert report["verification"]["ok"] is True
    assert report["ok"] is False
    assert "exceeds the 1-byte inspection limit" in report["inspection"]["errors"][0]
    assert "counts" not in report


def test_oversized_manifest_is_rejected_before_bundle_verification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "oversized-manifest"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}          ", encoding="utf-8")
    monkeypatch.setattr(inspection_module, "_MAX_METADATA_JSON_BYTES", 4)

    def unexpected_verification(_bundle: Path) -> dict[str, object]:
        raise AssertionError("oversized manifest must be rejected before verification")

    monkeypatch.setattr(inspection_module, "verify_bundle", unexpected_verification)

    report = inspect_bundle(bundle)

    assert report["ok"] is False
    assert report["verification"]["ok"] is False
    assert report["verification"]["files_checked"] == 0
    assert "exceeds the 4-byte inspection limit" in report["verification"]["errors"][0]


def test_inspect_counts_all_diagnostics_but_limits_preview(
    demo_inputs: Path, tmp_path: Path
) -> None:
    bundle = _make_bundle(tmp_path / "many-diagnostics", demo_inputs, include_excel=False)
    diagnostic_path = bundle / "diagnostics.csv"
    with diagnostic_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for index in range(40):
            writer.writerow(["test", str(index), "warning", "x" * 900])
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["summary"]["diagnostic_count"] = 40
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _rewrite_manifest_member(bundle, "diagnostics.csv")

    report = inspect_bundle(bundle)

    assert report["ok"] is True
    assert report["counts"]["diagnostics"] == 40
    assert report["counts"]["diagnostics_by_level"]["warning"] == 40
    assert len(report["diagnostics_preview"]) == 30
    assert len(report["diagnostics_preview"][0]["message"]) == 500
    assert report["diagnostics_preview_truncated"] is True


def test_tampered_bundle_returns_verification_errors_without_conclusions(
    demo_inputs: Path, tmp_path: Path
) -> None:
    bundle = _make_bundle(tmp_path / "tampered", demo_inputs, include_excel=False)
    with (bundle / "phase_summary.csv").open("a", encoding="utf-8") as handle:
        handle.write("tampered\n")

    report = inspect_bundle(bundle)

    assert report["ok"] is False
    assert report["verification"]["ok"] is False
    assert any("hash mismatch" in error for error in report["verification"]["errors"])
    assert "counts" not in report
    assert "analysis_settings" not in report
    assert "Verification: failed" in format_inspection(report)


def test_missing_bundle_member_is_reported_without_conclusions(
    demo_inputs: Path, tmp_path: Path
) -> None:
    bundle = _make_bundle(tmp_path / "missing", demo_inputs, include_excel=False)
    (bundle / "peak_reference.csv").unlink()

    report = inspect_bundle(bundle)

    assert report["ok"] is False
    assert report["verification"]["ok"] is False
    assert any("missing file: peak_reference.csv" in error for error in report["verification"]["errors"])
    assert "counts" not in report


def test_non_bundle_directory_reports_missing_manifest(tmp_path: Path) -> None:
    directory = tmp_path / "not-a-bundle"
    directory.mkdir()

    report = inspect_bundle(directory)

    assert report["ok"] is False
    assert report["verification"]["ok"] is False
    assert report["verification"]["errors"] == ["manifest.json not found"]
    assert "software_version" not in report


def test_manifest_paths_are_rejected_before_inspection(
    demo_inputs: Path, tmp_path: Path
) -> None:
    bundle = _make_bundle(tmp_path / "unsafe-path", demo_inputs, include_excel=False)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {
            "path": "../outside.json",
            "role": "provenance",
            "sha256": "0" * 64,
            "size_bytes": 0,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = inspect_bundle(bundle)

    assert report["ok"] is False
    assert report["verification"]["ok"] is False
    assert any("unsafe manifest path" in error for error in report["verification"]["errors"])
    assert "files" not in report


def test_inconsistent_manifest_summary_withholds_result_conclusions(
    demo_inputs: Path, tmp_path: Path
) -> None:
    bundle = _make_bundle(tmp_path / "inconsistent-summary", demo_inputs, include_excel=False)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["summary"]["phase_count"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = inspect_bundle(bundle)

    assert report["verification"]["ok"] is True
    assert report["ok"] is False
    assert report["inspection"]["ok"] is False
    assert any("phase_count" in error for error in report["inspection"]["errors"])
    assert "counts" not in report
    assert "analysis_settings" not in report


def test_inspection_never_unpickles_bundle_members(
    demo_inputs: Path, tmp_path: Path
) -> None:
    bundle = _make_bundle(tmp_path / "pickle-member", demo_inputs, include_excel=False)
    sentinel = tmp_path / "pickle-executed.txt"
    payload = bundle / "opaque.pkl"
    payload.write_bytes(pickle.dumps(_PickleCanary(sentinel)))
    _rewrite_manifest_member(bundle, "opaque.pkl")

    report = inspect_bundle(bundle)

    assert report["ok"] is True
    assert any(item["path"] == "opaque.pkl" for item in report["files"]["members"])
    assert not sentinel.exists()


def test_inspect_accepts_manifest_path_argument(demo_inputs: Path, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "manifest-argument", demo_inputs, include_excel=False)

    report = inspect_bundle(bundle / "manifest.json")

    assert report["ok"] is True
    assert report["bundle"] == str(bundle)
