"""Import tracked upstream runtime sources; never copy settings or user downloads.

Maintainer utility. Run with explicit CIF2Peaks and PhaseScout checkout paths.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cif2peaks", type=Path)
    parser.add_argument("phasescout", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / "src/diffractscout/compat"
    target.mkdir(exist_ok=True)
    inventory = {}
    for name, source in vars(args).items():
        files = subprocess.check_output(
            ["git", "-C", str(source), "ls-files", "-z"]
        ).decode().split("\0")
        records = []
        for relative in filter(None, files):
            src = source / relative
            dest = None
            if name == "cif2peaks" and relative.startswith("src/cif2peaks/"):
                dest = target / name / Path(relative).name
            if name == "phasescout" and (relative in {
                "app.py", "composition_parse.py", "elasticity_web.py",
                "mp_client.py", "structure_type.py",
            } or relative == "scripts/fetch_possible_phases.py"):
                dest = target / name / ("cli.py" if relative.startswith("scripts/") else relative)
            if relative == "LICENSE":
                dest = target / name / "LICENSE"
            if dest is None:
                continue
            data = src.read_bytes()
            records.append({"source": relative, "sha256": hashlib.sha256(data).hexdigest()})
            if dest.suffix == ".py":
                text = data.decode("utf-8-sig").replace("\r\n", "\n")
                if relative in {"src/cif2peaks/batch.py", "src/cif2peaks/quick_export.py", "scripts/fetch_possible_phases.py"}:
                    text = text.replace("from pathlib import Path", "from pathlib import Path\nfrom ...console import configure_cli_output")
                    text = text.replace("    parser = argparse.ArgumentParser(", "    configure_cli_output()\n    parser = argparse.ArgumentParser(", 1)
                if name == "phasescout":
                    text = text.replace("from dataclasses import asdict\n", "")
                    text = text.replace("from dataclasses import dataclass, field", "from dataclasses import dataclass")
                    text = text.replace('f"Definition: non-deprecated MP entries in subsystems; "', '"Definition: non-deprecated MP entries in subsystems; "')
                    text = re.sub(r"from (mp_client|structure_type|composition_parse|elasticity_web) import", r"from .\1 import", text)
                    text = text.replace(
                        '# Project root on sys.path\nROOT = Path(__file__).resolve().parents[1]\nif str(ROOT) not in sys.path:\n    sys.path.insert(0, str(ROOT))\n',
                        'from ..paths import user_data_dir\n\nROOT = user_data_dir()\n',
                    )
                    text = text.replace('APP_DIR = Path(__file__).resolve().parent', 'from ..paths import user_data_dir\n\nAPP_DIR = user_data_dir()')
                data = text.encode("utf-8")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        inventory[name] = {
            "commit": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"]).decode().strip(),
            "files": records,
        }
    (target / "phasescout/__init__.py").write_text('"""Inherited PhaseScout workflows, packaged within DiffractScout."""\n')
    (root / "docs/COMPAT_SOURCE_INVENTORY.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    tests = root / "tests/inherited"
    tests.mkdir(exist_ok=True)
    (tests / "__init__.py").touch()
    for name, source in vars(args).items():
        for src in sorted((source / "tests").glob("test_*.py")):
            text = src.read_text(encoding="utf-8")
            if name == "cif2peaks":
                # Upstream build scripts and agent instructions are not runtime contracts.
                lines = text.splitlines(keepends=True)
                excluded = []
                for node in reversed(ast.parse(text).body):
                    if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                        body = "".join(lines[node.lineno - 1:node.end_lineno])
                        if any(marker in body for marker in (
                            'ROOT / "pyproject.toml"', 'ROOT / "build_windows_app.bat"',
                            'from scripts.package_windows_portable', 'ROOT / "scripts"',
                            'ROOT / ".grok"',
                        )):
                            excluded.append(node.name)
                            del lines[node.lineno - 1:node.end_lineno]
                text = "".join(lines)
                text = text.replace("import tomllib", "")
                text = text.replace("import pytest", 'import pytest\n\npytest.importorskip("pymatgen.core")')
                text = re.sub(r"\bcif2peaks\.", "diffractscout.compat.cif2peaks.", text)
                text = text.replace('"cif2peaks",', '"diffractscout.compat.cif2peaks",')
                text = text.replace("text=True,", 'text=True, encoding="utf-8",')
                text = text.replace('parents[1]', 'parents[2]')
                text = text.replace('ROOT / "examples" / "cif"', 'ROOT / "examples" / "inherited_cif2peaks"')
                text = text.replace('Path.home() / "Desktop" / "Nb_HEA_peak_separation"', 'ROOT / "tests" / "private_fixtures" / "nb_hea"')
                text = text.replace('Path.home() / "Desktop" / "ZrNb_SXRD_deformation" / "Cif"', 'ROOT / "tests" / "private_fixtures" / "zr_hydride"')
                fixture_dir = root / "examples/inherited_cif2peaks"
                fixture_dir.mkdir(exist_ok=True)
                for fixture in (source / "examples/cif").glob("*.cif"):
                    fixture_text = "\n".join(line.rstrip() for line in fixture.read_text(encoding="utf-8").splitlines()).rstrip() + "\n"
                    (fixture_dir / fixture.name).write_text(fixture_text, encoding="utf-8")
                (tests / "EXCLUSIONS.json").write_text(json.dumps(sorted(excluded), indent=2) + "\n")
            else:
                if src.name == "test_skill_complete_table.py":
                    continue
                text = re.sub(r"from (mp_client|structure_type|composition_parse|elasticity_web) import", r"from diffractscout.compat.phasescout.\1 import", text)
                text = text.replace("import mp_client", "from diffractscout.compat.phasescout import mp_client")
            (tests / f"test_{name}_{src.stem[5:]}.py").write_text(text.rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
