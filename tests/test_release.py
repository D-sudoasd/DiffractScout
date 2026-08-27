from __future__ import annotations

import importlib.util
import json
import os
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
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation unavailable due to platform or permissions: {exc}")
    monkeypatch.setattr(module, "ROOT", root)

    with pytest.raises(SystemExit, match="must not be a symlink"):
        module._prepare_dist_dir("dist-link")


def test_preflight_dependency_check_reports_copyable_install_command(
    monkeypatch,
) -> None:
    module = _load_check_release()

    def missing_release_tools(name: str):
        return None if name in {"build", "twine"} else object()

    monkeypatch.setattr(module.importlib.util, "find_spec", missing_release_tools)
    with pytest.raises(SystemExit) as error:
        module._ensure_preflight_dependencies(skip_tests=False, skip_wheel=False)

    message = str(error.value)
    assert "build, twine" in message
    assert 'python -m pip install -e ".[test,release]"' in message


def test_preflight_dependency_check_does_not_require_release_tools_when_wheel_skipped(
    monkeypatch,
) -> None:
    module = _load_check_release()

    def missing_release_tools(name: str):
        return None if name in {"build", "twine"} else object()

    monkeypatch.setattr(module.importlib.util, "find_spec", missing_release_tools)
    module._ensure_preflight_dependencies(skip_tests=False, skip_wheel=True)


def test_preflight_dependency_check_reports_missing_pytest_when_tests_are_enabled(
    monkeypatch,
) -> None:
    module = _load_check_release()

    def missing_pytest(name: str):
        return None if name == "pytest" else object()

    monkeypatch.setattr(module.importlib.util, "find_spec", missing_pytest)
    with pytest.raises(SystemExit, match="Missing preflight tooling: pytest"):
        module._ensure_preflight_dependencies(skip_tests=False, skip_wheel=True)


def test_resolve_installed_launchers_uses_venv_layout_and_platform_suffix(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_check_release()

    posix_environment = tmp_path / "posix-venv"
    posix_bin = posix_environment / "bin"
    posix_bin.mkdir(parents=True)
    for name in module.DECLARED_ENTRYPOINTS:
        launcher = posix_bin / name
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        launcher.chmod(0o755)
    posix = module._resolve_installed_launchers(posix_environment, windows=False)
    assert posix == {name: (posix_bin / name).resolve() for name in module.DECLARED_ENTRYPOINTS}

    non_executable = posix_bin / "diffractscout-gui"
    non_executable.chmod(0o644)
    if os.access(non_executable, os.X_OK):
        # Windows does not model POSIX mode bits; force the same OS-level
        # result so the resolver's executable check remains covered there.
        real_access = module.os.access
        monkeypatch.setattr(
            module.os,
            "access",
            lambda path, mode: False
            if Path(path) == non_executable
            else real_access(path, mode),
        )
    with pytest.raises(SystemExit, match="not executable.*diffractscout-gui"):
        module._resolve_installed_launchers(posix_environment, windows=False)

    windows_environment = tmp_path / "windows-venv"
    windows_scripts = windows_environment / "Scripts"
    windows_scripts.mkdir(parents=True)
    for name in module.DECLARED_ENTRYPOINTS:
        (windows_scripts / f"{name}.exe").write_bytes(b"launcher")

    def reject_posix_permission_probe(path, mode):
        raise AssertionError(f"Windows launcher unexpectedly probed with os.access: {path}")

    monkeypatch.setattr(module.os, "access", reject_posix_permission_probe)
    windows = module._resolve_installed_launchers(windows_environment, windows=True)
    assert windows == {
        name: (windows_scripts / f"{name}.exe").resolve()
        for name in module.DECLARED_ENTRYPOINTS
    }

    (windows_scripts / "diffractscout-gui.exe").unlink()
    with pytest.raises(SystemExit, match="diffractscout-gui"):
        module._resolve_installed_launchers(windows_environment, windows=True)


def test_installed_entrypoint_metadata_contract_requires_declared_targets() -> None:
    module = _load_check_release()
    module._validate_installed_entrypoint_metadata(module.DECLARED_ENTRYPOINTS)

    missing = dict(module.DECLARED_ENTRYPOINTS)
    missing.pop("diffractscout-gui")
    with pytest.raises(SystemExit, match="missing=diffractscout-gui"):
        module._validate_installed_entrypoint_metadata(missing)

    redirected = dict(module.DECLARED_ENTRYPOINTS)
    redirected["diffractscout-gui"] = "diffractscout.cli:main"
    with pytest.raises(SystemExit, match="mismatched=diffractscout-gui"):
        module._validate_installed_entrypoint_metadata(redirected)


def test_release_receipt_records_installed_entrypoint_checks_without_repo_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_check_release()

    class FakeReadiness:
        @staticmethod
        def release_source_fingerprint() -> dict[str, object]:
            return {"ok": True, "sha256": "source-hash", "file_count": 3}

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_load_readiness_module", lambda: FakeReadiness)
    receipt = module._write_release_acceptance(
        "0.4.0",
        clean_wheel={
            "mode": "isolated-dependencies",
            "package": "dist/diffractscout-0.4.0-py3-none-any.whl",
            "source_tree_import": "rejected",
            "commands": (
                "pip-check,entrypoint-launchers,entrypoint-metadata,installed-entrypoints,"
                "version,demo,verify,benchmark,quick-export,verify"
            ),
        },
        preflight_source={"sha256": "source-hash"},
    )

    assert receipt == tmp_path / "build/release-preflight/release_acceptance.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    commands = set(payload["clean_wheel"]["commands"].split(","))
    assert {
        "pip-check",
        "demo",
        "verify",
        "benchmark",
        "quick-export",
        "entrypoint-launchers",
        "entrypoint-metadata",
        "installed-entrypoints",
    } <= commands
