from pathlib import Path

from diffractscout.benchmark import run_reference_benchmarks, verify_benchmark_bundle
from diffractscout.cli import main


def test_analytic_reference_benchmarks_pass(tmp_path: Path) -> None:
    output = tmp_path / "benchmark"
    report = run_reference_benchmarks(output)
    assert report["all_passed"]
    assert report["passed_checks"] == report["total_checks"]
    assert report["total_checks"] >= 30
    assert verify_benchmark_bundle(output)["ok"]


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
