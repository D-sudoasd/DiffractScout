from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .gui import (
    SimpleGuiExportResult,
    initial_gui_cif_paths,
    run_simple_gui_export,
    simple_export_message_lines,
    suggest_output_path,
)


def quick_export_cif2peaks(
    inputs: Sequence[str | Path],
    *,
    output_path: str | Path | None = None,
) -> SimpleGuiExportResult:
    cif_paths = initial_gui_cif_paths(inputs)
    if not cif_paths:
        raise FileNotFoundError("未找到 CIF 文件。请拖入 .cif 文件，或拖入包含 CIF 的文件夹。")
    output = Path(output_path) if output_path is not None else suggest_output_path(cif_paths)
    return run_simple_gui_export(cif_paths, output)


def quick_export_message_lines(result: SimpleGuiExportResult) -> list[str]:
    return simple_export_message_lines(result)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-step Excel export for dragged CIF files or folders.")
    parser.add_argument("inputs", nargs="+", help="CIF files or folders containing CIF files.")
    parser.add_argument("-o", "--output", default=None, help="Optional output .xlsx path.")
    args = parser.parse_args(argv)

    try:
        result = quick_export_cif2peaks(args.inputs, output_path=args.output)
    except Exception as exc:
        print(str(exc))
        return 1

    print("\n".join(quick_export_message_lines(result)))
    for row in result.phase_rows:
        cif_name, formula, space_group, peak_count, warning = row[:5]
        suffix = f"；{warning}" if warning else ""
        print(f"- {cif_name}: {formula}, {space_group}, {peak_count} peaks{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
