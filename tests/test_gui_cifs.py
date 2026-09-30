from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import diffractscout.gui_cifs as gui_cifs


def _form(**overrides):
    values = {
        "lang": "zh",
        "composition": "Ti-Al-V",
        "basis": "nominal",
        "nominal": "TC4",
        "percent_text": "",
        "host": "",
        "output_dir": "out/initial",
        "parameter_file": "",
        "offline": True,
        "api_key": "typed-key",
        "phase_alpha": True,
        "phase_beta": True,
        "phase_alpha-double-prime": True,
    }
    values.update(overrides)
    return values


def test_nominal_form_maps_to_prepare_api_without_network(tmp_path: Path) -> None:
    kwargs = gui_cifs.prepare_kwargs_from_form(
        _form(output_dir=str(tmp_path / "fresh")), environment_key="environment-key"
    )

    assert kwargs == {
        "composition": "Ti-Al-V",
        "output_dir": (tmp_path / "fresh").resolve(),
        "nominal": "TC4",
        "phases": ["alpha", "beta", "alpha-double-prime"],
        "host": "",
        "templates": {},
        "parameter_file": None,
        "offline": True,
        "api_key": None,
        "max_subsystems": 64,
    }


@pytest.mark.parametrize(
    ("basis", "expected_key", "amounts"),
    (
        ("weight_percent", "weight_percent", "Ti=90,Al=6,V=4"),
        ("atomic_percent", "atomic_percent", "Ti=86,Al=10,V=4"),
    ),
)
def test_percent_form_maps_only_selected_composition_basis(
    tmp_path: Path, basis: str, expected_key: str, amounts: str
) -> None:
    kwargs = gui_cifs.prepare_kwargs_from_form(
        _form(
            basis=basis,
            nominal="ignored grade",
            percent_text=amounts,
            offline=False,
            output_dir=str(tmp_path / "fresh"),
        ),
        environment_key="environment-key",
    )

    assert kwargs[expected_key] == amounts
    other_key = "weight_percent" if expected_key == "atomic_percent" else "atomic_percent"
    assert other_key not in kwargs
    assert kwargs["api_key"] == "typed-key"


def test_environment_key_is_used_only_when_online_and_no_key_was_typed(tmp_path: Path) -> None:
    kwargs = gui_cifs.prepare_kwargs_from_form(
        _form(offline=False, api_key="", output_dir=str(tmp_path / "fresh")),
        environment_key="environment-key",
    )

    assert kwargs["api_key"] == "environment-key"
    assert "api_key" not in str(kwargs["output_dir"])


