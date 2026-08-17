#!/usr/bin/env python3
"""Generate reproducible release, JOSS submission, and publication readiness.

The script separates objective repository checks from time-dependent and
evidence-dependent submission gates. It never rewrites Git history and does not
infer that local commits were publicly visible.
"""

from __future__ import annotations

import argparse
import calendar
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "docs/evidence/impact_evidence.json"

STAGES = ("release", "submission", "publication")
STAGE_ORDER = {name: index for index, name in enumerate(STAGES)}

EVIDENCE_CATEGORIES = (
    "archived_releases",
    "public_development_activity",
    "research_use_cases",
    "independent_validations",
    "external_engagement",
    "publications_or_preprints",
    "presentations_or_training",
)

SUBMISSION_CONFIRMATIONS = (
    "authors_confirmed",
    "affiliations_confirmed",
    "funding_confirmed",
    "contributors_confirmed",
    "related_publications_confirmed",
    "human_review_confirmed",
    "remote_ci_confirmed",
    "official_joss_build_confirmed",
)

SUBMISSION_TEXT_FIELDS = (
    "remote_ci_url",
    "remote_ci_commit",
    "official_joss_build_url",
    "official_joss_build_commit",
    "paper_source_sha256",
    "paper_pdf_sha256",
    "note",
)

TOP_LEVEL_EVIDENCE_FIELDS = {
    "schema",
    "public_repository",
    *EVIDENCE_CATEGORIES,
    "submission_metadata",
}

DEFAULT_RELEASE_ACCEPTANCE_PATH = ROOT / "build/release-preflight/release_acceptance.json"

REQUIRED_PAPER_SECTIONS = (
    "Summary",
    "Statement of need",
    "State of the field",
    "Software design",
    "Research impact statement",
    "AI usage disclosure",
    "Acknowledgements",
    "References",
)

REQUIRED_REPOSITORY_FILES = (
    "LICENSE",
    "README.md",
    "CITATION.cff",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "GOVERNANCE.md",
    "SUPPORT.md",
    "ROADMAP.md",
    "CHANGELOG.md",
    "docs/SCIENTIFIC_CONTRACTS.md",
    "docs/VALIDATION.md",
    "docs/JOSS_6_MONTH_PLAN.md",
    "docs/ADOPTION_AND_IMPACT.md",
    "docs/VALIDATION_CASE_TEMPLATE.md",
    "docs/ANALYTIC_BENCHMARKS.md",
    "docs/JOSS_REVIEW_CHECKLIST.md",
    "validation_cases/README.md",
    "validation_cases/analytic_reference_v1/README.md",
    "validation_cases/real_multiphase_case/README.md",
    "docs/evidence/README.md",
    "docs/evidence/impact_evidence.json",
    "docs/evidence/impact_evidence.schema.json",
    "scripts/joss_readiness.py",
    "scripts/check_docs.py",
    "scripts/archive_tree.py",
    "paper/paper.md",
    "paper/paper.pdf",
    "paper/paper.bib",
    "paper/fig_workflow.png",
    "paper/fig_validation.png",
    "paper/make_figures.py",
    "paper/build_local.sh",
    "paper/README.md",
    ".github/workflows/ci.yml",
    ".github/workflows/draft-pdf.yml",
    ".github/workflows/release.yml",
    ".github/workflows/monthly-audit.yml",
    ".github/dependabot.yml",
)


def add_calendar_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _run_git(*args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _git_history(public_since: date | None, as_of: date) -> dict[str, Any]:
    try:
        raw = _run_git("log", "--format=%H%x09%aI%x09%an")
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"available": False, "error": str(exc), "commits": []}
    commits: list[dict[str, str]] = []
    assert isinstance(raw, str)
    for line in raw.splitlines():
        if not line.strip():
            continue
        sha, timestamp, author = line.split("\t", 2)
        commit_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
        if commit_date > as_of:
            continue
        commits.append(
            {"sha": sha, "date": commit_date.isoformat(), "author": author}
        )
    public_commits = [
        item
        for item in commits
        if public_since is not None and date.fromisoformat(item["date"]) >= public_since
    ]
    active_months = Counter(item["date"][:7] for item in public_commits)
    try:
        raw_tags = _run_git("tag", "--list")
        assert isinstance(raw_tags, str)
        tags = [item for item in raw_tags.splitlines() if item]
    except (OSError, subprocess.CalledProcessError):
        tags = []
    return {
        "available": True,
        "total_local_commits": len(commits),
        "commits_on_or_after_public_date": len(public_commits),
        "active_months": dict(sorted(active_months.items())),
        "active_month_count": len(active_months),
        "authors": sorted({item["author"] for item in public_commits}),
        "tags": tags,
        "first_local_commit": commits[-1]["date"] if commits else None,
        "latest_local_commit": commits[0]["date"] if commits else None,
        "limitation": (
            "Commit timestamps do not prove that commits were publicly visible. "
            "Confirm public availability from the GitHub repository timeline."
        ),
    }


def _git_release_state() -> dict[str, Any]:
    """Return local release identity without claiming remote publication."""

    try:
        head_sha = _run_git("rev-parse", "HEAD")
        raw_tags = _run_git("tag", "--list")
        assert isinstance(head_sha, str) and isinstance(raw_tags, str)
        tags = [item for item in raw_tags.splitlines() if item]
        tag_commits = {tag: _run_git("rev-list", "-n", "1", tag) for tag in tags}
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"available": False, "error": str(exc), "head_sha": None, "tag_commits": {}}
    return {
        "available": True,
        "head_sha": head_sha,
        "tag_commits": dict(sorted(tag_commits.items())),
        "limitation": "Local tags do not prove that a GitHub Release or immutable archive exists.",
    }


