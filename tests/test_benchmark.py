import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from diffractscout.benchmark import run_reference_benchmarks, verify_benchmark_bundle
from diffractscout.cli import main


def test_analytic_reference_benchmarks_pass(tmp_path: Path) -> None:
    output = tmp_path / "benchmark"
    report = run_reference_benchmarks(output)
    assert report["all_passed"]
    assert report["passed_checks"] == report["total_checks"]
    assert report["total_checks"] >= 30
    assert verify_benchmark_bundle(output)["ok"]
    assert not list(tmp_path.glob(".benchmark.backup-*"))
    assert not list(tmp_path.glob(".benchmark.diffractscout-lock"))
    assert not list(tmp_path.glob(".benchmark.benchmark-*"))


def test_benchmark_cli(tmp_path: Path) -> None:
    output = tmp_path / "benchmark-cli"
    assert main(["benchmark", "-o", str(output)]) == 0
    assert verify_benchmark_bundle(output)["all_passed"]


def test_benchmark_overwrite_requires_valid_bundle(tmp_path: Path) -> None:
    output = tmp_path / "unrelated"
    output.mkdir()
    (output / "user.txt").write_text("keep", encoding="utf-8")
    try:
        run_reference_benchmarks(output, overwrite=True)
    except FileExistsError:
        pass
    else:
        raise AssertionError("Expected refusal to overwrite an unrelated directory")
    assert (output / "user.txt").read_text(encoding="utf-8") == "keep"

