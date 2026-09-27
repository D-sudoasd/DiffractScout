"""Dispatch inherited workflows without importing optional engines at startup."""
from __future__ import annotations

import importlib
import sys
from typing import Sequence


WORKFLOWS = {
    "cif2peaks": "diffractscout.compat.cif2peaks.batch",
    "cif2peaks-gui": "diffractscout.compat.cif2peaks.gui",
    "cif2peaks-quick-export": "diffractscout.compat.cif2peaks.quick_export",
    "phasescout": "diffractscout.compat.phasescout.cli",
    "phasescout-gui": "diffractscout.compat.phasescout.app",
}


def dispatch(workflow: str, argv: Sequence[str] = ()) -> int:
    if workflow not in WORKFLOWS:
        raise ValueError(f"Unknown inherited workflow: {workflow}")
    try:
        module = importlib.import_module(WORKFLOWS[workflow])
        if workflow == "phasescout-gui":
            if argv:
                raise ValueError("phasescout-gui takes no arguments")
            return int(module.main() or 0)
        return int(module.main(list(argv)) or 0)
    except ImportError as exc:
        print(
            f"Cannot load {workflow}: {exc}. Install the complete edition with "
            'python -m pip install "diffractscout[complete]".',
            file=sys.stderr,
        )
        return 2
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in WORKFLOWS:
        print("Usage: diffractscout-compat {" + ",".join(WORKFLOWS) + "} [options]")
        return 0 if args == ["--help"] else 2
    return dispatch(args[0], args[1:])


if __name__ == "__main__":
    raise SystemExit(main())
