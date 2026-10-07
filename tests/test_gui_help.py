from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from diffractscout.gui_help import HoverHelp
from diffractscout.gui_help_text import CHOICE_HELP, CONTROL_HELP, HELP_TEXT, VARIABLE_HELP
from diffractscout.gui_i18n import assert_language_parity, t


def _wait(root, milliseconds=80):
    deadline = time.monotonic() + milliseconds / 1000
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()


@pytest.fixture
def root():
    tk = pytest.importorskip("tkinter")
    for attempt in range(2):
        try:
            window = tk.Tk()
            break
        except tk.TclError as exc:
            if attempt == 1:
                pytest.skip(f"Tk display unavailable: {exc}")
    window.geometry("600x350+20+20")
    window.update()
    errors = []
    window.report_callback_exception = lambda *error: errors.append(error)
    yield window
    window.destroy()
    assert errors == []


def _descendants(widget):
    yield widget
    # Native drop-down children do not have Python widget objects.
    if widget.winfo_class() != "TCombobox":
        for child in widget.winfo_children():
            yield from _descendants(child)


def _assert_controls_covered(view, help_widgets):
    kinds = {"TButton", "TEntry", "TCombobox", "TCheckbutton", "TRadiobutton",
             "Text", "Listbox", "Treeview", "TNotebook", "TScrollbar", "TSpinbox"}
    registered = {str(widget) for widget in help_widgets}
    missing = [(str(widget), widget.winfo_class()) for widget in _descendants(view)
               if widget.winfo_class() in kinds and str(widget) not in registered]
    assert missing == []


def test_help_catalog_covers_both_languages_and_explains_units():
    assert_language_parity()
    assert set(HELP_TEXT["zh"]) == set(HELP_TEXT["en"])
    for key in set(CONTROL_HELP.values()) | set(VARIABLE_HELP.values()) | set(CHOICE_HELP.values()):
        for lang in ("zh", "en"):
            assert key in HELP_TEXT[lang]
            assert t(lang, key).strip() == t(lang, key)
            assert t(lang, key) != key
    assert "一半高度" in t("zh", "help_fwhm")
    assert "0.1 纳米" in t("zh", "help_d_min")
    assert "per atom" in t("en", "help_e_hull")
    assert "q=2π/d" in t("en", "help_choice_q")
    assert "g=1/d" in t("zh", "help_choice_g")


def test_entire_main_and_result_views_have_contextual_help():
    from diffractscout.gui import create_app
    tk = pytest.importorskip("tkinter")
    for attempt in range(2):
        try:
            app = create_app()
            break
        except tk.TclError as exc:
            if attempt == 1:
                pytest.skip(f"Tk display unavailable: {exc}")
    try:
        app.update()
        widgets = app.help.widgets + app.results_view.help.widgets
        _assert_controls_covered(app, widgets)
        for lang in ("zh", "en"):
            app._set_language(lang)
            for combo in app._translated_combos:
                choices = app.help._combo_choices[str(combo)]
                assert set(choices) == set(combo["values"])
                assert all(callable(text) and text() not in {"", "help_language"} for text in choices.values())
        # Unit explanations follow the selected mode, including both analysis tabs.
        app.input_mode.set("energy")
        for entry in app._radiation_value_widgets:
            assert "keV" in app.help._help[str(entry)].text()
        app.input_mode.set("wavelength")
        for entry in app._radiation_value_widgets:
            assert "0.1 nanometres" in app.help._help[str(entry)].text()
    finally:
        app.destroy()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_initial_cif_dialog_has_help_even_for_hidden_options(root, language):
    from diffractscout.gui_cifs import InitialCifDialog
    dialog = InitialCifDialog(root, language=language)
    try:
        root.update()
        _assert_controls_covered(dialog, dialog.help.widgets)
        dialog.basis_var.set("weight_percent")
        weight = dialog.help._help[str(dialog.percent_entry)].text()
        dialog.basis_var.set("atomic_percent")
        atomic = dialog.help._help[str(dialog.percent_entry)].text()
        assert weight != atomic
        assert ("质量" in weight and "原子数" in atomic) if language == "zh" else ("mass" in weight and "atom-count" in atomic)
        dialog.advanced_button.invoke()
        assert dialog.help._help[str(dialog.advanced_button)].text()
    finally:
        dialog.destroy()
        root.update()


