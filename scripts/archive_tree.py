#!/usr/bin/env python3
"""Create a deterministic, symlink-free ZIP archive from a directory tree.

The archive uses sorted paths, normalized metadata, and stored entries. This
makes the bytes reproducible for identical input bytes and the same root name,
independent of filesystem mtimes and ZIP compression-library behavior.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path, PurePosixPath
import tempfile
from zipfile import ZIP_STORED, ZipFile, ZipInfo

MIN_ZIP_EPOCH = 315532800  # 1980-01-01T00:00:00Z


def _archive_datetime() -> tuple[int, int, int, int, int, int]:
    raw = os.environ.get("SOURCE_DATE_EPOCH", str(MIN_ZIP_EPOCH)).strip()
    try:
        epoch = max(MIN_ZIP_EPOCH, int(raw))
    except ValueError as exc:
        raise ValueError("SOURCE_DATE_EPOCH must be an integer Unix timestamp.") from exc
    value = datetime.fromtimestamp(epoch, tz=timezone.utc)
    # ZIP stores timestamps with two-second resolution.
    return value.year, value.month, value.day, value.hour, value.minute, value.second // 2 * 2


def _safe_root_name(value: str) -> str:
    candidate = value.strip().replace("\\", "/").strip("/")
    if not candidate or "/" in candidate or candidate in {".", ".."}:
        raise ValueError("Archive root name must be one safe path component.")
    return candidate


def create_reproducible_zip(
    source_dir: str | Path,
    output_zip: str | Path,
    *,
    root_name: str | None = None,
) -> Path:
    source = Path(source_dir).expanduser().resolve()
    output_raw = Path(output_zip).expanduser()
    output = output_raw.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Archive source directory does not exist: {source}")
    if output == source or output.is_relative_to(source):
        raise ValueError("Archive output must be outside the source directory.")
    if output_raw.is_symlink():
        raise ValueError(f"Refusing to replace a symbolic-link archive path: {output_raw}")

    prefix = _safe_root_name(root_name or source.name)
    timestamp = _archive_datetime()
    files: list[Path] = []
    for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ValueError(f"Refusing to archive symbolic link: {path}")
        if path.is_file():
            files.append(path)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
        ) as handle:
            temporary_name = handle.name
        with ZipFile(temporary_name, mode="w", compression=ZIP_STORED, strict_timestamps=True) as archive:
            for path in files:
                relative = PurePosixPath(path.relative_to(source).as_posix())
                member = str(PurePosixPath(prefix) / relative)
                info = ZipInfo(member, date_time=timestamp)
                info.create_system = 3
                info.compress_type = ZIP_STORED
                info.external_attr = (0o100644 & 0xFFFF) << 16
                archive.writestr(info, path.read_bytes())
        Path(temporary_name).replace(output)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir")
    parser.add_argument("output_zip")
    parser.add_argument("--root-name", default=None)
    args = parser.parse_args()
    output = create_reproducible_zip(
        args.source_dir,
        args.output_zip,
        root_name=args.root_name,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
