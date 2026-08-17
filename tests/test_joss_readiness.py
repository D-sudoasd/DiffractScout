from __future__ import annotations

from datetime import date
import importlib.util
import json
import os
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
            "public_since": "2026-08-12",
            "note": "Public repository creation date verified from GitHub.",
        },
        "archived_releases": [],
        "public_development_activity": [],
        "research_use_cases": [],
        "independent_validations": [],
        "external_engagement": [],
        "publications_or_preprints": [],
        "presentations_or_training": [],
        "submission_metadata": {
            "authors_confirmed": False,
            "affiliations_confirmed": False,
            "funding_confirmed": False,
            "contributors_confirmed": False,
            "related_publications_confirmed": False,
            "human_review_confirmed": False,
            "remote_ci_confirmed": False,
            "remote_ci_url": "",
            "remote_ci_commit": "",
            "official_joss_build_confirmed": False,
            "official_joss_build_url": "",
            "official_joss_build_commit": "",
            "paper_source_sha256": "",
            "paper_pdf_sha256": "",
            "note": "pending human confirmation",
        },
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
        "software_version": "0.4.0",
        "claim_supported": "comparison",
    }
    payload["research_use_cases"] = [record, dict(record)]
    errors = READINESS.validate_evidence_payload(payload)
    assert any("public HTTPS URL" in item for item in errors)


def test_independent_validation_requires_a_supported_domain() -> None:
    payload = _valid_payload()
    payload["independent_validations"] = [
        {
            "date": "2027-01-01",
            "title": "Comparison",
            "url": "https://example.org/validation",
            "software_version": "0.4.0",
            "claim_supported": "comparison",
        }
    ]

    errors = READINESS.validate_evidence_payload(payload)

    assert any("validation_type" in item for item in errors)


def test_evidence_payload_requires_complete_submission_metadata_structure() -> None:
    missing = _valid_payload()
    missing.pop("submission_metadata")
    malformed = _valid_payload()
    malformed["submission_metadata"] = {
        "authors_confirmed": "yes",
        "paper_source_sha256": "not-a-digest",
    }

    missing_errors = READINESS.validate_evidence_payload(missing)
    malformed_errors = READINESS.validate_evidence_payload(malformed)

    assert "submission_metadata must be an object." in missing_errors
    assert any("authors_confirmed must be a boolean" in item for item in malformed_errors)
    assert any("funding_confirmed is required" in item for item in malformed_errors)
    assert any("paper_source_sha256 must be empty or a SHA-256" in item for item in malformed_errors)


def test_custom_evidence_validation_matches_closed_schema_boundaries() -> None:
    payload = _valid_payload()
    payload["unexpected"] = True
    metadata = payload["submission_metadata"]
    assert isinstance(metadata, dict)
    metadata["unexpected"] = True
    payload["archived_releases"] = [
        {
            "date": "2027-03-01",
            "title": "Archive",
            "url": "https://doi.org/10.5281/zenodo.1",
            "software_version": "0.4.0",
            "claim_supported": "archive",
            "tag": "release-four",
            "commit_sha": "not-hex",
            "doi": "10.5281/zenodo.1",
        }
    ]

    errors = READINESS.validate_evidence_payload(payload)

    assert "Unexpected top-level field: unexpected." in errors
    assert "submission_metadata.unexpected is not allowed." in errors
    assert any("tag must begin with a semantic version" in item for item in errors)
    assert any("commit_sha must contain 7 to 40 hex" in item for item in errors)


def test_hashed_report_path_must_use_schema_relative_form(tmp_path: Path, monkeypatch) -> None:
    case_root = tmp_path / "validation_cases"
    case_root.mkdir()
    report = case_root / "case.md"
    report.write_text("case", encoding="utf-8")
    monkeypatch.setattr(READINESS, "ROOT", tmp_path)
    record = {
        "report_path": str(report),
        "report_sha256": READINESS._sha256(report),
    }
    errors: list[str] = []

    READINESS._validate_hashed_report(record, "case", errors)

    assert errors == ["case.report_path must match validation_cases/... using '/'."]


