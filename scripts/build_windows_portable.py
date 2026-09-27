"""Build a complete, self-tested Windows portable distribution.

Install .[complete,windows] before running this script on Windows.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def freeze_command(dist: Path, work: Path) -> list[str]:
    command = [
        sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
        "--name", "DiffractScout", "--paths", str(ROOT / "src"),
        "--distpath", str(dist), "--workpath", str(work / "build"),
        "--specpath", str(work),
    ]
    for package in ("diffractscout", "gemmi", "spglib", "tkinterdnd2", "mp_api", "pymatgen"):
        command.extend(["--collect-all", package])
    # The desktop uses Tk; optional plotting backends must not pull competing Qt bindings.
    for package in ("PyQt5", "PyQt6", "PySide2", "PySide6", "torch", "tensorflow"):
        command.extend(["--exclude-module", package])
    command.append(str(ROOT / "scripts/diffractscout_entry.py"))
    return command


def package_portable_app(folder: Path, output: Path) -> Path:
    for relative in ("DiffractScout.exe", "LICENSE", "NOTICE.md", "README.md", "self_test.bat"):
        if not (folder / relative).is_file():
            raise FileNotFoundError(f"Incomplete portable distribution: {relative}")
    for filename in ("init.tcl", "tk.tcl"):
        if not any((folder / "_internal").rglob(filename)):
            raise FileNotFoundError(f"Missing Tcl/Tk runtime: {filename}")
    if not any((folder / "examples").rglob("*.cif")):
        raise FileNotFoundError("Missing example CIFs")
    if output.resolve().is_relative_to(folder.resolve()):
        raise ValueError("ZIP output must be outside the app folder")
    files = sorted(folder.rglob("*"))
    if any(path.is_symlink() for path in files):
        raise ValueError("Portable distribution must not contain symbolic links")
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_file():
                archive.write(path, Path(folder.name) / path.relative_to(folder))
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist/portable")
    parser.add_argument("--work", type=Path, default=ROOT / "build/portable")
    args = parser.parse_args(argv)
    args.dist = args.dist.resolve()
    args.work = args.work.resolve()
    if sys.platform != "win32":
        parser.error("Windows builds must run on Windows")
    folder = args.dist / "DiffractScout"
    if folder.exists():
        parser.error("Output folder already exists; choose a fresh --dist directory")
    args.work.mkdir(parents=True, exist_ok=True)
    subprocess.run(freeze_command(args.dist, args.work), check=True, cwd=ROOT)
    for name in ("LICENSE", "NOTICE.md", "README.md"):
        shutil.copy2(ROOT / name, folder / name)
    shutil.copytree(ROOT / "examples", folder / "examples")
    (folder / "docs").mkdir()
    for name in ("REPLACEMENT_AUDIT.md", "REPLACEMENT_REPORT.zh-CN.md", "COMPAT_SOURCE_INVENTORY.json"):
        shutil.copy2(ROOT / "docs" / name, folder / "docs" / name)
    for name, command in {
        "start_gui.bat": '"%~dp0DiffractScout.exe" gui',
        "CIF2Peaks.bat": '"%~dp0DiffractScout.exe" compat cif2peaks-gui %*',
        "PhaseScout.bat": '"%~dp0DiffractScout.exe" compat phasescout-gui',
        "quick_export.bat": '"%~dp0DiffractScout.exe" compat cif2peaks-quick-export %*',
        "self_test.bat": '"%~dp0DiffractScout.exe" --version\nif errorlevel 1 exit /b 1\n"%~dp0DiffractScout.exe" demo -o "%TEMP%\\DiffractScout-test-%RANDOM%"',
    }.items():
        (folder / name).write_bytes(("@echo off\n" + command + "\n").replace("\n", "\r\n").encode("ascii"))
    executable = str(folder / "DiffractScout.exe")
    for workflow in ("cif2peaks", "phasescout"):
        subprocess.run([executable, "compat", workflow, "--help"], check=True, cwd=folder)
    subprocess.run([executable, "demo", "-o", "self-test-results"], check=True, cwd=folder)
    subprocess.run([executable, "verify", "self-test-results"], check=True, cwd=folder)
    subprocess.run([
        executable, "compat", "cif2peaks", "examples/inherited_cif2peaks",
        "-o", "self-test-peaks.xlsx", "--export-patterns",
    ], check=True, cwd=folder)
    print(package_portable_app(folder, args.dist / "DiffractScout_Windows_Portable.zip"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
