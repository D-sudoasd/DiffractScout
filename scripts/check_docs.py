#!/usr/bin/env python3
"""Validate repository documentation links and machine-readable metadata."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

try:
    import yaml
except ImportError as exc:  # pragma: no cover - release dependency supplies it
    raise SystemExit("PyYAML is required for repository metadata validation.") from exc

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {
    ".git",
    ".venv",
    ".venv-joss",
    "venv",
    "build",
    "dist",
    "outputs",
    "downloads",
    ".pytest-tmp",
    "__pycache__",
}
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _repository_files(suffixes: set[str]) -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in suffixes
        and not SKIP_PARTS.intersection(path.relative_to(ROOT).parts)
    ]


def _local_target(raw: str) -> str | None:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        # Markdown permits an optional quoted title after the URL.
        target = re.split(r"\s+[\"']", target, maxsplit=1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    return unquote(target.split("#", 1)[0])


def check_markdown_links() -> list[str]:
    errors: list[str] = []
    for path in _repository_files({".md", ".markdown"}):
        text = path.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(text):
            target = _local_target(match.group(1))
            if target is None:
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                errors.append(f"{path.relative_to(ROOT)}: local link escapes repository: {target}")
                continue
            if not resolved.exists():
                line = text.count("\n", 0, match.start()) + 1
                errors.append(
                    f"{path.relative_to(ROOT)}:{line}: missing local link target: {target}"
                )
    return errors


def check_json() -> list[str]:
    errors: list[str] = []
    for path in _repository_files({".json"}):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")
    return errors


def check_yaml() -> list[str]:
    errors: list[str] = []
    paths = _repository_files({".yml", ".yaml"}) + [ROOT / "CITATION.cff"]
    for path in sorted(set(paths)):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid YAML: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{path.relative_to(ROOT)}: top-level YAML value must be an object")
    return errors


def check_pyproject() -> list[str]:
    try:
        payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"pyproject.toml: invalid TOML: {exc}"]
    project = payload.get("project")
    if not isinstance(project, dict) or not project.get("name") or not project.get("version"):
        return ["pyproject.toml: [project] name and version are required"]
    return []


def main() -> int:
    errors = [*check_markdown_links(), *check_json(), *check_yaml(), *check_pyproject()]
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Documentation checks: FAIL ({len(errors)} error(s))", file=sys.stderr)
        return 2
    print("Documentation checks: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