def test_distributed_activity_uses_public_ledger_urls_not_local_git_history() -> None:
    payload = _valid_payload()
    payload["public_development_activity"] = [
        {
            "date": f"2026-{month:02d}-20",
            "title": f"Month {month}",
            "url": f"https://github.com/D-sudoasd/DiffractScout/issues/{month}",
            "software_version": "0.4.0",
            "claim_supported": "distributed public development",
        }
        for month in range(8, 13)
    ]

    snapshot = READINESS._public_development_snapshot(
        payload,
        public_since=date(2026, 8, 12),
        as_of=date(2027, 2, 15),
    )

    assert snapshot["active_month_count"] == 5
    payload["public_development_activity"][0]["url"] = "https://example.org/private-copy"
    assert any(
        "canonical public repository" in item
        for item in READINESS.validate_evidence_payload(payload)
    )


def test_placeholder_research_evidence_cannot_satisfy_integrity_gate() -> None:
    payload = _valid_payload()
    common = {
        "date": "2027-01-10",
        "title": "Placeholder",
        "url": "https://example.org/placeholder",
        "software_version": "0.4.0",
        "claim_supported": "claim",
    }
    payload["research_use_cases"] = [dict(common)]
    payload["independent_validations"] = [
        {**common, "url": "https://example.org/diffraction", "validation_type": "diffraction"},
        {**common, "url": "https://example.org/elasticity", "validation_type": "elasticity"},
    ]
    payload["external_engagement"] = [
        {**common, "url": "https://example.org/engagement"}
    ]

    errors = READINESS.validate_evidence_payload(payload)

    assert any("research_use_cases[0].report_path is required" in item for item in errors)
    assert any("independent_validations[0].tolerance_basis is required" in item for item in errors)
    assert any("independent_validations[1].tensor_frame is required" in item for item in errors)
    assert any("external_engagement[0].commands_run is required" in item for item in errors)


def test_external_attribution_requires_consent_but_anonymous_record_does_not() -> None:
    common = {
        "date": "2027-01-10",
        "title": "External installation",
        "url": "https://github.com/D-sudoasd/DiffractScout/issues/100",
        "software_version": "0.4.0",
        "claim_supported": "external clean installation",
        "status": "complete",
        "engagement_type": "installation",
        "installation_artifact": "v0.4.0 wheel",
        "commands_run": "install, demo, verify",
        "verification_result": "PASS",
        "outcome": "documentation improvement",
        "limitations": "one environment",
        "consent_confirmed": False,
    }
    anonymous = _valid_payload()
    anonymous["external_engagement"] = [dict(common)]
    attributed = _valid_payload()
    attributed["external_engagement"] = [{**common, "people": ["External user"]}]

    assert READINESS.validate_evidence_payload(anonymous) == []
    assert any(
        "must be true when people are attributed" in item
        for item in READINESS.validate_evidence_payload(attributed)
    )


def test_paper_pdf_requires_official_confirmation_and_matching_hashes() -> None:
    payload = _valid_payload()
    initial = READINESS._paper_pdf_metadata(payload)
    assert initial["ok"] is False
    metadata = payload["submission_metadata"]
    assert isinstance(metadata, dict)
    metadata["official_joss_build_confirmed"] = True
    metadata["paper_source_sha256"] = initial["source_sha256"]
    metadata["paper_pdf_sha256"] = initial["pdf_sha256"]

    matching = READINESS._paper_pdf_metadata(payload)
    assert matching["ok"] is True

    metadata["paper_source_sha256"] = "0" * 64
    stale = READINESS._paper_pdf_metadata(payload)
    assert stale["ok"] is False
    assert stale["hashes_match"] is False


def test_readiness_report_calculates_six_month_date_without_claiming_readiness() -> None:
    report = READINESS.build_report(
        public_since=date(2026, 8, 12),
        as_of=date(2027, 2, 12),
        stage="submission",
    )
    assert report["earliest_calendar_eligibility"] == "2027-02-12"
    assert report["ready"] is False
    assert report["paper"]["missing_required_sections"] == []
    assert report["stage"] == "submission"


def test_release_stage_does_not_require_submission_or_archive_evidence(monkeypatch) -> None:
    monkeypatch.setattr(READINESS, "_release_acceptance", lambda version: {"ok": True})
    report = READINESS.build_report(
        public_since=date(2026, 8, 12),
        as_of=date(2026, 8, 12),
        stage="release",
    )

    assert report["ready"] is True
    assert report["stage_statuses"]["release"]["ready"] is True
    assert report["stage_statuses"]["submission"]["ready"] is False
    assert report["stage_statuses"]["publication"]["ready"] is False
    assert all(
        item["name"] != "Archived tagged release" or item["blocking"] is False
        for item in report["checks"]
    )


