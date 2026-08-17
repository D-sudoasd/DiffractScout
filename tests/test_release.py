from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_release.py"


def _load_check_release():
    spec = importlib.util.spec_from_file_location("diffractscout_check_release", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_dist_dir_rejects_nonempty_directory_without_removing_files(tmp_path: Path) -> None:
    module = _load_check_release()
    dist = tmp_path / "dist"
    dist.mkdir()
    marker = dist / "existing.whl"
    marker.write_bytes(b"keep me")

    with pytest.raises(SystemExit, match="not empty"):
        module._prepare_dist_dir(str(dist))

    assert marker.read_bytes() == b"keep me"


def test_prepare_dist_dir_creates_missing_directory_and_formats_external_path(
    tmp_path: Path,
) -> None:
    module = _load_check_release()
    dist = tmp_path / "release-output"

    prepared = module._prepare_dist_dir(str(dist))

    assert prepared == dist.resolve()
    assert prepared.is_dir()
    assert module._display_path(prepared) == str(prepared)


def test_prepare_dist_dir_rejects_symlink_relative_to_repository_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_check_release()
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    link = root / "dist-link"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(module, "ROOT", root)

    with pytest.raises(SystemExit, match="must not be a symlink"):
        module._prepare_dist_dir("dist-link")
