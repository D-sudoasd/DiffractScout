#!/usr/bin/env python3
"""Check release metadata, required files, paper references, tests, and a clean demo."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(command))
    environment = os.environ.copy()
    source_path = str(ROOT / "src")
    environment["PYTHONPATH"] = source_path + os.pathsep + environment.get("PYTHONPATH", "")
    subprocess.run(command, cwd=cwd, check=True, env=environment)


def _version_from_pyproject() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("No [project] version found in pyproject.toml.")
    return match.group(1)


def _version_from_init() -> str:
    text = (ROOT / "src/diffractscout/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("No __version__ found in diffractscout/__init__.py.")
    return match.group(1)


def _version_from_cff() -> str:
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*['\"]?([^'\"\s]+)", text, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("No version found in CITATION.cff.")
    return match.group(1)


def _required_files() -> list[Path]:
    return [
        ROOT / "LICENSE",
        ROOT / "README.md",
        ROOT / "CITATION.cff",
        ROOT / "CONTRIBUTING.md",
        ROOT / "CODE_OF_CONDUCT.md",
        ROOT / "SECURITY.md",
        ROOT / "GOVERNANCE.md",
        ROOT / "SUPPORT.md",
        ROOT / "ROADMAP.md",
        ROOT / "CHANGELOG.md",
        ROOT / "docs/GUI.md",
        ROOT / "docs/assets/gui-local.png",
        ROOT / "docs/assets/gui-materials-project.png",
        ROOT / "docs/ARCHITECTURE.md",
        ROOT / "docs/SCIENTIFIC_CONTRACTS.md",
        ROOT / "docs/SOURCE_LINEAGE.md",
        ROOT / "docs/VALIDATION.md",
        ROOT / "docs/JOSS_READINESS.md",
        ROOT / "docs/JOSS_6_MONTH_PLAN.md",
        ROOT / "docs/ADOPTION_AND_IMPACT.md",
        ROOT / "docs/VALIDATION_CASE_TEMPLATE.md",
        ROOT / "docs/ANALYTIC_BENCHMARKS.md",
        ROOT / "validation_cases/README.md",
        ROOT / "validation_cases/analytic_reference_v1/README.md",
        ROOT / "docs/evidence/impact_evidence.json",
        ROOT / "docs/evidence/impact_evidence.schema.json",
        ROOT / "scripts/joss_readiness.py",
        ROOT / "scripts/check_docs.py",
        ROOT / "scripts/archive_tree.py",
        ROOT / "paper/paper.md",
        ROOT / "paper/paper.bib",
        ROOT / "paper/fig_workflow.png",
        ROOT / "paper/fig_validation.png",
        ROOT / "paper/make_figures.py",
        ROOT / "paper/build_local.sh",
        ROOT / "paper/README.md",
        ROOT / ".github/workflows/ci.yml",
        ROOT / ".github/workflows/draft-pdf.yml",
        ROOT / ".github/workflows/release.yml",
        ROOT / ".github/workflows/monthly-audit.yml",
        ROOT / ".github/dependabot.yml",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-wheel", action="store_true")
    args = parser.parse_args()

    missing = [path.relative_to(ROOT) for path in _required_files() if not path.is_file()]
    if missing:
        raise SystemExit("Missing required files: " + ", ".join(map(str, missing)))

    versions = {
        "pyproject.toml": _version_from_pyproject(),
        "src/diffractscout/__init__.py": _version_from_init(),
        "CITATION.cff": _version_from_cff(),
    }
    if len(set(versions.values())) != 1:
        raise SystemExit(f"Version mismatch: {versions}")
    version = next(iter(versions.values()))
    print(f"Version metadata: {version}")

    paper = (ROOT / "paper/paper.md").read_text(encoding="utf-8")
    bibliography = (ROOT / "paper/paper.bib").read_text(encoding="utf-8")
    cited = set(re.findall(r"@([A-Za-z0-9_:-]+)", paper))
    defined = set(re.findall(r"@[A-Za-z]+\{([^,]+),", bibliography))
    undefined = cited - defined
    if undefined:
        raise SystemExit("Undefined bibliography keys: " + ", ".join(sorted(undefined)))

    # Non-strict mode validates the readiness machinery while preserving honest
    # blockers such as public age, impact evidence, and archive DOI.
    with tempfile.TemporaryDirectory(prefix="diffractscout_joss_preflight_") as readiness_temp:
        _run(
            [
                sys.executable,
                "scripts/joss_readiness.py",
                "--output",
                readiness_temp,
            ]
        )

    _run([sys.executable, "scripts/check_docs.py"])
    _run([sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"])
    bash = shutil.which("bash")
    if bash:
        _run([bash, "-n", "scripts/publish_github.sh"])
    if not args.skip_tests:
        _run([sys.executable, "-m", "pytest", "-q"])

    with tempfile.TemporaryDirectory(prefix="diffractscout_release_") as temp:
        demo = Path(temp) / "demo"
        benchmark = Path(temp) / "benchmark"
        _run([sys.executable, "-m", "diffractscout", "demo", "-o", str(demo)])
        _run([sys.executable, "-m", "diffractscout", "verify", str(demo)])
        _run(
            [sys.executable, "-m", "diffractscout", "benchmark", "-o", str(benchmark)]
        )

    if not args.skip_wheel:
        dist = ROOT / "dist"
        if dist.exists():
            shutil.rmtree(dist)
        _run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", "dist"])
        wheels = sorted(dist.glob("*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"Expected one wheel, found {len(wheels)}.")
        print(f"Wheel: {wheels[0].relative_to(ROOT)}")

    print("Release checks: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
