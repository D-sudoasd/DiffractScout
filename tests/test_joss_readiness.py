from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/joss_readiness.py"
SPEC = importlib.util.spec_from_file_location("diffractscout_joss_readiness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
READINESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READINESS)


def _valid_payload() -> dict[str, object]:
    return {
        "schema": "diffractscout_joss_evidence_v1",
        "public_repository": {
            "url": "https://github.com/D-sudoasd/DiffractScout",
            "public_since": None,
            "note": "not public yet",
        },
        "archived_releases": [],
        "research_use_cases": [],
        "independent_validations": [],
        "external_engagement": [],
        "publications_or_preprints": [],
        "presentations_or_training": [],
    }


def test_add_calendar_months_handles_month_end_and_leap_year() -> None:
    assert READINESS.add_calendar_months(date(2026, 8, 12), 6) == date(2027, 2, 12)
    assert READINESS.add_calendar_months(date(2023, 8, 31), 6) == date(2024, 2, 29)


def test_evidence_payload_validation_accepts_empty_honest_ledger() -> None:
    assert READINESS.validate_evidence_payload(_valid_payload()) == []


def test_evidence_payload_validation_rejects_untraceable_and_duplicate_records() -> None:
    payload = _valid_payload()
    record = {
        "date": "2027-01-01",
        "title": "Validation",
        "url": "http://example.invalid/report",
        "software_version": "0.3.0",
        "claim_supported": "comparison",
    }
    payload["research_use_cases"] = [record, dict(record)]
    errors = READINESS.validate_evidence_payload(payload)
    assert any("public HTTPS URL" in item for item in errors)


def test_readiness_report_calculates_six_month_date_without_claiming_readiness() -> None:
    report = READINESS.build_report(
        public_since=date(2026, 8, 12),
        as_of=date(2027, 2, 12),
    )
    assert report["earliest_calendar_eligibility"] == "2027-02-12"
    assert report["ready"] is False
    assert report["paper"]["missing_required_sections"] == []


def test_readiness_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--as-of",
            "2026-08-12",
            "--output",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0
    assert (tmp_path / "joss_readiness.json").is_file()
    assert (tmp_path / "joss_readiness.md").is_file()
    assert "BLOCKED" in completed.stdout