def test_author_orcid_is_a_submission_gate_not_a_release_gate(monkeypatch) -> None:
    monkeypatch.setattr(READINESS, "_release_acceptance", lambda version: {"ok": True})
    monkeypatch.setattr(
        READINESS,
        "_citation_metadata",
        lambda: {
            "version": "0.4.0",
            "repository_code": "https://github.com/D-sudoasd/DiffractScout",
            "orcids": [],
            "dois": [],
        },
    )

    release = READINESS.build_report(
        public_since=date(2026, 8, 12),
        as_of=date(2026, 8, 12),
        stage="release",
    )

    assert release["ready"] is True
    author_check = next(
        item for item in release["checks"] if item["name"] == "Author citation metadata"
    )
    assert author_check["status"] == "block"
    assert author_check["blocking"] is False


def test_publication_archive_must_match_version_tag_commit_and_citation_doi() -> None:
    evidence = {
        "tag": "v0.4.0",
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "doi": "10.5281/zenodo.1234567",
        "software_version": "0.4.0",
    }
    citation = {"version": "0.4.0", "dois": ["10.5281/zenodo.1234567"]}
    git_state = {
        "head_sha": "0123456789abcdef0123456789abcdef01234567",
        "tag_commits": {
            "v0.4.0": "0123456789abcdef0123456789abcdef01234567"
        },
    }

    matching = READINESS.evaluate_archived_release(
        [evidence], citation=citation, git_state=git_state
    )
    mismatched = READINESS.evaluate_archived_release(
        [{**evidence, "commit_sha": "f" * 40}],
        citation=citation,
        git_state=git_state,
    )

    assert matching["ok"] is True
    assert matching["errors"] == []
    assert mismatched["ok"] is False
    assert any("commit" in error.lower() for error in mismatched["errors"])