def release_source_fingerprint() -> dict[str, Any]:
    """Hash tracked and non-ignored release inputs using current content."""

    try:
        raw = _run_git("ls-files", "-co", "--exclude-standard", "-z", text=False)
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"ok": False, "error": str(exc), "sha256": None, "file_count": 0}
    assert isinstance(raw, bytes)
    relative_paths = sorted(
        {
            os.fsdecode(item)
            for item in raw.split(b"\0")
            if item
        }
    )
    digest = hashlib.sha256()
    file_count = 0
    missing: list[str] = []
    for relative in relative_paths:
        path = ROOT / relative
        encoded_path = relative.replace("\\", "/").encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        if not path.is_file():
            digest.update(b"MISSING")
            missing.append(relative)
            continue
        digest.update(_sha256(path).encode("ascii"))
        file_count += 1
    return {
        "ok": not missing,
        "sha256": digest.hexdigest(),
        "file_count": file_count,
        "missing": missing,
        "scope": "Git-tracked plus non-ignored untracked files using current content",
    }


def tracked_source_is_clean() -> dict[str, Any]:
    """Require a committed/indexed release identity before remote tag workflows."""

    try:
        unstaged_raw = _run_git("diff", "--name-only", "-z", text=False)
        staged_raw = _run_git("diff", "--cached", "--name-only", "-z", text=False)
        untracked_raw = _run_git(
            "ls-files", "--others", "--exclude-standard", "-z", text=False
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"ok": False, "error": str(exc), "paths": []}
    assert isinstance(unstaged_raw, bytes)
    assert isinstance(staged_raw, bytes)
    assert isinstance(untracked_raw, bytes)
    paths = sorted(
        {
            os.fsdecode(item).replace("\\", "/")
            for raw in (unstaged_raw, staged_raw, untracked_raw)
            for item in raw.split(b"\0")
            if item
        }
    )
    return {"ok": not paths, "paths": paths}


def _release_acceptance(version: str | None) -> dict[str, Any]:
    configured = os.environ.get("DIFFRACTSCOUT_RELEASE_ACCEPTANCE", "").strip()
    path = Path(configured).expanduser().resolve() if configured else DEFAULT_RELEASE_ACCEPTANCE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "path": str(path), "error": str(exc)}
    fingerprint = release_source_fingerprint()
    source_clean = tracked_source_is_clean()
    checks = payload.get("checks") if isinstance(payload, dict) else None
    required_checks = (
        "docs",
        "compile",
        "tests",
        "demo",
        "verify",
        "benchmark",
        "wheel",
        "sdist",
        "twine",
        "clean_wheel",
    )
    failed_checks = [name for name in required_checks if not isinstance(checks, dict) or checks.get(name) is not True]
    errors: list[str] = []
    if payload.get("schema") != "diffractscout_release_acceptance_v1":
        errors.append("Unknown release-acceptance schema.")
    if payload.get("version") != version:
        errors.append("Acceptance version does not match package version.")
    if not fingerprint.get("ok") or payload.get("source_sha256") != fingerprint.get("sha256"):
        errors.append("Acceptance source fingerprint does not match the current worktree.")
    if os.environ.get("GITHUB_ACTIONS") == "true" and not source_clean.get("ok"):
        errors.append("GitHub release acceptance requires a clean tagged checkout.")
    if failed_checks:
        errors.append("Acceptance checks not proven: " + ", ".join(failed_checks) + ".")
    clean_wheel = payload.get("clean_wheel")
    if not isinstance(clean_wheel, dict):
        errors.append("Clean-wheel evidence is missing from the acceptance receipt.")
    else:
        if clean_wheel.get("mode") not in {"isolated-dependencies", "system-site-packages"}:
            errors.append("Clean-wheel mode is invalid.")
        if clean_wheel.get("source_tree_import") != "rejected":
            errors.append("Clean-wheel evidence does not reject source-tree imports.")
        required_commands = {"pip-check", "demo", "verify", "benchmark", "quick-export"}
        commands = {
            item.strip()
            for item in str(clean_wheel.get("commands") or "").split(",")
            if item.strip()
        }
        if not required_commands.issubset(commands):
            errors.append("Clean-wheel evidence is missing required smoke commands.")
        package = Path(str(clean_wheel.get("package") or ""))
        if package.name != f"diffractscout-{version}-py3-none-any.whl":
            errors.append("Clean-wheel artifact does not match the release version.")
    return {
        "ok": not errors,
        "path": str(path),
        "errors": errors,
        "failed_checks": failed_checks,
        "recorded": payload,
        "current_source": fingerprint,
        "source_clean": source_clean,
    }


def _load_evidence() -> dict[str, Any]:
    try:
        payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"schema": "invalid", "error": str(exc)}
    return payload if isinstance(payload, dict) else {"schema": "invalid"}


def _is_public_https_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def _require_text(record: dict[str, Any], prefix: str, keys: tuple[str, ...], errors: list[str]) -> None:
    for key in keys:
        if not str(record.get(key, "")).strip():
            errors.append(f"{prefix}.{key} is required.")


