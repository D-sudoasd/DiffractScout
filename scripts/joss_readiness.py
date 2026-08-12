#!/usr/bin/env python3
"""Generate a reproducible JOSS submission-readiness report.

The script separates objective repository checks from time-dependent and
evidence-dependent submission gates. It never rewrites Git history and does not
infer that local commits were publicly visible.
"""

from __future__ import annotations

import argparse
import calendar
from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "docs/evidence/impact_evidence.json"

EVIDENCE_CATEGORIES = (
    "archived_releases",
    "research_use_cases",
    "independent_validations",
    "external_engagement",
    "publications_or_preprints",
    "presentations_or_training",
)

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
    "validation_cases/README.md",
    "validation_cases/analytic_reference_v1/README.md",
    "docs/evidence/README.md",
    "docs/evidence/impact_evidence.json",
    "docs/evidence/impact_evidence.schema.json",
    "scripts/joss_readiness.py",
    "scripts/check_docs.py",
    "scripts/archive_tree.py",
    "paper/paper.md",
    "paper/paper.bib",
    "paper/fig_workflow.png",
    "paper/fig_validation.png",
    "paper/make_figures.py",
    "paper/build_local.sh",
    "paper/README.md",
    ".github/workflows/ci.yml",
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


def _run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
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
        tags = [item for item in _run_git("tag", "--list").splitlines() if item]
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


def validate_evidence_payload(payload: dict[str, Any]) -> list[str]:
    """Return structural errors in the machine-readable impact ledger.

    This intentionally avoids inferring impact from counts. It only checks that
    records are traceable, dated, versioned, and sufficiently specific to audit.
    """

    errors: list[str] = []
    if payload.get("schema") != "diffractscout_joss_evidence_v1":
        errors.append("Unknown or missing evidence schema.")

    repository = payload.get("public_repository")
    if not isinstance(repository, dict):
        errors.append("public_repository must be an object.")
    else:
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


def _git_remote() -> dict[str, Any]:
    try:
        url = _run_git("remote", "get-url", "origin")
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"configured": False, "error": str(exc)}
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
) -> None:
    checks.append(
        {
            "name": name,
            "status": status,
            "gate": gate,
            "evidence": evidence,
            "reason": reason,
        }
    )


def build_report(
    *,
    public_since: date | None,
    as_of: date,
) -> dict[str, Any]:
    evidence = _load_evidence()
    evidence_errors = validate_evidence_payload(evidence)
    citation = _citation_metadata()
    remote = _git_remote()
    if public_since is None:
        value = (
            evidence.get("public_repository", {}).get("public_since")
            if isinstance(evidence.get("public_repository"), dict)
            else None
        )
        public_since = date.fromisoformat(value) if value else None
    eligible_on = add_calendar_months(public_since, 6) if public_since else None
    history = _git_history(public_since, as_of)
    paper = _paper_metrics()
    checks: list[dict[str, Any]] = []

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
    )

    active_month_count = int(history.get("active_month_count", 0))
    _check(
        checks,
        "Distributed public iteration",
        "pass" if active_month_count >= 4 else "block",
        history,
        gate="project",
        reason=(
            "The project uses four active calendar months as a conservative operational threshold; "
            "JOSS editors assess whether activity is genuinely distributed over the public period."
        ),
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

    citation_ok = bool(citation.get("version") and citation.get("repository_code") and citation.get("orcids"))
    _check(
        checks,
        "Citation metadata",
        "pass" if citation_ok else "block",
        citation,
        gate="project",
        reason="Version, canonical repository, and author ORCID metadata must be machine-readable.",
    )

    evidence_schema_ok = evidence.get("schema") == "diffractscout_joss_evidence_v1"
    archived = evidence.get("archived_releases", []) if evidence_schema_ok else []
    use_cases = evidence.get("research_use_cases", []) if evidence_schema_ok else []
    validations = evidence.get("independent_validations", []) if evidence_schema_ok else []
    engagement = evidence.get("external_engagement", []) if evidence_schema_ok else []
    archived_tags = {str(item.get("tag", "")) for item in archived if isinstance(item, dict)}
    local_tags = set(history.get("tags", []))
    archived_ok = bool(archived) and bool(archived_tags & local_tags) and bool(citation.get("dois"))
    _check(
        checks,
        "Archived tagged release",
        "pass" if archived_ok else "block",
        {
            "entries": len(archived),
            "evidence_tags": sorted(archived_tags),
            "local_tags": sorted(local_tags),
            "citation_dois": citation.get("dois", []),
        },
        gate="project",
        reason="The submission commit should correspond to a local tag, an immutable archive DOI, and matching citation metadata.",
    )
    _check(
        checks,
        "Concrete research-use evidence",
        "pass" if use_cases else "block",
        {"entries": len(use_cases)},
        gate="official",
        reason="The Research impact statement needs concrete evidence of use or credible near-term significance.",
    )
    _check(
        checks,
        "Independent scientific validation",
        "pass" if validations else "block",
        {"entries": len(validations)},
        gate="project",
        reason="At least one independent comparison is the project threshold for a defensible scientific submission.",
    )
    _check(
        checks,
        "External community engagement",
        "pass" if engagement else "block",
        {"entries": len(engagement)},
        gate="project",
        reason="A single-author project should show public user, reviewer, issue, or contribution engagement.",
    )

    blockers = [item for item in checks if item["status"] == "block"]
    return {
        "schema": "diffractscout_joss_readiness_report_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "public_since": public_since.isoformat() if public_since else None,
        "earliest_calendar_eligibility": eligible_on.isoformat() if eligible_on else None,
        "ready": not blockers,
        "blocker_count": len(blockers),
        "checks": checks,
        "git_history": history,
        "paper": paper,
        "citation": citation,
        "remote": remote,
        "evidence_errors": evidence_errors,
        "evidence_counts": {
            "archived_releases": len(archived),
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
        f"- Public since: `{report['public_since'] or 'not recorded'}`",
        f"- Earliest six-month date: `{report['earliest_calendar_eligibility'] or 'not calculable'}`",
        f"- Status: **{'READY' if report['ready'] else 'BLOCKED'}**",
        f"- Blocking checks: {report['blocker_count']}",
        "",
        "| Check | Gate | Status | Reason |",
        "|---|---|:---:|---|",
    ]
    for item in report["checks"]:
        lines.append(
            f"| {item['name']} | {item['gate']} | {item['status'].upper()} | {item['reason']} |"
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
    args = parser.parse_args()

    public_since = date.fromisoformat(args.public_since) if args.public_since else None
    as_of = date.fromisoformat(args.as_of)
    report = build_report(public_since=public_since, as_of=as_of)
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