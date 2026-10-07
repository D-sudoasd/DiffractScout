from __future__ import annotations

import pytest

from diffractscout.compat.cif2peaks.gui import (
    GUI_FIGURE_PRESET_TOOLTIP_KEYS,
    GUI_PATTERN_AXIS_TOOLTIP_KEYS,
    GUI_PREVIEW_HEADING_TOOLTIP_KEYS,
    GUI_TEXT,
    GUI_TOOLTIP_KEYS,
    GUI_XRAY_TOOLTIP_KEYS,
    GUI_XRAY_PRESET_LABELS,
    GUI_PUBLICATION_PRESET_LABELS,
    _gui_text,
)


def _tkinter_or_skip():
    return pytest.importorskip("tkinter")


def _assert_interactive_help_coverage(view, registered):
    kinds = {"TButton", "TEntry", "TCombobox", "TCheckbutton", "TSpinbox",
             "TNotebook", "Treeview", "Text", "Listbox", "TScrollbar"}
    covered = {str(widget) for widget in registered}
    pending = [view]
    missing = []
    while pending:
        widget = pending.pop()
        kind = widget.winfo_class()
        if kind in kinds and str(widget) not in covered:
            missing.append((str(widget), kind))
        if kind != "TCombobox":
            pending.extend(widget.winfo_children())
    assert missing == []


def test_cif2peaks_help_copy_and_choice_maps_are_bilingual() -> None:
    tooltip_keys = set(GUI_TOOLTIP_KEYS.values())
    tooltip_keys.update(GUI_XRAY_TOOLTIP_KEYS.values())
    tooltip_keys.update(GUI_PATTERN_AXIS_TOOLTIP_KEYS.values())
    tooltip_keys.update(GUI_FIGURE_PRESET_TOOLTIP_KEYS.values())
    tooltip_keys.update(GUI_PREVIEW_HEADING_TOOLTIP_KEYS.values())
    tooltip_keys.update(
        {
            "tooltip_cij_cell",
            "tooltip_cif_list_item",
            "tooltip_activity_item",
            "tooltip_tree_resize",
        }
    )

    assert set(GUI_TEXT["zh"]) == set(GUI_TEXT["en"])
    for key in tooltip_keys:
        assert key in GUI_TEXT["zh"]
        assert key in GUI_TEXT["en"]
        args = {"row": 1, "column": 2, "name": "Fe", "path": "Fe.cif", "message": "Ready"}
        assert _gui_text("zh", key, **args).strip()
        assert _gui_text("en", key, **args).strip()

    assert set(GUI_XRAY_TOOLTIP_KEYS) == set(GUI_XRAY_PRESET_LABELS)
    assert set(GUI_FIGURE_PRESET_TOOLTIP_KEYS) == set(GUI_PUBLICATION_PRESET_LABELS)
    assert set(GUI_PATTERN_AXIS_TOOLTIP_KEYS) == {"two_theta", "d_spacing", "q", "g"}
    assert set(GUI_PREVIEW_HEADING_TOOLTIP_KEYS) == {
        "display_name", "formula", "space_group", "peaks", "warning", "elastic"
    }


def test_phase_scout_help_covers_actions_tables_tabs_and_scrollbars(
    monkeypatch, tmp_path
) -> None:
    tkinter = _tkinter_or_skip()
    from diffractscout.compat.phasescout import app as phases

    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    monkeypatch.setattr(phases, "CONFIG_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(phases, "DEFAULT_DOWNLOAD_DIR", tmp_path / "downloads")

    try:
        app = phases.PhaseScoutApp(root)
        root.update_idletasks()
        registered = app.help.widgets
        _assert_interactive_help_coverage(root, registered)
        for widget in (
            app.api_key_entry,
            app.save_api_key_button,
            app.clear_api_key_button,
            app.output_dir_entry,
            app.choose_output_button,
            app.conventional_cell_check,
            app.include_elasticity_check,
            app.main_notebook,
            app.mpid_text,
            app.download_mpid_button,
            app.chemsys_entry,
            app.max_results_spinbox,
            app.search_button,
            app.results_tree,
            app.download_selected_button,
            app.download_all_button,
            app.log_text,
        ):
            assert widget in registered
        assert sum(widget.winfo_class() == "TScrollbar" for widget in registered) >= 2
    finally:
        root.destroy()


def test_cif2peaks_help_registers_controls_and_each_dropdown_item(monkeypatch) -> None:
    tkinter = _tkinter_or_skip()
    from diffractscout import gui_help
    from diffractscout.compat.cif2peaks import gui as cif2peaks

    try:
        probe = tkinter.Tk()
    except tkinter.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    probe.destroy()

    class RecordingHelp(gui_help.HoverHelp):
        instances: list[RecordingHelp] = []

        def __init__(self, owner):
            self.widget_classes: list[str] = []
            self.combobox_choices: list[set[str]] = []
            self.tree_headings: list[set[str]] = []
            self.scrollbar_parents: list[str] = []
            super().__init__(owner)
            self.instances.append(self)

        def add(self, widget, text, *, resolve=None):
            self.widget_classes.append(widget.winfo_class())
            return super().add(widget, text, resolve=resolve)

        def add_combobox(self, combo, body, choices):
            self.combobox_choices.append(set(choices))
            return super().add_combobox(combo, body, choices)

        def add_tree(self, tree, body, headings):
            self.tree_headings.append(set(headings))
            return super().add_tree(tree, body, headings)

        def add_scrollbars(self, parent, text):
            self.scrollbar_parents.append(str(parent))
            return super().add_scrollbars(parent, text)

    monkeypatch.setattr(gui_help, "HoverHelp", RecordingHelp)

    def close_after_construction(root, *_args, **_kwargs):
        try:
            root.update_idletasks()
            _assert_interactive_help_coverage(root, RecordingHelp.instances[-1].widgets)
        finally:
            root.destroy()

    monkeypatch.setattr(tkinter.Tk, "mainloop", close_after_construction)
    cif2peaks._launch_tk_app()

    assert RecordingHelp.instances
    help_manager = RecordingHelp.instances[-1]
    assert {"TEntry", "TButton", "TCheckbutton", "TCombobox", "Treeview", "Listbox", "TScrollbar"} <= set(help_manager.widget_classes)
    assert set(GUI_XRAY_PRESET_LABELS) in help_manager.combobox_choices
    assert set(GUI_PATTERN_AXIS_TOOLTIP_KEYS) in help_manager.combobox_choices
    assert set(GUI_PUBLICATION_PRESET_LABELS) in help_manager.combobox_choices
    assert help_manager.tree_headings == [set(GUI_PREVIEW_HEADING_TOOLTIP_KEYS) | {"__resize__"}]
    assert len(help_manager.scrollbar_parents) >= 3