def test_delayed_help_cancels_on_leave_and_click_preserves_action(root):
    from tkinter import ttk
    calls = []
    button = ttk.Button(root, text="Action", command=lambda: calls.append("clicked"))
    button.pack()
    root.update()
    help_view = HoverHelp(root, delay=25)
    help_view.add(button, "Choose files, then calculate.")
    event = dict(x=5, y=5, rootx=button.winfo_rootx() + 5, rooty=button.winfo_rooty() + 5)
    button.event_generate("<Enter>", **event)
    assert help_view.popup is None
    button.event_generate("<Leave>")
    _wait(root)
    assert help_view.popup is None
    button.event_generate("<Enter>", **event)
    _wait(root)
    assert help_view.popup is not None
    assert calls == []
    button.event_generate("<ButtonPress-1>", x=5, y=5)
    assert help_view.popup is None
    button.event_generate("<ButtonRelease-1>", x=5, y=5)
    assert calls == ["clicked"]
    help_view.destroy()


def test_focus_f1_escape_do_not_steal_focus_and_tip_stays_in_window(root):
    from tkinter import ttk
    entry = ttk.Entry(root)
    entry.place(relx=1, rely=1, anchor="se", width=140)
    root.update()
    help_view = HoverHelp(root, delay=25)
    message = "Enter a value. The next calculation will use it. " * 3
    help_view.add(entry, message)
    entry.focus_force()
    _wait(root)
    assert help_view.popup is not None
    assert root.focus_get() is entry
    popup = help_view.popup
    assert popup.winfo_rootx() >= root.winfo_rootx()
    assert popup.winfo_rooty() >= root.winfo_rooty()
    assert popup.winfo_rootx() + popup.winfo_width() <= root.winfo_rootx() + root.winfo_width()
    assert popup.winfo_rooty() + popup.winfo_height() <= root.winfo_rooty() + root.winfo_height()
    entry.event_generate("<Escape>")
    assert help_view.popup is None
    entry.event_generate("<F1>")
    assert help_view.popup is not None
    assert root.focus_get() is entry
    entry.event_generate("<KeyPress-a>")
    assert help_view.popup is None
    help_view.destroy()


def test_native_dropdown_options_explain_hovered_and_keyboard_rows(root):
    from tkinter import ttk
    combo = ttk.Combobox(root, values=("First", "Second"), state="readonly")
    combo.pack()
    combo.current(0)
    root.update()
    help_view = HoverHelp(root, delay=25)
    help_view.add_combobox(combo, "Choose a search.", {"First": "Search every group.", "Second": "Only search IDs."})
    combo.focus_force()
    root.update()
    combo.tk.call("ttk::combobox::Post", str(combo))
    listbox = str(combo) + ".popdown.f.l"
    root.update()
    bbox = combo.tk.splitlist(combo.tk.call(listbox, "bbox", 1))
    x, y = int(bbox[0]) + 3, int(bbox[1]) + 3
    root_x = int(combo.tk.call("winfo", "rootx", listbox)) + x
    root_y = int(combo.tk.call("winfo", "rooty", listbox)) + y
    # Dispatch the installed Tcl binding without moving the system pointer.
    # Windows coalesces generated Motion events on a non-active desktop.
    script = str(combo.tk.call("bind", listbox, "<Motion>"))
    assert script
    for token, value in (("%x", x), ("%y", y), ("%X", root_x), ("%Y", root_y)):
        script = script.replace(token, str(value))
    combo.tk.eval(script)
    _wait(root)
    assert help_view.popup is not None
    assert help_view._active_text == "Only search IDs."
    assert combo.get() == "First"  # Reading help does not select an option.
    combo.tk.call(listbox, "selection", "clear", 0, "end")
    combo.tk.call(listbox, "selection", "set", 0)
    combo.tk.call("event", "generate", listbox, "<KeyRelease-Down>")
    _wait(root)
    assert help_view._active_text == "Search every group."
    combo.tk.call("ttk::combobox::Unpost", str(combo))
    root.update()
    assert help_view.popup is None
    help_view.destroy()


