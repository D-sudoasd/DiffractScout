import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from diffractscout.cli import main as cli_main
from diffractscout.pipeline import analyze_cifs
from diffractscout.utils import sha256_file
from diffractscout.validation import verify_bundle


def test_tamper_is_detected(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    analyze_cifs([demo_inputs], output, include_excel=False)
    assert verify_bundle(output)["ok"]
    with (output / "phase_summary.csv").open("a", encoding="utf-8") as handle:
        handle.write("tamper\n")
    report = verify_bundle(output)
    assert not report["ok"]
    assert any("hash mismatch" in error for error in report["errors"])


def test_unlisted_file_is_detected(demo_inputs: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle-unlisted"
    analyze_cifs([demo_inputs], output, include_excel=False)
    (output / "unlisted.txt").write_text("extra", encoding="utf-8")
    report = verify_bundle(output)
    assert not report["ok"]
    assert "unexpected unlisted file: unlisted.txt" in report["errors"]


def test_malformed_manifest_size_is_reported_without_crash(demo_inputs: Path, tmp_path: Path) -> None:
    import json

    output = tmp_path / "bundle-malformed"
    analyze_cifs([demo_inputs], output, include_excel=False)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["size_bytes"] = "not-an-integer"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = verify_bundle(output)
    assert not report["ok"]
    assert any("invalid size_bytes" in error for error in report["errors"])


def test_duplicate_manifest_path_is_rejected(demo_inputs: Path, tmp_path: Path) -> None:
    import json

    output = tmp_path / "bundle-duplicate"
    analyze_cifs([demo_inputs], output, include_excel=False)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(dict(manifest["files"][0]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = verify_bundle(output)
    assert not report["ok"]
    assert any("duplicate manifest path" in error for error in report["errors"])


def _real_directory_reparse_point(tmp_path: Path) -> tuple[Path, callable]:
    target = tmp_path / "junction-target"
    target.mkdir()
    link = tmp_path / "junction-like"
    if os.name == "nt":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            pytest.skip("PowerShell is unavailable; cannot create a real Windows junction")
        environment = os.environ.copy()
        environment["DIFRACTSCOUT_JUNCTION_TARGET"] = str(target)
        environment["DIFRACTSCOUT_JUNCTION_LINK"] = str(link)
        command = (
            "$ErrorActionPreference='Stop'; "
            "New-Item -ItemType Junction "
            "-Path $env:DIFRACTSCOUT_JUNCTION_LINK "
            "-Target $env:DIFRACTSCOUT_JUNCTION_TARGET | Out-Null"
        )
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(
                "Windows junction creation unavailable: "
                + (completed.stderr or completed.stdout).strip()
            )

        def cleanup() -> None:
            subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Remove-Item -LiteralPath $env:DIFRACTSCOUT_JUNCTION_LINK -Force",
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        return link, cleanup
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"POSIX directory symlink creation unavailable: {exc}")
    return link, link.unlink


def test_verify_rejects_real_reparse_root_parent_and_cli_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import diffractscout.validation as validation

    reparse_component, cleanup = _real_directory_reparse_point(tmp_path)
    try:
        assert validation._is_reparse_point(reparse_component)
        for supplied in (
            reparse_component,
            reparse_component / "bundle",
            reparse_component / "bundle" / "manifest.json",
        ):
            report = verify_bundle(supplied)
            assert not report["ok"]
            assert any("reparse" in error.lower() for error in report["errors"])
            assert cli_main(["verify", str(supplied)]) == 2
            assert "PASS" not in capsys.readouterr().out
    finally:
        cleanup()


def test_verify_rejects_reparse_manifest_file_component(
    demo_inputs: Path, tmp_path: Path
) -> None:
    output = tmp_path / "bundle-reparse-file"
    analyze_cifs([demo_inputs], output, include_excel=False)
    target = tmp_path / "manifest-file-target"
    target.mkdir()
    payload = target / "payload.txt"
    payload.write_text("payload", encoding="utf-8")
    link = output / "reparse-dir"
    cleanup: callable
    if os.name == "nt":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            pytest.skip("PowerShell is unavailable; cannot create a real Windows junction")
        environment = os.environ.copy()
        environment["DIFRACTSCOUT_JUNCTION_TARGET"] = str(target)
        environment["DIFRACTSCOUT_JUNCTION_LINK"] = str(link)
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "$ErrorActionPreference='Stop'; "
                    "New-Item -ItemType Junction "
                    "-Path $env:DIFRACTSCOUT_JUNCTION_LINK "
                    "-Target $env:DIFRACTSCOUT_JUNCTION_TARGET | Out-Null"
                ),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(
                "Windows junction creation unavailable: "
                + (completed.stderr or completed.stdout).strip()
            )

        def cleanup() -> None:
            subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Remove-Item -LiteralPath $env:DIFRACTSCOUT_JUNCTION_LINK -Force",
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
    else:
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"POSIX directory symlink creation unavailable: {exc}")
        cleanup = link.unlink
    try:
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append(
            {
                "path": "reparse-dir/payload.txt",
                "sha256": sha256_file(payload),
                "size_bytes": payload.stat().st_size,
                "role": "test",
            }
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        report = verify_bundle(output)
        assert not report["ok"]
        assert any("reparse" in error.lower() for error in report["errors"])
    finally:
        cleanup()


def test_verify_reparse_detector_reads_raw_windows_attribute() -> None:
    import diffractscout.validation as validation

    class RawAttributePath:
        def stat(self, *, follow_symlinks: bool = True) -> object:
            assert follow_symlinks is False
            return SimpleNamespace(st_file_attributes=0x0400)

        @staticmethod
        def is_symlink() -> bool:
            return False

    assert validation._is_reparse_point(RawAttributePath())  # type: ignore[arg-type]
