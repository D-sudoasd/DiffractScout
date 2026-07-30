"""Bundle integrity checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .utils import sha256_file

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _report(manifest_path: Path, errors: list[str], checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "manifest": str(manifest_path),
        "errors": errors,
        "files": checks,
    }


def verify_bundle(bundle: str | Path) -> dict[str, Any]:
    supplied = Path(bundle).expanduser()
    if supplied.is_symlink():
        manifest_guess = supplied / "manifest.json" if supplied.name != "manifest.json" else supplied
        return _report(manifest_guess, [f"bundle path is a symbolic link: {supplied}"], [])
    root_or_manifest = supplied.resolve()
    manifest_path = (
        root_or_manifest
        if root_or_manifest.name == "manifest.json"
        else root_or_manifest / "manifest.json"
    )
    if not manifest_path.is_file():
        return _report(manifest_path, ["manifest.json not found"], [])
    if manifest_path.is_symlink():
        return _report(manifest_path, ["manifest.json must not be a symbolic link"], [])
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _report(manifest_path, [f"invalid manifest: {exc}"], [])
    if not isinstance(manifest, dict):
        return _report(manifest_path, ["manifest root must be a JSON object"], [])

    root = manifest_path.parent.resolve()
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
            resolved = path.resolve(strict=False)
            resolved.relative_to(root)
        except (OSError, ValueError):
            errors.append(f"manifest path escapes bundle root: {normalized}")
            continue
        if path.is_symlink():
            checks.append({"path": normalized, "ok": False, "reason": "symlink"})
            errors.append(f"symbolic link is not allowed: {normalized}")
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