def test_table_headings_notebook_tabs_and_destroy_cancel_pending_help(root):
    from tkinter import ttk
    frame = ttk.Frame(root)
    frame.pack(fill="both", expand=True)
    help_view = HoverHelp(frame, delay=25)
    tree = ttk.Treeview(frame, columns=("angle", "spacing"), show="headings", height=2)
    tree.pack()
    help_view.add_tree(tree, "Select a row.", {"angle": "Angle in degrees.", "spacing": "Distance between planes."})
    root.update()
    item = help_view._help[str(tree)]
    assert item.resolve(SimpleNamespace(x=15, y=5)) == "Angle in degrees."
    assert item.resolve(SimpleNamespace(x=220, y=5)) == "Distance between planes."
    notebook = ttk.Notebook(frame)
    notebook.pack()
    for title in ("Inputs", "Results"):
        notebook.add(ttk.Frame(notebook), text=title)
    help_view.add_notebook(notebook, ["Choose files.", "Read results."])
    notebook.select(1)
    assert help_view._help[str(notebook)].resolve(None) == "Read results."
    help_view.show(tree)
    after_id = help_view._after_id
    assert after_id
    frame.destroy()
    _wait(root)
    assert help_view._destroyed
    assert after_id not in root.tk.splitlist(root.tk.call("after", "info"))


def test_disabled_button_help_is_readable_without_enabling_action(root):
    from tkinter import ttk
    calls = []
    button = ttk.Button(root, text="Open result", state="disabled", command=lambda: calls.append(True))
    button.pack()
    root.update()
    help_view = HoverHelp(root, delay=25)
    help_view.add(button, "Run a calculation first, then open its folder.")
    button.event_generate("<Enter>", x=5, y=5, rootx=button.winfo_rootx() + 5, rooty=button.winfo_rooty() + 5)
    _wait(root)
    assert help_view.popup is not None
    button.invoke()
    assert button.instate(("disabled",)) and calls == []
    help_view.destroy()


def test_menu_help_describes_the_active_command_and_disappears(root):
    import tkinter as tk
    menu = tk.Menu(root, tearoff=False)
    menu.add_command(label="Prepare files", command=lambda: pytest.fail("Help must not run actions"))
    root.configure(menu=menu)
    root.update()
    help_view = HoverHelp(root, delay=25)
    help_view.add_menu(menu, {0: "Open a form to prepare starting files."})
    root.focus_force()
    root.update()
    menu.activate(0)
    # A Windows native menu has no mapped Tk window for event_generate.
    # Dispatch its installed callback with the real Tk event substitutions.
    binding = str(menu.bind("<<MenuSelect>>"))
    callback = binding.split("[", 1)[1].split(" ", 1)[0]
    substitutions = {"%W": str(menu), "%T": "35", "%X": str(root.winfo_rootx() + 15),
                     "%Y": str(root.winfo_rooty() + 15)}
    args = [substitutions.get(token, "0") for token in menu._subst_format]
    menu.tk.call(callback, *args)
    _wait(root)
    assert help_view.popup is not None
    assert help_view._active_text == "Open a form to prepare starting files."
    menu.activate("none")
    menu.tk.call(callback, *args)
    assert help_view.popup is None
    help_view.destroy()
