"""Bundle integrity checks."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .utils import sha256_file

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def _report(manifest_path: Path, errors: list[str], checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "manifest": str(manifest_path),
        "errors": errors,
        "files": checks,
    }


def _is_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink or Windows reparse point."""

    try:
        stat_result = path.stat(follow_symlinks=False)
    except (OSError, TypeError):
        try:
            stat_result = path.lstat()
        except OSError:
            return path.is_symlink()
    return path.is_symlink() or bool(
        getattr(stat_result, "st_file_attributes", 0)
        & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _reject_reparse_components(path: Path, *, label: str) -> None:
    """Reject reparse components before any path resolution follows them."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    components: list[Path] = []
    current = absolute
    while True:
        components.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    for component in reversed(components):
        if component.exists() or component.is_symlink():
            if _is_reparse_point(component):
                raise FileExistsError(
                    f"Refusing to verify a symbolic link or Windows reparse-point "
                    f"{label}: {component}"
                )


def verify_bundle(bundle: str | Path) -> dict[str, Any]:
    supplied = Path(bundle).expanduser()
    supplied = Path(os.path.abspath(os.fspath(supplied)))
    manifest_guess = supplied if supplied.name == "manifest.json" else supplied / "manifest.json"
    try:
        _reject_reparse_components(supplied, label="bundle or manifest path")
    except (OSError, ValueError) as exc:
        return _report(manifest_guess, [str(exc)], [])
    root_or_manifest = supplied
    manifest_path = (
        root_or_manifest
        if root_or_manifest.name == "manifest.json"
        else root_or_manifest / "manifest.json"
    )
    try:
        _reject_reparse_components(manifest_path, label="manifest path")
    except (OSError, ValueError) as exc:
        return _report(manifest_path, [str(exc)], [])
    if not manifest_path.is_file():
        return _report(manifest_path, ["manifest.json not found"], [])
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _report(manifest_path, [f"invalid manifest: {exc}"], [])
    if not isinstance(manifest, dict):
        return _report(manifest_path, ["manifest root must be a JSON object"], [])

    root = manifest_path.parent
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    if manifest.get("schema") != "diffractscout_bundle_manifest_v1":
        errors.append(f"unsupported manifest schema: {manifest.get('schema')!r}")

    entries = manifest.get("files")
    if not isinstance(entries, list):
        errors.append("manifest 'files' must be a list")
        entries = []

    declared: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"manifest file entry {index} must be an object")
            continue
        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(f"manifest file entry {index} has an empty or non-string path")
            continue
        relative = Path(raw_path)
        normalized = relative.as_posix()
        if (
            relative.is_absolute()
            or normalized in {".", "manifest.json"}
            or ".." in relative.parts
            or any(part in {"", "."} for part in relative.parts)
        ):
            errors.append(f"unsafe manifest path: {raw_path}")
            continue
        if normalized in declared:
            errors.append(f"duplicate manifest path: {normalized}")
            continue
        declared.add(normalized)

        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash.lower()):
            errors.append(f"invalid SHA-256 value for {normalized}")
            expected_hash = ""
        else:
            expected_hash = expected_hash.lower()
        expected_size = entry.get("size_bytes")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
            errors.append(f"invalid size_bytes value for {normalized}")
            expected_size = None

        path = root / relative
        try:
            _reject_reparse_components(path, label=f"manifest file {normalized}")
        except (OSError, ValueError):
            errors.append(f"unsafe or reparse manifest path: {normalized}")
            continue
        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(root)
        except (OSError, ValueError):
            errors.append(f"manifest path escapes bundle root: {normalized}")
            continue
        if not path.is_file():
            checks.append({"path": normalized, "ok": False, "reason": "missing"})
            errors.append(f"missing file: {normalized}")
            continue
        try:
            actual_hash = sha256_file(path)
            actual_size = path.stat().st_size
        except OSError as exc:
            checks.append({"path": normalized, "ok": False, "reason": str(exc)})
            errors.append(f"could not read file {normalized}: {exc}")
            continue
        hash_ok = bool(expected_hash) and actual_hash == expected_hash
        size_ok = expected_size is not None and expected_size == actual_size
        ok = hash_ok and size_ok
        checks.append(
            {
                "path": normalized,
                "ok": ok,
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "expected_size_bytes": expected_size,
                "actual_size_bytes": actual_size,
            }
        )
        if expected_hash and not hash_ok:
            errors.append(f"hash mismatch: {normalized}")
        if expected_size is not None and not size_ok:
            errors.append(f"size mismatch: {normalized}")

    actual: set[str] = set()
    for path in sorted(root.rglob("*")):
        if path == manifest_path:
            continue
        try:
            _reject_reparse_components(path, label="bundle member")
        except (OSError, ValueError) as exc:
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                errors.append(f"symbolic link is not allowed: {relative}")
            else:
                errors.append(f"unsafe or reparse bundle member: {relative} ({exc})")
            continue
        if path.is_symlink():
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                relative = str(path)
            errors.append(f"symbolic link is not allowed: {relative}")
            continue
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    for unexpected in sorted(actual - declared):
        errors.append(f"unexpected unlisted file: {unexpected}")
        checks.append({"path": unexpected, "ok": False, "reason": "unlisted"})

    return _report(manifest_path, errors, checks)
