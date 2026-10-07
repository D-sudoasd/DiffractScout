"""Non-modal contextual help for native Tk controls, including their sub-items."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

try:
    import tkinter as tk
except ImportError:  # Keep numerical/CLI imports usable without Tk.
    tk = None  # type: ignore[assignment]

from .gui_theme import BORDER, CARD, TEXT

HelpText = str | Callable[[], str]


def _text(value: HelpText) -> str:
    return str(value() if callable(value) else value)


@dataclass
class _Help:
    widget: Any
    text: HelpText
    resolve: Callable[[Any], str] | None = None


class HoverHelp:
    """One delayed, non-focusable help bubble per view; F1 also opens it.

    Bindings are additive: help never replaces selection, typing, scrolling,
    or an action's callback. Text is resolved at display time for translation
    and changing selections. The owner controls all timers and popup lifetime.
    """

    def __init__(self, owner: Any, *, delay: int = 450) -> None:
        if tk is None:  # pragma: no cover - platform-dependent
            raise RuntimeError("Tk is required to display contextual help.")
        self.owner = owner
        self.root = owner.winfo_toplevel()
        self.delay = delay
        self.popup: Any = None
        self._after_id: str | None = None
        self._focus_after_id: str | None = None
        self._active: str | None = None
        self._active_text = ""
        self._help: dict[str, _Help] = {}
        self._bindings: list[tuple[Any, str, str]] = []
        self._native_bindings: list[tuple[str, str, str, str]] = []
        self._combo_choices: dict[str, Mapping[str, HelpText]] = {}
        self._combo_postcommands: list[tuple[Any, str, str]] = []
        self._native_combos: set[str] = set()
        self._scroll_text: HelpText = "Drag to see more items in this list."
        self._destroyed = False
        self._bind(owner, "<Destroy>", self._owner_destroyed)
        self._bind(self.root, "<Configure>", self._root_changed)
        self._bind(self.root, "<Unmap>", self._root_changed)
        self._bind(self.root, "<FocusOut>", self._window_focus_out)

    @property
    def widgets(self) -> tuple[Any, ...]:
        return tuple(item.widget for item in self._help.values())

    def _bind(self, widget: Any, sequence: str, callback: Callable[..., Any]) -> None:
        func_id = widget.bind(sequence, callback, add="+")
        if func_id:
            self._bindings.append((widget, sequence, func_id))

    def add(self, widget: Any, text: HelpText, *,
            resolve: Callable[[Any], str] | None = None) -> None:
        path = str(widget)
        first = path not in self._help
        self._help[path] = _Help(widget, text, resolve)
        if not first:
            return
        self._bind(widget, "<Enter>", lambda event: self.show(widget, event))
        self._bind(widget, "<Motion>", lambda event: self.show(widget, event))
        self._bind(widget, "<Leave>", lambda _event: self.hide())
        self._bind(widget, "<FocusIn>", lambda _event: self.show(widget))
        self._bind(widget, "<FocusOut>", lambda _event: self.hide())
        self._bind(widget, "<ButtonPress>", lambda _event: self.hide())
        self._bind(widget, "<KeyPress>", lambda _event: self.hide())
        self._bind(widget, "<MouseWheel>", lambda _event: self.hide())
        self._bind(widget, "<F1>", lambda _event: self._keyboard_show(widget))
        self._bind(widget, "<Escape>", lambda _event: self._dismiss())
        self._bind(widget, "<Destroy>", lambda _event: self.hide()
                   if self._active == path else None)

    def _keyboard_show(self, widget: Any) -> str:
        self.show(widget, immediate=True)
        return "break"

    def _dismiss(self) -> str | None:
        visible = self.popup is not None or self._after_id is not None
        self.hide()
        return "break" if visible else None

    def show(self, widget: Any, event: Any = None, *, immediate: bool = False) -> None:
        item = self._help.get(str(widget))
        if self._destroyed or item is None:
            return
        message = item.resolve(event) if item.resolve is not None else _text(item.text)
        if not message:
            self.hide()
            return
        if self._active == str(widget) and self._active_text == message:
            if not immediate or self.popup is not None:
                return
        self.hide()
        self._active = str(widget)
        self._active_text = message
        # Resolve coordinates now, while an event's selected row still exists.
        if event is None:
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height() + 8
        else:
            x = int(event.x_root) + 12
            y = int(event.y_root) + 18
        if immediate:
            self._display(widget, x, y)
        else:
            self._after_id = self.owner.after(self.delay, lambda: self._display(widget, x, y))

    def _display(self, widget: Any, x: int, y: int) -> None:
        self._after_id = None
        if self._destroyed or not widget.winfo_exists() or (
            not widget.winfo_ismapped() and widget.winfo_class() != "Menu"
        ):
            self.hide()
            return
        try:
            popup = tk.Toplevel(self.root, takefocus=False)
            self.popup = popup
            popup.withdraw()
            popup.overrideredirect(True)
            popup.attributes("-topmost", True)
            label = tk.Label(
                popup, text=self._active_text, justify="left", wraplength=360,
                background=CARD, foreground=TEXT, font="TkDefaultFont",
                relief="solid", borderwidth=1, highlightbackground=BORDER,
                padx=10, pady=7, takefocus=False,
            )
            label.pack()
            popup.update_idletasks()
            # Keep help inside the active window and the available screen.
            left = max(self.root.winfo_vrootx(), self.root.winfo_rootx()) + 4
            top = max(self.root.winfo_vrooty(), self.root.winfo_rooty()) + 4
            right = min(self.root.winfo_vrootx() + self.root.winfo_vrootwidth(),
                        self.root.winfo_rootx() + self.root.winfo_width()) - 4
            bottom = min(self.root.winfo_vrooty() + self.root.winfo_vrootheight(),
                         self.root.winfo_rooty() + self.root.winfo_height()) - 4
            width, height = popup.winfo_reqwidth(), popup.winfo_reqheight()
            if y + height > bottom:
                y = widget.winfo_rooty() - height - 8
            x = max(left, min(x, right - width))
            y = max(top, min(y, bottom - height))
            popup.geometry(f"+{x}+{y}")
            popup.deiconify()
        except tk.TclError:
            self.hide()

    def add_tree(self, tree: Any, body: HelpText, headings: Mapping[str, HelpText]) -> None:
        def resolve(event: Any) -> str:
            if event is not None and tree.identify_region(event.x, event.y) == "separator":
                return _text(headings.get("__resize__", body))
            if event is not None and tree.identify_region(event.x, event.y) == "heading":
                column = tree.identify_column(event.x)
                columns = tuple(tree["columns"])
                index = int(column[1:]) - 1
                name = columns[index] if 0 <= index < len(columns) else column
                return _text(headings.get(name, body))
            return _text(body)
        self.add(tree, body, resolve=resolve)

    def add_notebook(self, notebook: Any, tab_texts: Sequence[HelpText]) -> None:
        first = str(notebook) not in self._help
        def resolve(event: Any) -> str:
            try:
                index = notebook.index(f"@{event.x},{event.y}") if event is not None else notebook.index("current")
                return _text(tab_texts[index])
            except (tk.TclError, IndexError):
                return ""
        self.add(notebook, "", resolve=resolve)
        if first:
            self._bind(notebook, "<<NotebookTabChanged>>", lambda _event: self.hide())

    def add_combobox(self, combo: Any, body: HelpText, choices: Mapping[str, HelpText]) -> None:
        """Help for the current value and each native drop-down list item."""
        path = str(combo)
        first = path not in self._combo_choices
        self._combo_choices[path] = dict(choices)

        def current(_event: Any) -> str:
            choice = self._combo_choices[path].get(combo.get())
            return _text(body) + ("\n" + _text(choice) if choice is not None else "")

        self.add(combo, body, resolve=current)
        if first:
            previous = str(combo.cget("postcommand"))
            command = combo.register(lambda: self._prepare_choices(combo, previous))
            combo.configure(postcommand=command)
            self._combo_postcommands.append((combo, previous, command))

    def _prepare_choices(self, combo: Any, previous: str) -> None:
        self.hide()
        if previous:
            combo.tk.eval(previous)
        # ttk owns this Tcl listbox, which has no Python widget object.
        popdown = str(combo.tk.call("ttk::combobox::PopdownWindow", str(combo)))
        listbox = popdown + ".f.l"
        if listbox in self._native_combos:
            return
        if bool(int(combo.tk.call("winfo", "exists", listbox))):
            self._native_combos.add(listbox)
            for sequence in ("<Motion>", "<KeyRelease>", "<F1>"):
                self._bind_native(listbox, sequence,
                                  lambda x, y, X, Y, c=combo, box=listbox, s=sequence:
                                  self._show_choice(c, box, x, y, X, Y, s))
            for sequence in ("<Leave>", "<Unmap>", "<ButtonPress>"):
                self._bind_native(listbox, sequence, lambda *_args: self.hide())
            scrollbar = popdown + ".f.sb"
            self._bind_native(scrollbar, "<Enter>", lambda x, y, X, Y:
                              self._native_message(combo, self._scroll_text, x, y, X, Y))
            for sequence in ("<Leave>", "<Unmap>", "<ButtonPress>"):
                self._bind_native(scrollbar, sequence, lambda *_args: self.hide())

    def _bind_native(self, path: str, sequence: str, callback: Callable[..., Any]) -> None:
        command = self.owner.register(callback)
        script = f"{command} %x %y %X %Y"
        self.owner.tk.call("bind", path, sequence, "+" + script)
        self._native_bindings.append((path, sequence, command, script))

    def _show_choice(self, combo: Any, listbox: str, x: str, y: str, X: str, Y: str,
                     sequence: str) -> None:
        if not bool(int(combo.tk.call("winfo", "ismapped", listbox))):
            self.hide()
            return
        if sequence != "<Motion>":
            selected = combo.tk.splitlist(combo.tk.call(listbox, "curselection"))
            if not selected:
                return
            index = int(selected[0])
            bounds = combo.tk.splitlist(combo.tk.call(listbox, "bbox", index))
            if bounds:
                x, y = str(bounds[0]), str(bounds[1])
                X = str(int(combo.tk.call("winfo", "rootx", listbox)) + int(x))
                Y = str(int(combo.tk.call("winfo", "rooty", listbox)) + int(y))
        else:
            index = int(combo.tk.call(listbox, "nearest", y))
        values = tuple(combo["values"])
        if not 0 <= index < len(values):
            return
        message = self._combo_choices[str(combo)].get(str(values[index]))
        if message is None:
            self.hide()
            return
        self._native_message(combo, message, x, y, X, Y, immediate=sequence == "<F1>")

    def _native_message(self, combo: Any, message: HelpText,
                        x: str, y: str, X: str, Y: str, *, immediate: bool = False) -> None:
        # Use the existing combo as the anchor; do not change its value.
        item = self._help[str(combo)]
        original = item.resolve
        item.resolve = lambda _event: _text(message)
        try:
            event = SimpleNamespace(x=int(x), y=int(y), x_root=int(X), y_root=int(Y))
            self.show(combo, event, immediate=immediate)
        finally:
            item.resolve = original

    def add_menu(self, menu: Any, items: Mapping[int, HelpText]) -> None:
        self.add(menu, "", resolve=lambda _event: _text(items[menu.index("active")])
                 if menu.index("active") in items else "")
        self._bind(menu, "<<MenuSelect>>", lambda event: self.show(menu, event))
        self._bind(menu, "<Unmap>", lambda _event: self.hide())

    def add_scrollbars(self, parent: Any, text: HelpText) -> None:
        self._scroll_text = text
        if parent.winfo_class() == "TCombobox":
            return  # Its native popup is managed separately.
        if hasattr(parent, "help") and parent.help is not self:
            return  # An independent child view manages its own help.
        for child in parent.winfo_children():
            if child.winfo_class() in {"TScrollbar", "Scrollbar"} and str(child) not in self._help:
                self.add(child, text)
            self.add_scrollbars(child, text)

    def _root_changed(self, event: Any) -> None:
        if event.widget is self.root:
            self.hide()

    def _window_focus_out(self, _event: Any) -> None:
        # Focus can move between fields or to the native drop-down. Neither
        # should be mistaken for leaving the application.
        if not self._destroyed:
            if self._focus_after_id is None:
                self._focus_after_id = self.owner.after_idle(self._check_window_focus)

    def _check_window_focus(self) -> None:
        self._focus_after_id = None
        if self._destroyed:
            return
        focus = str(self.root.tk.call("focus"))
        if not focus or (focus not in self._native_combos and
                         str(self.root.tk.call("winfo", "toplevel", focus)) != str(self.root)):
            self.hide()

    def _owner_destroyed(self, event: Any) -> None:
        if event.widget is self.owner:
            self.destroy()

    def hide(self) -> None:
        if self._after_id is not None:
            try:
                self.owner.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self._active = None
        self._active_text = ""
        if self.popup is not None:
            popup, self.popup = self.popup, None
            try:
                popup.destroy()
            except tk.TclError:
                pass

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self.hide()
        if self._focus_after_id is not None:
            try:
                self.owner.after_cancel(self._focus_after_id)
            except tk.TclError:
                pass
            self._focus_after_id = None
        for widget, sequence, func_id in self._bindings:
            try:
                widget.unbind(sequence, func_id)
            except tk.TclError:
                pass
        for path, sequence, command, script in self._native_bindings:
            try:
                current = str(self.owner.tk.call("bind", path, sequence))
                self.owner.tk.call("bind", path, sequence, current.replace(script, ""))
                self.owner.deletecommand(command)
            except tk.TclError:
                pass
        for combo, previous, command in self._combo_postcommands:
            try:
                combo.configure(postcommand=previous)
                combo.deletecommand(command)
            except tk.TclError:
                pass
        self._bindings.clear()
        self._native_bindings.clear()
        self._help.clear()