def _validate_hashed_report(record: dict[str, Any], prefix: str, errors: list[str]) -> None:
    """Bind completed evidence to a versioned report in validation_cases/."""

    raw_relative = str(record.get("report_path", "")).strip()
    relative = raw_relative.replace("\\", "/")
    expected = record.get("report_sha256")
    if not relative:
        errors.append(f"{prefix}.report_path is required.")
        return
    if not raw_relative.startswith("validation_cases/") or "\\" in raw_relative:
        errors.append(f"{prefix}.report_path must match validation_cases/... using '/'.")
        return
    if not _is_sha256(expected):
        errors.append(f"{prefix}.report_sha256 must be a SHA-256 digest.")
        return
    path = (ROOT / relative).resolve()
    try:
        path.relative_to((ROOT / "validation_cases").resolve())
    except ValueError:
        errors.append(f"{prefix}.report_path must stay within validation_cases/.")
        return
    if not path.is_file():
        errors.append(f"{prefix}.report_path does not exist: {relative}.")
        return
    if _sha256(path).lower() != str(expected).lower():
        errors.append(f"{prefix}.report_sha256 does not match {relative}.")


def validate_evidence_payload(payload: dict[str, Any]) -> list[str]:
    """Return structural errors in the machine-readable impact ledger.

    This intentionally avoids inferring impact from counts. It only checks that
    records are traceable, dated, versioned, and sufficiently specific to audit.
    """

    errors: list[str] = []
    missing_top_level = TOP_LEVEL_EVIDENCE_FIELDS - set(payload)
    unexpected_top_level = set(payload) - TOP_LEVEL_EVIDENCE_FIELDS
    for key in sorted(missing_top_level):
        errors.append(f"Top-level field {key} is required.")
    for key in sorted(unexpected_top_level):
        errors.append(f"Unexpected top-level field: {key}.")
    if payload.get("schema") != "diffractscout_joss_evidence_v1":
        errors.append("Unknown or missing evidence schema.")

    repository = payload.get("public_repository")
    if not isinstance(repository, dict):
        errors.append("public_repository must be an object.")
    else:
        allowed_repository_fields = {"url", "public_since", "note"}
        for key in sorted(set(repository) - allowed_repository_fields):
            errors.append(f"public_repository.{key} is not allowed.")
        for key in sorted(allowed_repository_fields - set(repository)):
            errors.append(f"public_repository.{key} is required.")
        if not _is_public_https_url(repository.get("url")):
            errors.append("public_repository.url must be a public HTTPS URL.")
        public_since = repository.get("public_since")
        if public_since not in (None, ""):
            try:
                date.fromisoformat(str(public_since))
            except ValueError:
                errors.append("public_repository.public_since must be an ISO date or null.")

    seen_urls: set[str] = set()
    for category in EVIDENCE_CATEGORIES:
        records = payload.get(category)
        if not isinstance(records, list):
            errors.append(f"{category} must be an array.")
            continue
        for index, record in enumerate(records):
            prefix = f"{category}[{index}]"
            if not isinstance(record, dict):
                errors.append(f"{prefix} must be an object.")
                continue
            for key in ("date", "title", "url", "software_version", "claim_supported"):
                if not str(record.get(key, "")).strip():
                    errors.append(f"{prefix}.{key} is required.")
            try:
                date.fromisoformat(str(record.get("date", "")))
            except ValueError:
                errors.append(f"{prefix}.date must be an ISO date.")
            url = str(record.get("url", "")).strip()
            if url and not _is_public_https_url(url):
                errors.append(f"{prefix}.url must be a public HTTPS URL.")
            elif url in seen_urls:
                errors.append(f"{prefix}.url duplicates another evidence record.")
            elif url:
                seen_urls.add(url)
            if category == "archived_releases":
                for key in ("tag", "commit_sha", "doi"):
                    if not str(record.get(key, "")).strip():
                        errors.append(f"{prefix}.{key} is required for archived releases.")
                doi = str(record.get("doi", "")).strip()
                if doi and not doi.startswith("10."):
                    errors.append(f"{prefix}.doi must be a DOI beginning with '10.'.")
                tag = str(record.get("tag", "")).strip()
                if tag and re.match(r"^v?[0-9]+\.[0-9]+\.[0-9]+", tag) is None:
                    errors.append(f"{prefix}.tag must begin with a semantic version.")
                commit_sha = str(record.get("commit_sha", "")).strip()
                if commit_sha and re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_sha) is None:
                    errors.append(f"{prefix}.commit_sha must contain 7 to 40 hex characters.")
            if category == "independent_validations":
                validation_type = str(record.get("validation_type", "")).strip()
                if validation_type not in {"diffraction", "elasticity"}:
                    errors.append(
                        f"{prefix}.validation_type must be 'diffraction' or 'elasticity'."
                    )

                _require_text(
                    record,
                    prefix,
                    (
                        "status",
                        "report_path",
                        "reference_implementation",
                        "reference_version",
                        "tolerance_basis",
                        "result_sha256",
                        "diffractscout_commit",
                        "limitations",
                    ),
                    errors,
                )
                if record.get("status") != "complete":
                    errors.append(f"{prefix}.status must be 'complete'.")
                for key in ("result_sha256", "diffractscout_commit"):
                    pattern = r"[0-9a-fA-F]{64}" if key == "result_sha256" else r"[0-9a-fA-F]{40}"
                    if not re.fullmatch(pattern, str(record.get(key, ""))):
                        errors.append(f"{prefix}.{key} has an invalid digest or commit SHA.")
                if validation_type == "diffraction":
                    _require_text(
                        record,
                        prefix,
                        ("input_sha256", "radiation", "scan_range"),
                        errors,
                    )
                    if not _is_sha256(record.get("input_sha256")):
                        errors.append(f"{prefix}.input_sha256 must be a SHA-256 digest.")
                elif validation_type == "elasticity":
                    _require_text(
                        record,
                        prefix,
                        ("tensor_source", "tensor_frame", "voigt_convention"),
                        errors,
                    )
                    directions = record.get("directions")
                    if not isinstance(directions, list) or not {"[100]", "[110]", "[111]"}.issubset(
                        {str(item) for item in directions}
                    ):
                        errors.append(
                            f"{prefix}.directions must include [100], [110], and [111]."
                        )
                _validate_hashed_report(record, prefix, errors)

            if category == "research_use_cases":
                _require_text(
                    record,
                    prefix,
                    (
                        "status",
                        "report_path",
                        "research_decision",
                        "input_sha256",
                        "result_manifest_sha256",
                        "input_license",
                        "limitations",
                    ),
                    errors,
                )
                if record.get("status") != "complete":
                    errors.append(f"{prefix}.status must be 'complete'.")
                for key in ("input_sha256", "result_manifest_sha256"):
                    if not _is_sha256(record.get(key)):
                        errors.append(f"{prefix}.{key} must be a SHA-256 digest.")
                _validate_hashed_report(record, prefix, errors)

            if category == "external_engagement":
                _require_text(
                    record,
                    prefix,
                    (
                        "status",
                        "engagement_type",
                        "installation_artifact",
                        "commands_run",
                        "verification_result",
                        "outcome",
                        "limitations",
                    ),
                    errors,
                )
                if record.get("status") != "complete":
                    errors.append(f"{prefix}.status must be 'complete'.")
                if record.get("engagement_type") not in {
                    "installation",
                    "research-use",
                    "review",
                    "issue",
                    "contribution",
                }:
                    errors.append(f"{prefix}.engagement_type is unsupported.")
                consent = record.get("consent_confirmed")
                if not isinstance(consent, bool):
                    errors.append(f"{prefix}.consent_confirmed must be a boolean.")
                people = record.get("people")
                if isinstance(people, list) and people and consent is not True:
                    errors.append(
                        f"{prefix}.consent_confirmed must be true when people are attributed."
                    )

            if category == "public_development_activity" and url:
                canonical_prefix = "https://github.com/D-sudoasd/DiffractScout/"
                if not url.startswith(canonical_prefix):
                    errors.append(
                        f"{prefix}.url must identify activity in the canonical public repository."
                    )
                if record.get("activity_type") not in {"commit", "issue", "pull_request", "release"}:
                    errors.append(f"{prefix}.activity_type is unsupported.")
                if not str(record.get("outcome", "")).strip():
                    errors.append(f"{prefix}.outcome is required.")

    submission_metadata = payload.get("submission_metadata")
    if not isinstance(submission_metadata, dict):
        errors.append("submission_metadata must be an object.")
    else:
        allowed_submission_fields = {
            *SUBMISSION_CONFIRMATIONS,
            *SUBMISSION_TEXT_FIELDS,
        }
        for key in sorted(set(submission_metadata) - allowed_submission_fields):
            errors.append(f"submission_metadata.{key} is not allowed.")
        for key in SUBMISSION_CONFIRMATIONS:
            if key not in submission_metadata:
                errors.append(f"submission_metadata.{key} is required.")
            elif not isinstance(submission_metadata[key], bool):
                errors.append(f"submission_metadata.{key} must be a boolean.")
        for key in SUBMISSION_TEXT_FIELDS:
            if key not in submission_metadata:
                errors.append(f"submission_metadata.{key} is required.")
            elif not isinstance(submission_metadata[key], str):
                errors.append(f"submission_metadata.{key} must be a string.")
        for key in ("paper_source_sha256", "paper_pdf_sha256"):
            value = submission_metadata.get(key)
            if isinstance(value, str) and value and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                errors.append(f"submission_metadata.{key} must be empty or a SHA-256 digest.")
        for key in ("remote_ci_commit", "official_joss_build_commit"):
            value = submission_metadata.get(key)
            if isinstance(value, str) and value and not re.fullmatch(r"[0-9a-fA-F]{40}", value):
                errors.append(f"submission_metadata.{key} must be empty or a full commit SHA.")
    return errors


