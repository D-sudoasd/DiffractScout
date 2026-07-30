from pathlib import Path

from diffractscout.pipeline import analyze_cifs
from diffractscout.validation import verify_bundle


def test_tamper_is_detected(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    analyze_cifs([demo_inputs], output, include_excel=False)
    assert verify_bundle(output)["ok"]
    with (output / "phase_summary.csv").open("a", encoding="utf-8") as handle:
        handle.write("tamper\n")
    report = verify_bundle(output)
    assert not report["ok"]
    assert any("hash mismatch" in error for error in report["errors"])


def test_unlisted_file_is_detected(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle-unlisted"
    analyze_cifs([demo_inputs], output, include_excel=False)
    (output / "unlisted.txt").write_text("extra", encoding="utf-8")
    report = verify_bundle(output)
    assert not report["ok"]
    assert "unexpected unlisted file: unlisted.txt" in report["errors"]


def test_malformed_manifest_size_is_reported_without_crash(demo_inputs: Path, tmp_path: Path) -> None:
    import json

    output = tmp_path / "bundle-malformed"
    analyze_cifs([demo_inputs], output, include_excel=False)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["size_bytes"] = "not-an-integer"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = verify_bundle(output)
    assert not report["ok"]
    assert any("invalid size_bytes" in error for error in report["errors"])


def test_duplicate_manifest_path_is_rejected(demo_inputs: Path, tmp_path: Path) -> None:
    import json

    output = tmp_path / "bundle-duplicate"
    analyze_cifs([demo_inputs], output, include_excel=False)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(dict(manifest["files"][0]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = verify_bundle(output)
    assert not report["ok"]
    assert any("duplicate manifest path" in error for error in report["errors"])
