"""Windows packaging entry point.

The builder runs python -m PyInstaller with --paths src and
scripts\\diffractscout_entry.py, validates Tcl/Tk, runs frozen CLI checks,
and packages the complete directory. Install .[complete,windows] first.
"""
from __future__ import annotations

import argparse
import json

from build_windows_portable import ROOT, freeze_command, main as build_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--print-recipe", action="store_true")
    parser.add_argument("--build", action="store_true")
    args, extra = parser.parse_known_args(argv)
    if args.build:
        return build_main(extra)
    if extra:
        parser.error("Unexpected arguments: " + " ".join(extra))
    print("Portable build implemented. Use --build on Windows after installing .[complete,windows].")
    if args.print_recipe:
        print(json.dumps(freeze_command(ROOT / "dist/portable", ROOT / "build/portable"), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
