#!/usr/bin/env python3
"""Document / sketch a Windows portable (PyInstaller) build for DiffractScout.

Status: **stub / documentation only**. This script does not run a full freeze
build. Prefer an editable install plus the root batch launchers for day-to-day
Windows use:

* ``启动DiffractScout.bat`` — desktop GUI
* ``quick_export_diffractscout.bat`` — drag-and-drop quick-export

When a portable single-folder or one-file build is required, the recommended
approach is PyInstaller against the checked-in standalone wrapper below.  The
wrapper imports ``diffractscout.cli.main`` and adds ``src`` to ``sys.path``
when run directly from a source checkout.

Example outline (run from a clean venv after ``pip install -e ".[figures]"``)::

    python -m PyInstaller ^
      --noconfirm --clean ^
      --name DiffractScout ^
      --paths src ^
      --collect-all gemmi ^
      --collect-all spglib ^
      --hidden-import diffractscout.gui ^
      --hidden-import diffractscout.quick_export ^
      scripts\\diffractscout_entry.py

Notes for a real freeze:

* Tk GUI needs the Tcl/Tk data files bundled (PyInstaller usually handles this).
* Optional MP path needs ``.[mp]`` and network access at runtime, not freeze time.
* Optional figures need matplotlib (``.[figures]``).
* Ship ``启动DiffractScout.bat`` / ``quick_export_diffractscout.bat`` only when the
  frozen layout still exposes ``py -3 -m diffractscout``; for pure frozen trees,
  point the batch files at the frozen executables instead.
* Do not embed user API keys or experimental datasets in the portable package.
"""

from __future__ import annotations

import argparse
import sys
from textwrap import dedent


STATUS = "stub"
SUMMARY = dedent(
    """\
    package_windows_portable.py — status: stub (documentation only)

    This helper does not produce a portable build yet. Use:

      py -3 -m pip install -e ".[figures,gui-dnd]"
      启动DiffractScout.bat
      quick_export_diffractscout.bat

    For a future PyInstaller freeze, see the module docstring
    (python scripts/package_windows_portable.py --help) and the examples
    printed by --print-recipe.
    """
)

RECIPE = dedent(
    """\
    # Suggested future recipe (not executed by this stub)
    python -m venv .venv-portable
    .venv-portable\\Scripts\\activate
    python -m pip install -U pip
    python -m pip install -e ".[figures]"
    python -m pip install pyinstaller
    python -m PyInstaller --noconfirm --clean --name DiffractScout ^
      --paths src ^
      --collect-all gemmi --collect-all spglib ^
      --hidden-import diffractscout.gui ^
      --hidden-import diffractscout.quick_export ^
      scripts\\diffractscout_entry.py
    # Then copy batch launchers and edit them to call dist\\DiffractScout\\DiffractScout.exe
    """
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="package_windows_portable",
        description=(
            "Windows portable packaging helper for DiffractScout. "
            "Currently a documentation stub: it does not run PyInstaller."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent(
            """\
            status:
              stub — no freeze build is performed.

            related launchers (repo root):
              启动DiffractScout.bat
              quick_export_diffractscout.bat
            """
        ),
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print packaging status and exit 0.",
    )
    parser.add_argument(
        "--print-recipe",
        action="store_true",
        help="Print a sample PyInstaller recipe (not executed).",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Reserved for a future freeze implementation (currently errors).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.build:
        print(
            "ERROR: portable freeze is not implemented in this stub.\n"
            "Use --print-recipe for a manual PyInstaller outline, or install\n"
            "the package and use the Windows batch launchers.",
            file=sys.stderr,
        )
        return 2

    if args.print_recipe:
        print(RECIPE)
        return 0

    # Default and --status: explain current state.
    print(SUMMARY)
    print(f"status={STATUS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
