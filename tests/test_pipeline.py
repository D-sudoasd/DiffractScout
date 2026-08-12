import csv
from pathlib import Path
import shutil

from openpyxl import load_workbook
import pytest

from diffractscout.models import AnalysisSettings
from diffractscout.pipeline import analyze_cifs, collect_cif_paths, run_pipeline
from diffractscout.validation import verify_bundle


def test_local_pipeline_is_self_contained_and_verifiable(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    result = analyze_cifs([demo_inputs], output)
    assert len(result.analyses) == 1
    assert (output / "inputs" / "synthetic_fcc_al.cif").is_file()
    assert (output / "peak_reference.csv").is_file()
    assert (output / "results.xlsx").is_file()
    assert verify_bundle(output)["ok"]

    with (output / "peak_reference.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert rows[0]["hkl"] == "(1 1 1)"
    assert rows[0]["cif_name"] == "synthetic_fcc_al.cif"
    assert rows[0]["volume_normalized_intensity_with_lp"] == rows[0]["material_scattering_factor_R_hkl"]
    assert rows[0]["volume_normalized_intensity_no_lp"] == rows[0]["material_scattering_factor_R_hkl_no_lp"]

    workbook = load_workbook(output / "results.xlsx", read_only=True)
    assert {"Summary", "Phases", "Peaks", "Elasticity", "Candidates", "Downloads", "Patterns"}.issubset(workbook.sheetnames)


def test_output_overwrite_requires_known_manifest(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "occupied"
    output.mkdir()
    (output / "user.txt").write_text("keep", encoding="utf-8")
    try:
        analyze_cifs([demo_inputs], output, overwrite=True)
    except FileExistsError:
        pass
    else:
        raise AssertionError("Expected refusal to overwrite an unrelated directory")
    assert (output / "user.txt").read_text(encoding="utf-8") == "keep"


def test_output_path_must_be_a_directory(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "result-file"
    output.write_text("keep", encoding="utf-8")
    try:
        analyze_cifs([demo_inputs], output)
    except FileExistsError as exc:
        assert "not a directory" in str(exc)
    else:
        raise AssertionError("Expected refusal when the output path is a file")
    assert output.read_text(encoding="utf-8") == "keep"


def test_no_elasticity_does_not_copy_or_load_sidecar(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "no-elasticity"
    result = analyze_cifs(
        [demo_inputs],
        output,
        settings=AnalysisSettings(include_elasticity=False),
        include_excel=False,
    )
    assert len(result.analyses) == 1
    assert result.analyses[0].elastic_tensor is None
    assert result.analyses[0].metadata["elasticity_requested"] is False
    assert {
        reflection.elastic_status for reflection in result.analyses[0].reflections
    } == {"not_requested"}
    assert not list((output / "inputs").glob("*_elasticity.json"))


def test_collect_cif_paths_is_case_insensitive(demo_inputs: Path, tmp_path: Path) -> None:
    scan_root = tmp_path / "case-scan"
    scan_root.mkdir()
    upper = scan_root / "UPPER.CIF"
    shutil.copy2(demo_inputs / "synthetic_fcc_al.cif", upper)
    assert collect_cif_paths([scan_root]) == [upper.resolve()]


def test_same_named_inputs_are_preserved_without_collision(
    demo_inputs: Path, tmp_path: Path
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    shutil.copy2(demo_inputs / "synthetic_fcc_al.cif", left / "phase.cif")
    shutil.copy2(demo_inputs / "synthetic_fcc_al.cif", right / "phase.cif")

    output = tmp_path / "collision-safe"
    result = analyze_cifs(
        [left, right],
        output,
        settings=AnalysisSettings(include_elasticity=False),
        include_excel=False,
    )
    bundled = sorted(path.name for path in (output / "inputs").glob("*.cif"))
    assert len(result.analyses) == 2
    assert bundled[0] == "phase.cif"
    assert len(bundled) == 2
    assert bundled[1].startswith("phase_")


def test_missing_explicit_input_is_not_silently_ignored(tmp_path: Path) -> None:
    missing = tmp_path / "missing.cif"
    try:
        collect_cif_paths([missing])
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("Expected an explicit missing input to raise FileNotFoundError")


def test_input_output_overlap_is_rejected_before_writes(demo_inputs: Path) -> None:
    output = demo_inputs / "nested-result"
    try:
        analyze_cifs([demo_inputs], output, include_excel=False)
    except ValueError as exc:
        assert "must be disjoint" in str(exc)
    else:
        raise AssertionError("Expected overlapping input/output paths to be rejected")
    assert not output.exists()


def test_invalid_run_settings_fail_before_output_writes(
    demo_inputs: Path, tmp_path: Path
) -> None:
    output = tmp_path / "invalid-settings"
    with pytest.raises(ValueError, match="2theta range"):
        analyze_cifs(
            [demo_inputs],
            output,
            settings=AnalysisSettings(
                two_theta_min_deg=120.0,
                two_theta_max_deg=5.0,
            ),
            include_excel=False,
        )
    assert not output.exists()


def test_invalid_figure_preset_fails_before_output_writes(
    demo_inputs: Path, tmp_path: Path
) -> None:
    output = tmp_path / "invalid-figure-preset"
    with pytest.raises(ValueError, match="Unknown figure export preset"):
        analyze_cifs(
            [demo_inputs],
            output,
            settings=AnalysisSettings(
                include_figures=True,
                figure_preset="not-a-preset",
            ),
            include_excel=False,
        )
    assert not output.exists()


def test_workbook_contains_structured_diagnostics_sheet(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "diagnostic-workbook"
    analyze_cifs([demo_inputs], output)
    workbook = load_workbook(output / "results.xlsx", read_only=True)
    assert "Diagnostics" in workbook.sheetnames
    headers = [cell.value for cell in next(workbook["Diagnostics"].iter_rows(max_row=1))]
    assert headers == ["stage", "item", "level", "message"]


def test_overwrite_requires_an_intact_existing_bundle(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "damaged-bundle"
    analyze_cifs([demo_inputs], output, include_excel=False)
    (output / "phase_summary.csv").write_text("damaged", encoding="utf-8")
    try:
        analyze_cifs([demo_inputs], output, include_excel=False, overwrite=True)
    except FileExistsError as exc:
        assert "fails integrity verification" in str(exc)
    else:
        raise AssertionError("Expected refusal to replace a damaged result bundle")
    assert (output / "phase_summary.csv").read_text(encoding="utf-8") == "damaged"


def test_failed_staged_export_preserves_previous_verified_bundle(
    demo_inputs: Path, tmp_path: Path, monkeypatch
) -> None:
    import diffractscout.pipeline as pipeline

    output = tmp_path / "previous-bundle"
    analyze_cifs([demo_inputs], output, include_excel=False)
    original_manifest = (output / "manifest.json").read_bytes()

    def fail_export(*_args, **_kwargs):
        raise RuntimeError("simulated export failure")

    monkeypatch.setattr(pipeline, "export_result_bundle", fail_export)
    try:
        pipeline.analyze_cifs(
            [demo_inputs], output, include_excel=False, overwrite=True
        )
    except RuntimeError as exc:
        assert "simulated export failure" in str(exc)
    else:
        raise AssertionError("Expected staged export failure")
    assert (output / "manifest.json").read_bytes() == original_manifest
    assert verify_bundle(output)["ok"]


def test_target_created_during_run_is_not_silently_replaced(
    demo_inputs: Path, tmp_path: Path, monkeypatch
) -> None:
    import diffractscout.pipeline as pipeline

    output = tmp_path / "raced-target"
    original_export = pipeline.export_result_bundle

    def export_then_occupy(*args, **kwargs):
        manifest = original_export(*args, **kwargs)
        output.mkdir()
        (output / "user.txt").write_text("keep", encoding="utf-8")
        return manifest

    monkeypatch.setattr(pipeline, "export_result_bundle", export_then_occupy)
    with pytest.raises(FileExistsError, match="not empty"):
        analyze_cifs([demo_inputs], output, include_excel=False)

    assert (output / "user.txt").read_text(encoding="utf-8") == "keep"
    assert not list(tmp_path.glob(".raced-target.diffractscout-*"))


def test_remote_provider_is_not_contacted_when_output_is_unsafe(tmp_path: Path) -> None:
    class Provider:
        name = "not-called"

        def search_subsystem(self, *_args, **_kwargs):
            raise AssertionError("provider should not be contacted")

        def download_candidates(self, *_args, **_kwargs):
            raise AssertionError("provider should not be contacted")

        def metadata(self):
            raise AssertionError("provider should not be contacted")

    output = tmp_path / "occupied"
    output.mkdir()
    (output / "user.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        run_pipeline("Ti-Al", Provider(), output)
    assert (output / "user.txt").read_text(encoding="utf-8") == "keep"