def test_readiness_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--as-of",
            "2026-08-12",
            "--stage",
            "submission",
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
    payload = json.loads((tmp_path / "joss_readiness.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "joss_readiness.md").read_text(encoding="utf-8")
    assert payload["stage"] == "submission"
    assert set(payload["stage_statuses"]) == {"release", "submission", "publication"}
    assert "Selected stage: `submission`" in markdown


def test_readiness_cli_strict_exit_depends_on_selected_stage(tmp_path: Path) -> None:
    environment = dict(**os.environ)
    environment["DIFFRACTSCOUT_RELEASE_ACCEPTANCE"] = str(tmp_path / "missing-receipt.json")
    release = subprocess.run(
        [sys.executable, str(SCRIPT), "--stage", "release", "--strict"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        env=environment,
    )
    submission = subprocess.run(
        [sys.executable, str(SCRIPT), "--stage", "submission", "--strict"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        env=environment,
    )

    assert release.returncode == 2
    assert submission.returncode == 2


def test_release_acceptance_binds_all_checks_and_current_source(tmp_path: Path, monkeypatch) -> None:
    fingerprint = READINESS.release_source_fingerprint()
    assert fingerprint["ok"] is True
    receipt = tmp_path / "release_acceptance.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "diffractscout_release_acceptance_v1",
                "version": "0.4.0",
                "source_sha256": fingerprint["sha256"],
                "checks": {
                    "docs": True,
                    "compile": True,
                    "tests": True,
                    "demo": True,
                    "verify": True,
                    "benchmark": True,
                    "wheel": True,
                    "sdist": True,
                    "twine": True,
                    "clean_wheel": True,
                },
                "clean_wheel": {
                    "mode": "isolated-dependencies",
                    "package": "dist/diffractscout-0.4.0-py3-none-any.whl",
                    "source_tree_import": "rejected",
                    "commands": "pip-check,demo,verify,benchmark,quick-export,verify",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DIFFRACTSCOUT_RELEASE_ACCEPTANCE", str(receipt))

    assert READINESS._release_acceptance("0.4.0")["ok"] is True
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["checks"]["twine"] = False
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert READINESS._release_acceptance("0.4.0")["ok"] is False


def test_release_acceptance_rejects_unproven_clean_wheel(tmp_path: Path, monkeypatch) -> None:
    fingerprint = READINESS.release_source_fingerprint()
    receipt = tmp_path / "release_acceptance.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "diffractscout_release_acceptance_v1",
                "version": "0.4.0",
                "source_sha256": fingerprint["sha256"],
                "checks": {
                    "docs": True,
                    "compile": True,
                    "tests": True,
                    "demo": True,
                    "verify": True,
                    "benchmark": True,
                    "wheel": True,
                    "sdist": True,
                    "twine": True,
                    "clean_wheel": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DIFFRACTSCOUT_RELEASE_ACCEPTANCE", str(receipt))

    result = READINESS._release_acceptance("0.4.0")

    assert result["ok"] is False
    assert any("Clean-wheel evidence is missing" in item for item in result["errors"])


def test_release_fingerprint_ignores_generated_untracked_outputs(tmp_path: Path) -> None:
    before = READINESS.release_source_fingerprint()
    generated_dir = READINESS.ROOT / "release_demo"
    generated = generated_dir / "manifest.json"
    assert not generated_dir.exists()
    try:
        generated_dir.mkdir()
        generated.write_text("generated workflow artifact", encoding="utf-8")
        after = READINESS.release_source_fingerprint()
    finally:
        generated.unlink(missing_ok=True)
        generated_dir.rmdir()

    assert before["ok"] is True
    assert after["sha256"] == before["sha256"]


def test_release_fingerprint_includes_non_ignored_untracked_source() -> None:
    before = READINESS.release_source_fingerprint()
    source = READINESS.ROOT / "release_receipt_source_test.txt"
    assert not source.exists()
    try:
        source.write_text("intended untracked release input", encoding="utf-8")
        after = READINESS.release_source_fingerprint()
    finally:
        source.unlink(missing_ok=True)

    assert before["ok"] is True
    assert after["sha256"] != before["sha256"]


def test_tracked_source_cleanliness_reports_non_ignored_untracked_work() -> None:
    source = READINESS.ROOT / "submission_source_identity_test.txt"
    assert not source.exists()
    try:
        source.write_text("uncommitted submission source", encoding="utf-8")
        state = READINESS.tracked_source_is_clean()
    finally:
        source.unlink(missing_ok=True)

    assert state["ok"] is False
    assert "submission_source_identity_test.txt" in state["paths"]


def test_submission_stage_blocks_a_dirty_source_even_with_other_gates_stubbed(monkeypatch) -> None:
    monkeypatch.setattr(READINESS, "_release_acceptance", lambda version: {"ok": True})
    dirty = READINESS.ROOT / "submission_source_identity_stage_test.txt"
    assert not dirty.exists()
    try:
        dirty.write_text("uncommitted submission source", encoding="utf-8")
        report = READINESS.build_report(
            public_since=date(2026, 8, 12),
            as_of=date(2027, 2, 15),
            stage="submission",
        )
    finally:
        dirty.unlink(missing_ok=True)

    source = next(item for item in report["checks"] if item["name"] == "Submission source identity")
    assert source["status"] == "block"
    assert source["blocking"] is True
    assert "submission_source_identity_stage_test.txt" in source["evidence"]["paths"]


def test_public_since_override_cannot_backdate_the_ledger(monkeypatch) -> None:
    monkeypatch.setattr(READINESS, "_release_acceptance", lambda version: {"ok": True})

    report = READINESS.build_report(
        public_since=date(2020, 1, 1),
        as_of=date(2027, 2, 15),
        stage="release",
    )

    assert report["public_since"] == "2026-08-12"
    integrity = next(
        item for item in report["checks"] if item["name"] == "Public repository date integrity"
    )
    assert integrity["status"] == "block"
    assert report["ready"] is False


def test_publication_cli_is_strict_and_non_strict_remains_zero() -> None:
    strict = subprocess.run(
        [sys.executable, str(SCRIPT), "--stage", "publication", "--strict"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    non_strict = subprocess.run(
        [sys.executable, str(SCRIPT), "--stage", "publication", "--json"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert strict.returncode == 2
    assert non_strict.returncode == 0
    assert json.loads(non_strict.stdout)["stage"] == "publication"
