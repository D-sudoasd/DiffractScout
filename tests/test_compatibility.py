from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from diffractscout.cli import main
from diffractscout.compat import launcher
from diffractscout.compat.paths import user_data_dir


def test_compat_help_does_not_require_optional_engines(capsys):
    assert main(["compat", "--help"]) == 0
    assert "phasescout" in capsys.readouterr().out


def test_dispatch_preserves_upstream_options(monkeypatch):
    calls = []

    class FakeModule:
        @staticmethod
        def main(argv):
            calls.append(argv)
            return 3

    monkeypatch.setattr(launcher.importlib, "import_module", lambda name: FakeModule)
    assert main(["compat", "phasescout", "Ti-Al", "--dry-run"]) == 3
    assert calls == [["Ti-Al", "--dry-run"]]


def test_missing_engine_reports_install_command(monkeypatch, capsys):
    def missing(name):
        raise ModuleNotFoundError("pymatgen")

    monkeypatch.setattr(launcher.importlib, "import_module", missing)
    assert launcher.dispatch("cif2peaks", []) == 2
    assert "diffractscout[complete]" in capsys.readouterr().err


def test_data_directory_is_user_writable_not_package_relative(tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFRACTSCOUT_DATA_DIR", str(tmp_path / "user-data"))
    assert user_data_dir() == tmp_path / "user-data"
    assert not user_data_dir().exists()  # Reading settings has no side effects.


def test_runtime_sources_are_included_and_have_license():
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / "docs/COMPAT_SOURCE_INVENTORY.json").read_text())
    for name, project in inventory.items():
        assert len(project["commit"]) == 40
        for record in project["files"]:
            filename = Path(record["source"]).name
            if filename == "fetch_possible_phases.py":
                filename = "cli.py"
            assert (root / "src/diffractscout/compat" / name / filename).is_file()
            assert len(record["sha256"]) == 64


def test_portable_rejects_incomplete_runtime_and_preserves_folder(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("portable_builder", root / "scripts/build_windows_portable.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = tmp_path / "DiffractScout"
    folder.mkdir()
    for name in ("DiffractScout.exe", "LICENSE", "NOTICE.md", "README.md", "self_test.bat", "examples/demo.cif", "_internal/tcl/init.tcl"):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    output = tmp_path / "portable.zip"
    with pytest.raises(FileNotFoundError, match="tk.tcl"):
        module.package_portable_app(folder, output)
    assert not output.exists()
    (folder / "_internal/tcl/tk.tcl").write_text("fixture")
    module.package_portable_app(folder, output)
    with ZipFile(output) as archive:
        assert "DiffractScout/_internal/tcl/init.tcl" in archive.namelist()
        assert "DiffractScout/DiffractScout.exe" in archive.namelist()


def test_inherited_gui_can_construct_without_starting_event_loop(monkeypatch, tmp_path):
    pytest.importorskip("pymatgen.core")
    import tkinter as tk
    from diffractscout.compat.cif2peaks import gui as peaks
    from diffractscout.compat.phasescout import app as phases

    try:
        probe = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    probe.destroy()
    monkeypatch.setattr(phases, "CONFIG_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(phases, "DEFAULT_DOWNLOAD_DIR", tmp_path)
    root = tk.Tk()
    try:
        phases.PhaseScoutApp(root)
        root.update_idletasks()
        assert root.winfo_children()
    finally:
        root.destroy()
    captured = []

    def close_after_construction(root, *args, **kwargs):
        root.update_idletasks()
        captured.append(bool(root.winfo_children()))
        root.destroy()

    monkeypatch.setattr(tk.Tk, "mainloop", close_after_construction)
    assert peaks.main([]) == 0
    assert captured == [True]
