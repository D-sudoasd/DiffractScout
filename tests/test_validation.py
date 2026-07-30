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
