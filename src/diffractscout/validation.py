"""Bundle integrity checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import sha256_file


def verify_bundle(bundle: str | Path) -> dict[str, Any]:
    root = Path(bundle).expanduser().resolve()
    manifest_path = root if root.name == "manifest.json" else root / "manifest.json"
    if not manifest_path.is_file():
        return {"ok": False, "manifest": str(manifest_path), "errors": ["manifest.json not found"], "files": []}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "manifest": str(manifest_path), "errors": [f"invalid manifest: {exc}"], "files": []}

    root = manifest_path.parent
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    if manifest.get("schema") != "diffractscout_bundle_manifest_v1":
        errors.append(f"unsupported manifest schema: {manifest.get('schema')!r}")

    for entry in manifest.get("files", []):
        relative = Path(str(entry.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"unsafe manifest path: {relative}")
            continue
        path = root / relative
        expected_hash = str(entry.get("sha256", ""))
        expected_size = entry.get("size_bytes")
        if not path.is_file():
            checks.append({"path": relative.as_posix(), "ok": False, "reason": "missing"})
            errors.append(f"missing file: {relative.as_posix()}")
            continue
        actual_hash = sha256_file(path)
        actual_size = path.stat().st_size
        ok = actual_hash == expected_hash and (
            expected_size is None or int(expected_size) == actual_size
        )
        checks.append(
            {
                "path": relative.as_posix(),
                "ok": ok,
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "expected_size_bytes": expected_size,
                "actual_size_bytes": actual_size,
            }
        )
        if actual_hash != expected_hash:
            errors.append(f"hash mismatch: {relative.as_posix()}")
        if expected_size is not None and int(expected_size) != actual_size:
            errors.append(f"size mismatch: {relative.as_posix()}")

    return {
        "ok": not errors,
        "manifest": str(manifest_path),
        "errors": errors,
        "files": checks,
    }
