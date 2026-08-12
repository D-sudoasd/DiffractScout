from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "archive_tree.py"
SPEC = importlib.util.spec_from_file_location("diffractscout_archive_tree", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reproducible_archive_is_byte_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "evidence"
    (source / "nested").mkdir(parents=True)
    # Write exact fixture bytes so the archive contract is tested independently
    # of platform-specific text newline translation.
    (source / "z.txt").write_bytes(b"zeta\n")
    (source / "nested" / "a.json").write_bytes(b'{"a": 1}\n')
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1786492800")

    first = MODULE.create_reproducible_zip(source, tmp_path / "first.zip", root_name="bundle")
    second = MODULE.create_reproducible_zip(source, tmp_path / "second.zip", root_name="bundle")

    assert _sha256(first) == _sha256(second)
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        assert archive.namelist() == ["bundle/nested/a.json", "bundle/z.txt"]
        assert archive.read("bundle/nested/a.json") == b'{"a": 1}\n'


def test_archive_output_cannot_be_inside_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.txt").write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the source"):
        MODULE.create_reproducible_zip(source, source / "archive.zip")
