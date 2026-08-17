#!/usr/bin/env python3
"""Check release metadata, required files, paper references, tests, and a clean demo."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READINESS_SCRIPT = ROOT / "scripts/joss_readiness.py"


def _load_readiness_module():
    spec = importlib.util.spec_from_file_location(
        "diffractscout_joss_readiness_for_release", READINESS_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load scripts/joss_readiness.py.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_release_acceptance(
    version: str,
    *,
    clean_wheel: dict[str, str],
    preflight_source: dict[str, object],
) -> Path:
    readiness = _load_readiness_module()
    fingerprint = readiness.release_source_fingerprint()
    if not fingerprint.get("ok"):
        raise SystemExit(f"Could not fingerprint release source: {fingerprint}")
    if fingerprint.get("sha256") != preflight_source.get("sha256"):
        raise SystemExit("Release source changed while the preflight was running; rerun it.")
    output = ROOT / "build/release-preflight"
    output.mkdir(parents=True, exist_ok=True)
    path = output / "release_acceptance.json"
    payload = {
        "schema": "diffractscout_release_acceptance_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "version": version,
        "source_sha256": fingerprint["sha256"],
        "source_file_count": fingerprint["file_count"],
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
        "clean_wheel": clean_wheel,
        "limitations": (
            "Local receipt for this exact worktree; remote cross-platform CI and the official "
            "JOSS build remain submission-stage evidence."
        ),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _clean_wheel_smoke(wheel: Path) -> dict[str, str]:
    """Install the just-built wheel without source-path leakage and exercise it."""

    configured_root = os.environ.get("DIFFRACTSCOUT_CLEAN_WHEEL_ROOT", "").strip()
    temporary_root = Path(configured_root).expanduser().resolve() if configured_root else None
    reuse_dependencies = os.environ.get(
        "DIFFRACTSCOUT_CLEAN_WHEEL_SYSTEM_SITE_PACKAGES", ""
    ).strip() == "1"
    if temporary_root is not None:
        temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="diffractscout_clean_wheel_",
        dir=str(temporary_root) if temporary_root else None,
    ) as temp:
        root = Path(temp).resolve()
        environment_path = root / "venv"
        venv_command = [sys.executable, "-m", "venv"]
        if reuse_dependencies:
            venv_command.extend(["--system-site-packages", "--without-pip"])
        venv_command.append(str(environment_path))
        _run(venv_command, cwd=root)
        python = environment_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        clean_environment = os.environ.copy()
        clean_environment.pop("PYTHONPATH", None)

        def run_clean(*args: str) -> None:
            command = [str(python), *args]
            print("+", " ".join(command))
            subprocess.run(command, cwd=root, check=True, env=clean_environment)

        install_args = ["-m", "pip", "install", "--disable-pip-version-check"]
        if reuse_dependencies:
            install_args.extend(["--no-index", "--no-deps"])
        install_args.append(str(wheel.resolve()))
        run_clean(*install_args)
        run_clean("-m", "pip", "check")
        run_clean(
            "-c",
            (
                "import diffractscout,pathlib,sys; "
                "package=pathlib.Path(diffractscout.__file__).resolve(); "
                "venv=pathlib.Path(sys.prefix).resolve(); "
                "package.relative_to(venv); "
                "print(f'CLEAN_WHEEL_PACKAGE={package}')"
            ),
        )
        demo = root / "demo"
        benchmark = root / "benchmark"
        quick = root / "quick.xlsx"
        run_clean("-m", "diffractscout", "demo", "-o", str(demo), "--no-excel")
        run_clean("-m", "diffractscout", "verify", str(demo))
        run_clean("-m", "diffractscout", "benchmark", "-o", str(benchmark))
        packaged_cif = (
            "import diffractscout,pathlib; "
            "print(pathlib.Path(diffractscout.__file__).with_name('benchmark_data')/'fcc_al.cif')"
        )
        located = subprocess.run(
            [str(python), "-c", packaged_cif],
            cwd=root,
            check=True,
            env=clean_environment,
            text=True,
            capture_output=True,
        ).stdout.strip()
        run_clean("-m", "diffractscout", "quick-export", located, "-o", str(quick))
        run_clean("-m", "diffractscout", "verify", str(root / "quick_bundle"))
        return {
            "mode": "system-site-packages" if reuse_dependencies else "isolated-dependencies",
            "package": str(wheel.resolve()),
            "source_tree_import": "rejected",
            "commands": "pip-check,demo,verify,benchmark,quick-export,verify",
        }


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


def _prepare_dist_dir(raw_path: str) -> Path:
    """Resolve a build output directory without deleting existing artifacts."""

    candidate = Path(raw_path).expanduser()
    path = candidate if candidate.is_absolute() else ROOT / candidate
    if path.is_symlink():
        raise SystemExit(f"Distribution output directory must not be a symlink: {path}")
    path = path.resolve()
    if path.exists():
        if not path.is_dir():
            raise SystemExit(f"Distribution output path is not a directory: {path}")
        if any(path.iterdir()):
            raise SystemExit(
                f"Distribution output directory is not empty: {path}. "
                "Choose an empty directory with --dist-dir; existing artifacts were preserved."
            )
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


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
    parser.add_argument(
        "--dist-dir",
        default="dist",
        help="Empty directory for wheel and sdist output; existing files are never removed.",
    )
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
    readiness = _load_readiness_module()
    preflight_source = readiness.release_source_fingerprint()
    if not preflight_source.get("ok"):
        raise SystemExit(f"Could not fingerprint release source: {preflight_source}")

    paper = (ROOT / "paper/paper.md").read_text(encoding="utf-8")
    bibliography = (ROOT / "paper/paper.bib").read_text(encoding="utf-8")
    cited = set(re.findall(r"@([A-Za-z0-9_:-]+)", paper))
    defined = set(re.findall(r"@[A-Za-z]+\{([^,]+),", bibliography))
    undefined = cited - defined
    if undefined:
        raise SystemExit("Undefined bibliography keys: " + ", ".join(sorted(undefined)))

    _run([sys.executable, "scripts/check_docs.py"])
    _run([sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"])
    bash = shutil.which("bash")
    if bash:
        _run([bash, "-n", "scripts/publish_github.sh"])
    tests_passed = not args.skip_tests
    if tests_passed:
        _run([sys.executable, "-m", "pytest", "-q"])

    with tempfile.TemporaryDirectory(prefix="diffractscout_release_") as temp:
        demo = Path(temp) / "demo"
        benchmark = Path(temp) / "benchmark"
        _run([sys.executable, "-m", "diffractscout", "demo", "-o", str(demo)])
        _run([sys.executable, "-m", "diffractscout", "verify", str(demo)])
        _run(
            [sys.executable, "-m", "diffractscout", "benchmark", "-o", str(benchmark)]
        )

    distributions_passed = not args.skip_wheel
    if distributions_passed:
        dist = _prepare_dist_dir(args.dist_dir)
        _run(
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(dist),
            ]
        )
        wheels = sorted(dist.glob("*.whl"))
        sdists = sorted(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise SystemExit(
                f"Expected one wheel and one sdist, found {len(wheels)} wheel(s) and {len(sdists)} sdist(s)."
            )
        _run(
            [
                sys.executable,
                "-m",
                "twine",
                "check",
                str(wheels[0]),
                str(sdists[0]),
            ]
        )
        clean_wheel = _clean_wheel_smoke(wheels[0])
        print(f"Wheel: {_display_path(wheels[0])}")
        print(f"Sdist: {_display_path(sdists[0])}")

    # A receipt may only assert checks actually performed by this invocation.
    if not tests_passed or not distributions_passed:
        print("Release acceptance receipt: not written because checks were skipped")
    else:
        receipt = _write_release_acceptance(
            version,
            clean_wheel=clean_wheel,
            preflight_source=preflight_source,
        )
        # Release-stage strict mode now binds to the exact source fingerprint
        # whose full local preflight produced the receipt.
        with tempfile.TemporaryDirectory(prefix="diffractscout_joss_preflight_") as readiness_temp:
            _run(
                [
                    sys.executable,
                    "scripts/joss_readiness.py",
                    "--stage",
                    "release",
                    "--strict",
                    "--output",
                    readiness_temp,
                ]
            )
        print(f"Release acceptance receipt: {receipt.relative_to(ROOT)}")

    print("Release checks: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
