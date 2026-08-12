from pathlib import Path

import pytest

from diffractscout.cli import _pipeline_exit_code, main
from diffractscout.models import DiagnosticRecord
from diffractscout.validation import verify_bundle


def test_demo_cli(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    assert main(["demo", "-o", str(output), "--no-excel"]) == 0
    assert verify_bundle(output)["ok"]


def test_cli_rejects_conflicting_radiation_inputs(tmp_path: Path) -> None:
    output = tmp_path / "conflicting-radiation"
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "analyze",
                str(tmp_path),
                "-o",
                str(output),
                "--energy-keV",
                "20",
                "--wavelength-A",
                "1.0",
            ]
        )
    assert exc_info.value.code == 2
    assert not output.exists()


def test_partial_batch_has_distinct_exit_code() -> None:
    class Result:
        analyses = [object()]
        diagnostics = [DiagnosticRecord("analysis", "bad.cif", "error", "failed")]

    assert _pipeline_exit_code(Result()) == 3
