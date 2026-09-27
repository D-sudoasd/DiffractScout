from __future__ import annotations

import hashlib
import importlib.metadata
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def package_versions() -> dict[str, str]:
    packages = ("cif2peaks", "numpy", "pymatgen", "gemmi", "spglib")
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def friendly_cif_issue_message(error: str | None, warnings: Sequence[str]) -> str:
    if error:
        lower = error.lower()
        if (
            "cif" in lower
            or "cell parameters" in lower
            or "atom coordinates" in lower
            or "no structures" in lower
            or "failed to open" in lower
            or "data is invalid" in lower
        ):
            return "CIF 格式不完整或无法解析。请检查该文件是否包含晶胞参数和原子坐标。"
        return f"无法读取该 CIF：{error}"
    return " | ".join(warnings)
