from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import tempfile
import warnings
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp, honoring SOURCE_DATE_EPOCH when set."""

    epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if epoch:
        try:
            return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(value: str, fallback: str = "item") -> str:
    value = re.sub(r"[^A-Za-z0-9_.+-]+", "_", value.strip()).strip("._ ")
    value = re.sub(r"_+", "_", value)
    return value or fallback


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in fields(value)
            if field.name
            not in {"small_structure", "structure_factor_structure", "space_group_object"}
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, complex):
        return {"real": value.real, "imag": value.imag}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


def write_json(path: str | Path, payload: Any) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}-",
        suffix=".tmp",
        dir=str(output.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(
                json.dumps(
                    to_jsonable(payload),
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
        temporary.replace(output)
    finally:
        if descriptor != -1:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            try:
                warnings.warn(
                    f"Could not remove JSON temporary file {temporary}: "
                    f"{type(exc).__name__}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
            except Exception:
                pass
    return output


def runtime_environment() -> dict[str, str]:
    """Return portable runtime metadata without local paths or host identifiers."""

    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "operating_system": platform.system(),
        "operating_system_release": platform.release(),
        "machine": platform.machine(),
        "byteorder": sys.byteorder,
    }


def package_versions(
    names: tuple[str, ...] = (
        "diffractscout",
        "gemmi",
        "numpy",
        "pandas",
        "openpyxl",
        "spglib",
        "mp-api",
        "pymatgen",
    ),
) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in names:
        if name.casefold() == "diffractscout":
            # Resolve the local package lazily.  Importing it at module scope
            # would create a cycle while diffractscout itself is initializing,
            # and installed metadata may describe an older checkout.
            try:
                from . import __version__ as runtime_version
            except (ImportError, AttributeError):
                versions[name] = "not-installed"
            else:
                versions[name] = str(runtime_version)
            continue
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions
