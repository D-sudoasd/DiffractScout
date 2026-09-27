"""Exercise installed workflows from a directory outside the source checkout."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import diffractscout
from diffractscout.cli import main
from diffractscout.compat.phasescout.elasticity_web import ElasticityWebTarget, run_web_fallback
from diffractscout.validation import verify_bundle


def check() -> None:
    package = Path(diffractscout.__file__).resolve().parent
    if "site-packages" not in package.parts:
        raise RuntimeError(f"Not checking an installed package: {package}")
    with tempfile.TemporaryDirectory(prefix="diffractscout-installed-") as temporary:
        root = Path(temporary)
        cif = package / "benchmark_data/fcc_al.cif"
        assert main(["compat", "cif2peaks", str(cif), "-o", str(root / "peaks.xlsx"), "--export-patterns"]) == 0
        assert (root / "peaks_峰表.xlsx").is_file()
        assert (root / "peaks_谱线.xlsx").is_file()
        assert (root / "peaks_峰表.json").is_file()
        run_web_fallback(root / "literature", [ElasticityWebTarget("mp-134", "Al")], live_search=False)
        assert (root / "literature/elasticity_web_search.csv").is_file()
        assert main(["analyze", str(cif), "-o", str(root / "bundle")]) == 0
        assert verify_bundle(root / "bundle")["ok"]
        assert main(["compat", "--help"]) == 0
        print(json.dumps({"package": str(package), "offline_workflows": "PASS"}))


if __name__ == "__main__":
    check()
