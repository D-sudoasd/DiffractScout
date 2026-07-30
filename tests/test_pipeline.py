import csv
from pathlib import Path

from openpyxl import load_workbook

from diffractscout.pipeline import analyze_cifs
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
    from diffractscout.models import AnalysisSettings

    output = tmp_path / "no-elasticity"
    result = analyze_cifs(
        [demo_inputs],
        output,
        settings=AnalysisSettings(include_elasticity=False),
        include_excel=False,
    )
    assert len(result.analyses) == 1
    assert result.analyses[0].elastic_tensor is None
    assert not list((output / "inputs").glob("*_elasticity.json"))


def test_input_output_overlap_is_rejected_before_writes(demo_inputs: Path) -> None:
    output = demo_inputs / "nested-result"
    try:
        analyze_cifs([demo_inputs], output, include_excel=False)
    except ValueError as exc:
        assert "must be disjoint" in str(exc)
    else:
        raise AssertionError("Expected overlapping input/output paths to be rejected")
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
