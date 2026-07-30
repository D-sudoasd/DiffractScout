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
