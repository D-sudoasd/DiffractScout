"""Small native widgets that retain canonical settings behind translated labels."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Mapping


class TranslatedCombobox(ttk.Combobox):
    """Display translated choices without putting UI labels into scientific settings."""

    def __init__(self, master: object, *, variable: tk.StringVar,
                 value_keys: Mapping[str, str], translate: Callable[..., str], **kwargs: object):
        self.canonical_variable = variable
        self.value_keys = dict(value_keys)
        self.translate = translate
        self.display_variable = tk.StringVar(master=master)
        super().__init__(master, textvariable=self.display_variable, state="readonly", **kwargs)
        self._trace_id = variable.trace_add("write", self._sync_value)
        self.bind("<<ComboboxSelected>>", self._select_value, add="+")
        self.refresh_language()

    def _sync_value(self, *_args: object) -> None:
        value = self.canonical_variable.get()
        self.display_variable.set(self.translate(self.value_keys[value])
                                  if value in self.value_keys else value)

    def _select_value(self, _event: object = None) -> None:
        selected = self.display_variable.get()
        for value, key in self.value_keys.items():
            if self.translate(key) == selected:
                self.canonical_variable.set(value)
                break

    def refresh_language(self) -> None:
        self.configure(values=tuple(self.translate(key) for key in self.value_keys.values()))
        self._sync_value()

    def destroy(self) -> None:
        self.canonical_variable.trace_remove("write", self._trace_id)
        super().destroy()