def _front_matter_removed(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def _paper_metrics() -> dict[str, Any]:
    paper_path = ROOT / "paper/paper.md"
    bibliography_path = ROOT / "paper/paper.bib"
    text = paper_path.read_text(encoding="utf-8")
    body = _front_matter_removed(text)
    sections = re.findall(r"^#\s+(.+?)\s*$", body, flags=re.MULTILINE)
    # Remove fenced code, equations, image syntax, citations, and table delimiter
    # characters before the approximate prose count. The official build remains
    # the source of truth for final editorial judgment.
    countable = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
    countable = re.sub(r"\$\$.*?\$\$", " ", countable, flags=re.DOTALL)
    countable = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", countable)
    countable = re.sub(r"\[@[^\]]+\]", " ", countable)
    countable = re.sub(r"[#|`*_<>]", " ", countable)
    words = re.findall(r"\b[\w'’-]+\b", countable, flags=re.UNICODE)

    bibliography = bibliography_path.read_text(encoding="utf-8")
    cited = set(re.findall(r"@([A-Za-z0-9_:-]+)", text))
    defined = set(re.findall(r"@[A-Za-z]+\{([^,]+),", bibliography))
    return {
        "approximate_word_count": len(words),
        "sections": sections,
        "missing_required_sections": [
            section for section in REQUIRED_PAPER_SECTIONS if section not in sections
        ],
        "undefined_citations": sorted(cited - defined),
        "word_count_target": [750, 1750],
    }


def _citation_metadata() -> dict[str, Any]:
    cff_path = ROOT / "CITATION.cff"
    text = cff_path.read_text(encoding="utf-8")
    version_match = re.search(r"^version:\s*['\"]?([^'\"\s]+)", text, flags=re.MULTILINE)
    repository_match = re.search(r"^repository-code:\s*['\"]?([^'\"\n]+)", text, flags=re.MULTILINE)
    orcid_matches = re.findall(r"^\s*orcid:\s*['\"]?([^'\"\s]+)", text, flags=re.MULTILINE)
    doi_matches = re.findall(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text)
    return {
        "version": version_match.group(1) if version_match else None,
        "repository_code": repository_match.group(1).strip() if repository_match else None,
        "orcids": orcid_matches,
        "dois": sorted(set(doi_matches)),
    }


def _version_metadata() -> dict[str, Any]:
    sources: dict[str, str | None] = {}
    patterns = {
        "pyproject.toml": r'^version\s*=\s*"([^"]+)"',
        "src/diffractscout/__init__.py": r'^__version__\s*=\s*"([^"]+)"',
        "CITATION.cff": r"^version:\s*['\"]?([^'\"\s]+)",
    }
    for relative, pattern in patterns.items():
        try:
            text = (ROOT / relative).read_text(encoding="utf-8")
        except OSError:
            sources[relative] = None
            continue
        match = re.search(pattern, text, flags=re.MULTILINE)
        sources[relative] = match.group(1) if match else None
    values = [value for value in sources.values() if value]
    return {
        "sources": sources,
        "consistent": len(values) == len(sources) and len(set(values)) == 1,
        "version": values[0] if values and len(set(values)) == 1 else None,
    }


def _license_metadata() -> dict[str, Any]:
    path = ROOT / "LICENSE"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": "MIT License" in text and "Permission is hereby granted" in text,
        "path": "LICENSE",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paper_source_sha256(source_paths: list[Path]) -> str:
    """Hash paper inputs with stable repository-relative path separators."""

    digest = hashlib.sha256()
    for source in source_paths:
        relative = source.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(_sha256(source).encode("ascii"))
    return digest.hexdigest()


def _paper_pdf_metadata(evidence: dict[str, Any]) -> dict[str, Any]:
    path = ROOT / "paper/paper.pdf"
    source_paths = [
        ROOT / "paper/paper.md",
        ROOT / "paper/paper.bib",
        ROOT / "paper/fig_workflow.png",
        ROOT / "paper/fig_validation.png",
    ]
    raw_submission = evidence.get("submission_metadata")
    submission = raw_submission if isinstance(raw_submission, dict) else {}
    try:
        header = path.read_bytes()[:4]
        size = path.stat().st_size
        missing_sources = [source for source in source_paths if not source.is_file()]
        if missing_sources:
            raise FileNotFoundError(
                "Missing paper inputs: "
                + ", ".join(source.relative_to(ROOT).as_posix() for source in missing_sources)
            )
        source_sha256 = _paper_source_sha256(source_paths)
        pdf_sha256 = _sha256(path)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    recorded_source_sha256 = str(submission.get("paper_source_sha256") or "")
    recorded_pdf_sha256 = str(submission.get("paper_pdf_sha256") or "")
    official_confirmed = submission.get("official_joss_build_confirmed") is True
    hashes_match = (
        bool(recorded_source_sha256)
        and bool(recorded_pdf_sha256)
        and recorded_source_sha256.lower() == source_sha256
        and recorded_pdf_sha256.lower() == pdf_sha256
    )
    return {
        "ok": header == b"%PDF" and size > 10_000 and official_confirmed and hashes_match,
        "path": "paper/paper.pdf",
        "bytes": size,
        "source_sha256": source_sha256,
        "pdf_sha256": pdf_sha256,
        "recorded_source_sha256": recorded_source_sha256 or None,
        "recorded_pdf_sha256": recorded_pdf_sha256 or None,
        "official_build_confirmed": official_confirmed,
        "hashes_match": hashes_match,
        "limitation": (
            "Matching hashes prove source/artifact identity but do not replace rendered-page human review."
        ),
    }


def _submission_metadata(evidence: dict[str, Any], *, current_head: str) -> dict[str, Any]:
    raw = evidence.get("submission_metadata")
    values = raw if isinstance(raw, dict) else {}
    missing_or_false = [name for name in SUBMISSION_CONFIRMATIONS if values.get(name) is not True]
    invalid_urls = [
        name
        for name in ("remote_ci_url", "official_joss_build_url")
        if not _is_public_https_url(values.get(name))
    ]
    invalid_commits = [
        name
        for name in ("remote_ci_commit", "official_joss_build_commit")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", str(values.get(name, "")))
        or str(values.get(name, "")).lower() != current_head.lower()
    ]
    return {
        "ok": not missing_or_false and not invalid_urls and not invalid_commits,
        "required_confirmations": list(SUBMISSION_CONFIRMATIONS),
        "missing_or_false": missing_or_false,
        "invalid_urls": invalid_urls,
        "invalid_or_mismatched_commits": invalid_commits,
        "current_head": current_head or None,
    }


def _public_development_snapshot(
    evidence: dict[str, Any],
    *,
    public_since: date | None,
    as_of: date,
) -> dict[str, Any]:
    """Count only ledger-linked public repository activity, never local timestamps."""

    raw_records = evidence.get("public_development_activity")
    records = raw_records if isinstance(raw_records, list) else []
    accepted: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            activity_date = date.fromisoformat(str(record.get("date", "")))
        except ValueError:
            continue
        if public_since is None or not (public_since <= activity_date <= as_of):
            continue
        url = str(record.get("url") or "")
        if not url.startswith("https://github.com/D-sudoasd/DiffractScout/"):
            continue
        accepted.append(record)
    active_months = Counter(str(record["date"])[:7] for record in accepted)
    return {
        "entries": len(accepted),
        "active_months": dict(sorted(active_months.items())),
        "active_month_count": len(active_months),
        "source": "docs/evidence/impact_evidence.json public_development_activity",
        "limitation": (
            "Each ledger URL remains subject to human review; local commit dates are context only."
        ),
    }


def evaluate_archived_release(
    archived: list[dict[str, Any]],
    *,
    citation: dict[str, Any],
    git_state: dict[str, Any],
) -> dict[str, Any]:
    """Require one archive record to match version, current commit, tag and DOI."""

    errors: list[str] = []
    version = str(citation.get("version") or "").strip()
    expected_tag = f"v{version}" if version else ""
    head_sha = str(git_state.get("head_sha") or "")
    tag_commits = git_state.get("tag_commits")
    tag_commits = tag_commits if isinstance(tag_commits, dict) else {}
    citation_dois = {str(item).rstrip(".,;") for item in citation.get("dois", [])}

    matching = [item for item in archived if str(item.get("tag", "")) == expected_tag]
    if not matching:
        errors.append(f"No archived release matches citation version {version or 'unknown'}.")
        return {"ok": False, "errors": errors, "expected_tag": expected_tag}

    record = matching[-1]
    record_commit = str(record.get("commit_sha") or "")
    tag_commit = str(tag_commits.get(expected_tag) or "")
    record_doi = str(record.get("doi") or "").rstrip(".,;")
    if str(record.get("software_version") or "") != version:
        errors.append("Archived software_version does not match citation version.")
    if not head_sha or record_commit != head_sha:
        errors.append("Archived commit does not match the current submission commit.")
    if not tag_commit or tag_commit != record_commit:
        errors.append("Archived commit does not match the local version tag commit.")
    if not record_doi or record_doi not in citation_dois:
        errors.append("Archived DOI is missing from CITATION.cff metadata.")
    return {
        "ok": not errors,
        "errors": errors,
        "expected_tag": expected_tag,
        "record": record,
        "head_sha": head_sha,
        "tag_commit": tag_commit or None,
        "citation_dois": sorted(citation_dois),
    }


def _git_remote() -> dict[str, Any]:
    try:
        url = _run_git("remote", "get-url", "origin")
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"configured": False, "error": str(exc)}
    assert isinstance(url, str)
    return {
        "configured": True,
        "url": url,
        "github_target": "github.com/D-sudoasd/DiffractScout" in url.replace("\\", "/"),
    }