def test_selected_templates_and_parameter_file_are_paths(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha.cif"
    alpha.write_text("data_alpha\n", encoding="utf-8")
    parameters = tmp_path / "parameters.json"
    parameters.write_text("{}\n", encoding="utf-8")
    kwargs = gui_cifs.prepare_kwargs_from_form(
        _form(
            phase_beta=False,
            phase_alpha=False,
            **{
                "phase_alpha-double-prime": True,
                "template_alpha-double-prime": str(alpha),
            },
            parameter_file=str(parameters),
            output_dir=str(tmp_path / "fresh"),
        )
    )

    assert kwargs["phases"] == ["alpha-double-prime"]
    assert kwargs["templates"] == {"alpha-double-prime": alpha.resolve()}
    assert kwargs["parameter_file"] == parameters.resolve()


def test_invalid_form_fails_before_api_call(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="至少选择一个相"):
        gui_cifs.prepare_kwargs_from_form(
            _form(
                phase_alpha=False,
                phase_beta=False,
                **{"phase_alpha-double-prime": False},
                output_dir=str(tmp_path / "fresh"),
            )
        )

    with pytest.raises(ValueError, match="Ti=90,Al=6,V=4"):
        gui_cifs.prepare_kwargs_from_form(
            _form(
                basis="weight_percent",
                percent_text="",
                output_dir=str(tmp_path / "fresh"),
            )
        )

    with pytest.raises(ValueError, match="Ti=86,Al=10,V=4"):
        gui_cifs.prepare_kwargs_from_form(
            _form(
                basis="atomic_percent",
                percent_text="",
                output_dir=str(tmp_path / "fresh"),
            )
        )


def _make_hidden_dialog(**kwargs):
    if gui_cifs.tk is None:
        pytest.skip("Tkinter unavailable")
    last_error = None
    for _attempt in range(2):
        root = None
        try:
            root = gui_cifs.tk.Tk()
            root.withdraw()
            dialog = gui_cifs.InitialCifDialog(root, **kwargs)
            dialog.withdraw()
            root.update_idletasks()
            return root, dialog
        except gui_cifs.tk.TclError as exc:
            last_error = exc
            if root is not None:
                try:
                    root.destroy()
                except gui_cifs.tk.TclError:
                    pass
    pytest.skip(f"Tk display unavailable: {last_error}")


def _wait_for(root, condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if condition():
            return
        time.sleep(0.01)
    pytest.fail("Timed out waiting for the dialog worker result")


def test_hidden_dialog_accepts_entries_and_loads_result_paths_on_tk_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "prepared"
    source_thread = threading.get_ident()
    loaded: list[tuple[list[Path], int]] = []
    opened: list[Path] = []

    def prepare(**kwargs):
        assert kwargs["composition"] == "Ti-Al-V"
        assert kwargs["nominal"] == "TC4"
        assert kwargs["phases"] == ["alpha"]
        output.mkdir()
        cif = output / "alpha.cif"
        cif.write_text("data_alpha\n", encoding="utf-8")
        report = output / "report.md"
        report.write_text("starting model\n", encoding="utf-8")
        return SimpleNamespace(
            output_dir=output,
            report_path=report,
            index_path=output / "index.csv",
            manifest_path=output / "manifest.json",
            exit_code=3,
            records=(
                SimpleNamespace(
                    phase="alpha",
                    status="prepared",
                    cif_path=cif,
                    note="Packaged prototype; lattice is an initial assumption.",
                ),
            ),
        )

    monkeypatch.setattr(gui_cifs, "_prepare_cifs", prepare)
    monkeypatch.setattr(gui_cifs, "_open_path", lambda path: opened.append(path))
    root, dialog = _make_hidden_dialog(
        language="zh",
        on_load=lambda paths: loaded.append((paths, threading.get_ident())),
    )
    try:
        dialog.composition_entry.delete(0, "end")
        dialog.composition_entry.insert(0, "Ti-Al-V")
        dialog.output_entry.delete(0, "end")
        dialog.output_entry.insert(0, str(output))
        dialog.phase_vars["beta"].set(False)
        dialog.phase_vars["alpha-double-prime"].set(False)
        dialog.run_button.invoke()

        _wait_for(root, lambda: not dialog._running)
        assert dialog.tree.get_children() == ("0",)
        assert Path(dialog._result.records[0].cif_path) == output / "alpha.cif"
        assert "部分完成" in dialog.status_var.get()
        assert "initial assumption" in dialog.details.get("1.0", "end")
        assert str((output / "alpha.cif").resolve()) in dialog.details.get("1.0", "end")

        dialog.report_button.invoke()
        dialog.folder_button.invoke()
        assert opened == [output / "report.md", output]
        dialog.load_button.invoke()
        assert loaded == [([output / "alpha.cif"], source_thread)]
    finally:
        dialog._close()
        root.destroy()


def test_hidden_dialog_surfaces_worker_failure_and_reenables_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(**_kwargs):
        raise RuntimeError("parameter JSON is invalid")

    monkeypatch.setattr(gui_cifs, "_prepare_cifs", fail)
    root, dialog = _make_hidden_dialog(language="en")
    try:
        dialog.output_entry.delete(0, "end")
        dialog.output_entry.insert(0, str(tmp_path / "fresh"))
        dialog.run_button.invoke()
        _wait_for(root, lambda: not dialog._running)

        assert "failed" in dialog.status_var.get().lower()
        assert "parameter JSON is invalid" in dialog.details.get("1.0", "end")
        assert str(dialog.run_button.cget("state")) == "normal"
    finally:
        dialog._close()
        root.destroy()


def test_closing_dialog_during_worker_has_no_tk_callback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    def delayed(**kwargs):
        started.set()
        release.wait(timeout=2)
        return SimpleNamespace(
            output_dir=kwargs["output_dir"],
            report_path=None,
            exit_code=2,
            records=(),
        )

    monkeypatch.setattr(gui_cifs, "_prepare_cifs", delayed)
    root, dialog = _make_hidden_dialog(language="en")
    dialog.output_entry.delete(0, "end")
    dialog.output_entry.insert(0, str(tmp_path / "fresh"))
    dialog.run_button.invoke()
    assert started.wait(timeout=2)
    dialog._close()
    release.set()
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not dialog._events.qsize():
            root.update()
            time.sleep(0.01)
        root.update()
    finally:
        root.destroy()


def test_small_screen_scroll_keeps_status_and_actions_visible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if gui_cifs.tk is None:
        pytest.skip("Tkinter unavailable")
    monkeypatch.setattr(gui_cifs.InitialCifDialog, "winfo_screenheight", lambda _self: 768)
    monkeypatch.setattr(
        gui_cifs,
        "_prepare_cifs",
        lambda **kwargs: SimpleNamespace(
            output_dir=kwargs["output_dir"], report_path=None, exit_code=2, records=()
        ),
    )
    root = None
    try:
        root = gui_cifs.tk.Tk()
        root.attributes("-alpha", 0.0)
        root.deiconify()
        dialog = gui_cifs.InitialCifDialog(root, language="en")
        dialog.attributes("-alpha", 0.0)
        dialog.deiconify()
        root.update()
    except gui_cifs.tk.TclError as exc:
        if root is not None:
            try:
                root.destroy()
            except gui_cifs.tk.TclError:
                pass
        pytest.skip(f"Mapped Tk layout unavailable: {exc}")

    try:
        client_height = dialog.winfo_height()
        assert client_height <= 668
        assert dialog.minsize()[1] <= client_height
        assert dialog.minsize()[1] <= 668

        dialog._toggle_advanced()
        root.update()
        scroll_region = dialog._scroll_canvas.bbox("all")
        assert scroll_region is not None
        assert scroll_region[3] > dialog._scroll_canvas.winfo_height()
        dialog._scroll_canvas.yview_moveto(1.0)
        root.update()
        assert dialog._scroll_canvas.yview()[0] > 0

        pinned = (
            dialog.status_label,
            dialog.run_button,
            dialog.load_button,
            dialog.report_button,
            dialog.folder_button,
        )
        for widget in pinned:
            bottom = widget.winfo_rooty() + widget.winfo_height() - dialog.winfo_rooty()
            assert bottom <= client_height

        dialog.output_entry.delete(0, "end")
        dialog.output_entry.insert(0, str(tmp_path / "small_screen_output"))
        dialog.run_button.invoke()
        _wait_for(root, lambda: not dialog._running)
        assert "No CIF files" in dialog.status_var.get()
        assert str(dialog.run_button.cget("state")) == "normal"
    finally:
        dialog._close()
        root.destroy()


def test_offline_tc4_runs_real_service_through_gui_and_loads_cifs(
    tmp_path: Path,
) -> None:
    output = tmp_path / "offline_tc4"
    main_thread = threading.get_ident()
    loaded: list[tuple[list[Path], int]] = []
    root, dialog = _make_hidden_dialog(
        language="zh",
        on_load=lambda paths: loaded.append((paths, threading.get_ident())),
    )
    try:
        dialog.composition_entry.delete(0, "end")
        dialog.composition_entry.insert(0, "TC4")
        dialog.output_entry.delete(0, "end")
        dialog.output_entry.insert(0, str(output))
        dialog.offline_var.set(True)
        dialog.run_button.invoke()

        _wait_for(root, lambda: not dialog._running, timeout=30)

        assert dialog._result.exit_code == 0
        assert [record.phase for record in dialog._result.records] == [
            "alpha",
            "beta",
            "alpha-double-prime",
        ]
        assert all(record.status == "ready" for record in dialog._result.records)
        assert all(record.cif_path.is_file() for record in dialog._result.records)
        assert dialog._result.report_path.is_file()
        assert dialog._result.index_path.is_file()
        assert dialog._result.manifest_path.is_file()
        assert "完成" in dialog.status_var.get()
        assert [dialog.tree.set(item, "status") for item in dialog.tree.get_children()] == [
            "可用起始 CIF",
            "可用起始 CIF",
            "可用起始 CIF",
        ]

        dialog.load_button.invoke()
        assert loaded == [
            ([record.cif_path.resolve() for record in dialog._result.records], main_thread)
        ]
    finally:
        dialog._close()
        root.destroy()