def test_benchmark_bundle_is_reproducible_with_source_date_epoch(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1786492800")
    first = tmp_path / "benchmark-a"
    second = tmp_path / "benchmark-b"
    run_reference_benchmarks(first)
    run_reference_benchmarks(second)

    import json

    first_manifest = json.loads((first / "benchmark_manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second / "benchmark_manifest.json").read_text(encoding="utf-8"))
    first_entries = {item["path"]: item["sha256"] for item in first_manifest["files"]}
    second_entries = {item["path"]: item["sha256"] for item in second_manifest["files"]}
    assert first_entries == second_entries


def test_benchmark_manifest_includes_nested_same_named_manifest(tmp_path: Path) -> None:
    import diffractscout.benchmark as benchmark

    root = tmp_path / "nested-manifest"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "result.txt").write_text("root", encoding="utf-8")
    (nested / "benchmark_manifest.json").write_text("nested", encoding="utf-8")

    benchmark._build_manifest(root, all_passed=True)
    payload = json.loads((root / "benchmark_manifest.json").read_text(encoding="utf-8"))
    paths = {entry["path"] for entry in payload["files"]}
    assert "benchmark_manifest.json" not in paths
    assert "nested/benchmark_manifest.json" in paths


def test_benchmark_verifier_detects_unlisted_nested_manifest(tmp_path: Path) -> None:
    output = tmp_path / "nested-unlisted"
    run_reference_benchmarks(output)
    nested = output / "nested" / "benchmark_manifest.json"
    nested.parent.mkdir()
    nested.write_text("unlisted", encoding="utf-8")

    report = verify_benchmark_bundle(output)
    assert report["ok"] is False
    assert "Unlisted file: nested/benchmark_manifest.json" in report["errors"]


def test_benchmark_commit_preserves_external_target_and_backup_on_publication_race(
    tmp_path: Path, monkeypatch
) -> None:
    import diffractscout.benchmark as benchmark
    import diffractscout.pipeline as pipeline

    target = tmp_path / "benchmark-race"
    run_reference_benchmarks(target)
    expected_state = pipeline._capture_target_state(
        target,
        manifest_name="benchmark_manifest.json",
    )
    staging = tmp_path / "benchmark-staging"
    staging.mkdir()
    (staging / "benchmark_report.json").write_text("new", encoding="utf-8")
    benchmark._build_manifest(staging, all_passed=True)

    def publish_then_occupy(source: Path, destination: Path) -> None:
        assert source == staging
        destination.mkdir()
        (destination / "external.txt").write_text("keep", encoding="utf-8")
        raise FileExistsError("target appeared at benchmark publication")

    monkeypatch.setattr(pipeline, "_rename_directory_noreplace", publish_then_occupy)
    with pytest.raises(FileExistsError, match="target appeared at benchmark publication"):
        benchmark._commit_directory(
            target,
            staging,
            expected_state=expected_state,
        )

    assert (target / "external.txt").read_text(encoding="utf-8") == "keep"
    backups = sorted(tmp_path.glob(".benchmark-race.backup-*"))
    assert len(backups) == 1
    assert verify_benchmark_bundle(backups[0])["ok"]


def test_benchmark_commit_rejects_unlisted_external_file_before_isolation(
    tmp_path: Path,
) -> None:
    import diffractscout.benchmark as benchmark
    import diffractscout.pipeline as pipeline

    target = tmp_path / "benchmark-external"
    run_reference_benchmarks(target)
    expected_state = pipeline._capture_target_state(
        target,
        manifest_name="benchmark_manifest.json",
    )
    (target / "external.txt").write_text("keep", encoding="utf-8")
    staging = tmp_path / "benchmark-staging"
    staging.mkdir()
    (staging / "benchmark_report.json").write_text("new", encoding="utf-8")
    benchmark._build_manifest(staging, all_passed=True)

    with pytest.raises(FileExistsError, match="unlisted files"):
        benchmark._commit_directory(
            target,
            staging,
            expected_state=expected_state,
        )

    assert (target / "external.txt").read_text(encoding="utf-8") == "keep"
    assert not list(tmp_path.glob(".benchmark-external.backup-*"))


def test_benchmark_commit_rejects_external_file_added_to_empty_target(
    tmp_path: Path,
) -> None:
    import diffractscout.benchmark as benchmark

    target = tmp_path / "empty-benchmark-target"
    target.mkdir()
    expected_state = benchmark._capture_target_state(
        target,
        manifest_name="benchmark_manifest.json",
    )
    (target / "external.txt").write_text("keep", encoding="utf-8")
    staging = tmp_path / "empty-benchmark-staging"
    staging.mkdir()
    (staging / "benchmark_report.json").write_text("new", encoding="utf-8")
    benchmark._build_manifest(staging, all_passed=True)

    with pytest.raises(FileExistsError, match="no benchmark_manifest.json"):
        benchmark._commit_directory(target, staging, expected_state=expected_state)
    assert (target / "external.txt").read_text(encoding="utf-8") == "keep"


def test_benchmark_duplicate_manifest_path_rejects_verifier_and_state_snapshot(
    tmp_path: Path,
) -> None:
    import diffractscout.pipeline as pipeline

    target = tmp_path / "duplicate-benchmark"
    run_reference_benchmarks(target)
    manifest_path = target / "benchmark_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"].append(dict(payload["files"][0]))
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    report = verify_benchmark_bundle(target)
    assert report["ok"] is False
    assert any("Duplicate manifest path" in error for error in report["errors"])
    with pytest.raises(FileExistsError, match="Duplicate benchmark manifest path"):
        pipeline._capture_target_state(
            target,
            manifest_name="benchmark_manifest.json",
        )
    assert target.is_dir()
    assert manifest_path.is_file()
    assert not list(tmp_path.glob(".duplicate-benchmark.backup-*"))


@pytest.mark.parametrize(
    "manifest_payload, expected",
    [
        ([{"path": "x"}], "root must be a JSON object"),
        ({"schema": "diffractscout_benchmark_manifest_v1", "files": [
            {"path": "C:\\outside.txt", "size_bytes": 1, "sha256": "x"}
        ]}, "Unsafe manifest path"),
        ({"schema": "diffractscout_benchmark_manifest_v1", "files": [
            {"path": "../outside.txt", "size_bytes": 1, "sha256": "x"}
        ]}, "Unsafe manifest path"),
    ],
)
def test_benchmark_verifier_rejects_malformed_or_unsafe_manifest_paths(
    tmp_path: Path, manifest_payload: object, expected: str
) -> None:
    output = tmp_path / "malformed"
    output.mkdir()
    (output / "benchmark_manifest.json").write_text(
        json.dumps(manifest_payload), encoding="utf-8"
    )
    report = verify_benchmark_bundle(output)
    assert report["ok"] is False
    assert any(expected in error for error in report["errors"])


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


def test_benchmark_rejects_real_reparse_point_final_and_parent(tmp_path: Path) -> None:
    import diffractscout.benchmark as benchmark

    reparse_component, cleanup = _real_directory_reparse_point(tmp_path)
    try:
        assert benchmark._is_reparse_point(reparse_component)
        for output in (reparse_component, reparse_component / "nested" / "bundle"):
            with pytest.raises(FileExistsError, match="reparse-point"):
                benchmark._prepare_target(output, overwrite=False)
    finally:
        cleanup()


def test_benchmark_reparse_detector_reads_raw_windows_attribute() -> None:
    import diffractscout.benchmark as benchmark

    class RawAttributePath:
        def stat(self, *, follow_symlinks: bool = True) -> object:
            assert follow_symlinks is False
            return SimpleNamespace(st_file_attributes=0x0400)

        @staticmethod
        def is_symlink() -> bool:
            return False

    assert benchmark._is_reparse_point(RawAttributePath())  # type: ignore[arg-type]