def _check(
    checks: list[dict[str, Any]],
    name: str,
    status: str,
    evidence: Any,
    *,
    gate: str,
    reason: str,
    required_from: str = "release",
) -> None:
    checks.append(
        {
            "name": name,
            "status": status,
            "gate": gate,
            "evidence": evidence,
            "reason": reason,
            "required_from": required_from,
        }
    )


def _stage_statuses(checks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        blockers = [
            item["name"]
            for item in checks
            if item["status"] == "block"
            and STAGE_ORDER[stage] >= STAGE_ORDER[item["required_from"]]
        ]
        statuses[stage] = {
            "ready": not blockers,
            "blocker_count": len(blockers),
            "blockers": blockers,
        }
    return statuses


def build_report(
    *,
    public_since: date | None,
    as_of: date,
    stage: str = "submission",
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"Unknown readiness stage: {stage!r}.")
    evidence = _load_evidence()
    evidence_errors = validate_evidence_payload(evidence)
    citation = _citation_metadata()
    remote = _git_remote()
    version = _version_metadata()
    license_metadata = _license_metadata()
    paper_pdf = _paper_pdf_metadata(evidence)
    git_release_state = _git_release_state()
    release_acceptance = _release_acceptance(version.get("version"))
    value = (
        evidence.get("public_repository", {}).get("public_since")
        if isinstance(evidence.get("public_repository"), dict)
        else None
    )
    try:
        recorded_public_since = date.fromisoformat(str(value)) if value else None
    except ValueError:
        recorded_public_since = None
    public_since_override = public_since
    public_date_matches = public_since_override is None or public_since_override == recorded_public_since
    public_since = recorded_public_since
    eligible_on = add_calendar_months(public_since, 6) if public_since else None
    history = _git_history(public_since, as_of)
    paper = _paper_metrics()
    checks: list[dict[str, Any]] = []

    _check(
        checks,
        "Public repository date integrity",
        "pass" if public_date_matches and public_since is not None else "block",
        {
            "recorded": public_since.isoformat() if public_since else None,
            "requested": public_since_override.isoformat() if public_since_override else None,
        },
        gate="project",
        reason="The public-development clock is fixed by the evidence ledger and cannot be backdated by CLI override.",
    )

    missing_files = [
        relative for relative in REQUIRED_REPOSITORY_FILES if not (ROOT / relative).is_file()
    ]
    _check(
        checks,
        "Repository materials",
        "pass" if not missing_files else "block",
        {"missing": missing_files},
        gate="project",
        reason="Submission-facing software, governance, validation, and paper files must exist.",
    )

    _check(
        checks,
        "Version metadata consistency",
        "pass" if version["consistent"] else "block",
        version,
        gate="project",
        reason="Package, import and citation versions must identify the same release.",
    )

    _check(
        checks,
        "OSI license text",
        "pass" if license_metadata["ok"] else "block",
        license_metadata,
        gate="official",
        reason="The repository must carry the complete plain-text MIT license.",
    )

    _check(
        checks,
        "Evidence-ledger integrity",
        "pass" if not evidence_errors else "block",
        {"errors": evidence_errors},
        gate="project",
        reason="Impact and validation claims must be indexed by valid, traceable public records.",
    )

    _check(
        checks,
        "Canonical GitHub remote",
        "pass" if remote.get("github_target") else "block",
        remote,
        gate="project",
        reason="The local release candidate must point to the public repository used for the JOSS record.",
    )

    _check(
        checks,
        "Release preflight acceptance",
        "pass" if release_acceptance["ok"] else "block",
        release_acceptance,
        gate="project",
        reason="The current source fingerprint must have passed docs, compile, tests, demo, verify, benchmark, package metadata, and clean-wheel checks.",
    )

    if public_since is None:
        history_status = "block"
        history_evidence: Any = "Public repository date has not been recorded."
    elif as_of < eligible_on:  # type: ignore[operator]
        history_status = "block"
        history_evidence = {
            "public_since": public_since.isoformat(),
            "eligible_on": eligible_on.isoformat() if eligible_on else None,
            "days_remaining": (eligible_on - as_of).days if eligible_on else None,
        }
    else:
        history_status = "pass"
        history_evidence = {
            "public_since": public_since.isoformat(),
            "eligible_on": eligible_on.isoformat() if eligible_on else None,
        }
    _check(
        checks,
        "Six-month public development period",
        history_status,
        history_evidence,
        gate="official",
        reason="JOSS pre-review screening requires at least six months of public development.",
        required_from="submission",
    )

    practical_submission_date = None
    if eligible_on is not None:
        project_buffer = eligible_on.replace(day=15)
        practical_submission_date = max(eligible_on, project_buffer)
    practical_status = (
        "pass"
        if practical_submission_date is not None and as_of >= practical_submission_date
        else "block"
    )
    _check(
        checks,
        "Practical submission date",
        practical_status,
        {
            "target": practical_submission_date.isoformat()
            if practical_submission_date
            else None,
            "policy": "Project buffer after the six-calendar-month date.",
        },
        gate="project",
        reason="The project uses 15 February 2027 as its earliest practical submission date.",
        required_from="submission",
    )

    public_development = _public_development_snapshot(
        evidence,
        public_since=public_since,
        as_of=as_of,
    )
    active_month_count = int(public_development["active_month_count"])
    _check(
        checks,
        "Distributed public iteration",
        "pass" if active_month_count >= 4 else "block",
        {"public_evidence": public_development, "local_history_context": history},
        gate="project",
        reason=(
            "The project uses four active calendar months as a conservative operational threshold; "
            "JOSS editors assess whether activity is genuinely distributed over the public period."
        ),
        required_from="submission",
    )

    paper_ok = (
        not paper["missing_required_sections"]
        and not paper["undefined_citations"]
        and 750 <= paper["approximate_word_count"] <= 1750
    )
    _check(
        checks,
        "JOSS paper structure and citation closure",
        "pass" if paper_ok else "block",
        paper,
        gate="official",
        reason="The manuscript must use the required sections, cite defined references, and remain concise.",
    )

    _check(
        checks,
        "Rendered JOSS draft",
        "pass" if paper_pdf["ok"] else "block",
        paper_pdf,
        gate="official",
        reason="A rendered paper must be available for official-build and page-level review.",
        required_from="submission",
    )

    citation_ok = bool(citation.get("version") and citation.get("repository_code"))
    _check(
        checks,
        "Citation metadata",
        "pass" if citation_ok else "block",
        citation,
        gate="project",
        reason="Release version and canonical repository must be machine-readable.",
    )

    _check(
        checks,
        "Author citation metadata",
        "pass" if citation.get("orcids") else "block",
        {"orcids": citation.get("orcids", [])},
        gate="official",
        reason="Submission authors must supply machine-readable ORCID metadata.",
        required_from="submission",
    )

    author_metadata = _submission_metadata(
        evidence,
        current_head=str(git_release_state.get("head_sha") or ""),
    )
    _check(
        checks,
        "Human-confirmed submission metadata",
        "pass" if author_metadata["ok"] else "block",
        author_metadata,
        gate="official",
        reason="Authors, affiliations, funding, contributors, related work and human review require confirmation.",
        required_from="submission",
    )

    submission_source = tracked_source_is_clean()
    _check(
        checks,
        "Submission source identity",
        "pass" if submission_source["ok"] else "block",
        submission_source,
        gate="project",
        reason="Submission and publication must use a clean checkout whose HEAD matches the recorded remote CI and official paper builds.",
        required_from="submission",
    )

    evidence_schema_ok = evidence.get("schema") == "diffractscout_joss_evidence_v1"
    archived = evidence.get("archived_releases", []) if evidence_schema_ok else []
    use_cases = evidence.get("research_use_cases", []) if evidence_schema_ok else []
    validations = evidence.get("independent_validations", []) if evidence_schema_ok else []
    engagement = evidence.get("external_engagement", []) if evidence_schema_ok else []
    trustworthy_evidence = evidence_schema_ok and not evidence_errors
    archived_records = [item for item in archived if isinstance(item, dict)]
    archive_evaluation = evaluate_archived_release(
        archived_records,
        citation=citation,
        git_state=git_release_state,
    )
    _check(
        checks,
        "Archived tagged release",
        "pass" if archive_evaluation["ok"] else "block",
        archive_evaluation,
        gate="project",
        reason="After review, the final commit, version tag, immutable archive DOI and citation metadata must match.",
        required_from="publication",
    )
    _check(
        checks,
        "Concrete research-use evidence",
        "pass" if trustworthy_evidence and use_cases else "block",
        {"entries": len(use_cases)},
        gate="official",
        reason="The Research impact statement needs concrete evidence of use or credible near-term significance.",
        required_from="submission",
    )
    diffraction_validations = [
        item for item in validations
        if isinstance(item, dict) and item.get("validation_type") == "diffraction"
    ]
    elasticity_validations = [
        item for item in validations
        if isinstance(item, dict) and item.get("validation_type") == "elasticity"
    ]
    _check(
        checks,
        "Independent diffraction validation",
        "pass" if trustworthy_evidence and diffraction_validations else "block",
        {"entries": len(diffraction_validations)},
        gate="project",
        reason="A public, pre-toleranced diffraction comparison is required for submission.",
        required_from="submission",
    )
    _check(
        checks,
        "Independent elasticity validation",
        "pass" if trustworthy_evidence and elasticity_validations else "block",
        {"entries": len(elasticity_validations)},
        gate="project",
        reason="A public tensor-basis-aware elasticity comparison is required for submission.",
        required_from="submission",
    )
    _check(
        checks,
        "External community engagement",
        "pass" if trustworthy_evidence and engagement else "block",
        {"entries": len(engagement)},
        gate="project",
        reason="A single-author project should show public user, reviewer, issue, or contribution engagement.",
        required_from="submission",
    )

    stage_statuses = _stage_statuses(checks)
    for item in checks:
        item["blocking"] = (
            item["status"] == "block"
            and STAGE_ORDER[stage] >= STAGE_ORDER[item["required_from"]]
        )
    selected_status = stage_statuses[stage]
    return {
        "schema": "diffractscout_joss_readiness_report_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "stage": stage,
        "public_since": public_since.isoformat() if public_since else None,
        "earliest_calendar_eligibility": eligible_on.isoformat() if eligible_on else None,
        "ready": selected_status["ready"],
        "blocker_count": selected_status["blocker_count"],
        "stage_statuses": stage_statuses,
        "checks": checks,
        "git_history": history,
        "paper": paper,
        "citation": citation,
        "remote": remote,
        "version": version,
        "license": license_metadata,
        "paper_pdf": paper_pdf,
        "git_release_state": git_release_state,
        "tracked_source_clean": tracked_source_is_clean(),
        "release_acceptance": release_acceptance,
        "evidence_errors": evidence_errors,
        "evidence_counts": {
            "archived_releases": len(archived),
            "public_development_activity": len(
                evidence.get("public_development_activity", [])
                if isinstance(evidence.get("public_development_activity"), list)
                else []
            ),
            "research_use_cases": len(use_cases),
            "independent_validations": len(validations),
            "external_engagement": len(engagement),
        },
        "interpretation": (
            "This report is a project-side preflight. JOSS editors and reviewers make the final scope, "
            "impact, and readiness decisions from the public record."
        ),
    }


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DiffractScout JOSS readiness report",
        "",
        f"- As of: `{report['as_of']}`",
        f"- Selected stage: `{report['stage']}`",
        f"- Public since: `{report['public_since'] or 'not recorded'}`",
        f"- Earliest six-month date: `{report['earliest_calendar_eligibility'] or 'not calculable'}`",
        f"- Status: **{'READY' if report['ready'] else 'BLOCKED'}**",
        f"- Blocking checks: {report['blocker_count']}",
        "",
        "| Check | Required from | Status | Selected-stage blocker | Reason |",
        "|---|---|:---:|:---:|---|",
    ]
    for item in report["checks"]:
        lines.append(
            f"| {item['name']} | {item['required_from']} | {item['status'].upper()} | "
            f"{'YES' if item['blocking'] else 'NO'} | {item['reason']} |"
        )
    lines.extend(
        [
            "",
            "## Evidence snapshot",
            "",
            "```json",
            json.dumps(report["evidence_counts"], indent=2, ensure_ascii=False),
            "```",
            "",
            "## Stage snapshot",
            "",
            "```json",
            json.dumps(report["stage_statuses"], indent=2, ensure_ascii=False),
            "```",
            "",
            "## Git snapshot",
            "",
            "```json",
            json.dumps(report["git_history"], indent=2, ensure_ascii=False),
            "```",
            "",
            report["interpretation"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-since", default="")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--output", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--stage", choices=STAGES, default="submission")
    args = parser.parse_args()

    public_since = date.fromisoformat(args.public_since) if args.public_since else None
    as_of = date.fromisoformat(args.as_of)
    report = build_report(public_since=public_since, as_of=as_of, stage=args.stage)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        (output / "joss_readiness.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (output / "joss_readiness.md").write_text(
            report_markdown(report), encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("READY" if report["ready"] else "BLOCKED")
        print(f"Blockers: {report['blocker_count']}")
        print(
            "Earliest six-month date: "
            + str(report["earliest_calendar_eligibility"] or "not calculable")
        )
    return 2 if args.strict and not report["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
