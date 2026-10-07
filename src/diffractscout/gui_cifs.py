"""Tk dialog for preparing traceable starting CIFs for selected phases."""

from __future__ import annotations

import os
import queue
import re
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .gui_theme import BG, BORDER, ERROR, MUTED, TEXT, configure_styles

try:  # Keep the core package importable when Tk is unavailable.
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - platform-dependent
    tk = None  # type: ignore[assignment]
    filedialog = messagebox = ttk = None  # type: ignore[assignment]


PHASES = ("alpha", "beta", "alpha-double-prime")
_PHASE_LABELS = {
    "alpha": {"zh": "α 相", "en": "α phase"},
    "beta": {"zh": "β 相", "en": "β phase"},
    "alpha-double-prime": {"zh": "α″ 马氏体", "en": "α″ martensite"},
}
_STATUS_LABELS = {
    "ready": {"zh": "可用起始 CIF", "en": "ready starting CIF"},
    "failed": {"zh": "该相准备失败", "en": "phase preparation failed"},
    "downloaded": {"zh": "数据库原型", "en": "database prototype"},
    "template": {"zh": "用户模板", "en": "user template"},
    "scaffold": {"zh": "随包原型", "en": "packaged prototype"},
    "prepared": {"zh": "已生成起始 CIF", "en": "starting CIF prepared"},
    "adapted": {"zh": "已生成起始 CIF", "en": "starting CIF prepared"},
    "missing": {"zh": "未生成", "en": "not generated"},
}


def prepare_kwargs_from_form(
    values: Mapping[str, Any], *, environment_key: str | None = None
) -> dict[str, Any]:
    """Validate a plain form snapshot and translate it to ``prepare_cifs`` kwargs."""

    composition = str(values.get("composition", "")).strip()
    output_text = str(values.get("output_dir", "")).strip()
    if not composition:
        raise ValueError("请输入合金成分或元素系统，例如 Ti-Al-V。" if values.get("lang") != "en" else "Enter a composition or element system, for example Ti-Al-V.")
    if not output_text:
        raise ValueError("请选择新建的输出文件夹。" if values.get("lang") != "en" else "Choose a new output folder.")

    basis = str(values.get("basis", "nominal"))
    nominal = str(values.get("nominal", "")).strip()
    percent_text = str(values.get("percent_text", "")).strip()
    if basis == "nominal":
        if not nominal:
            raise ValueError("请输入名义牌号，例如 TC4、Ti64 或 Ti-6Al-4V。" if values.get("lang") != "en" else "Enter a nominal grade, for example TC4, Ti64, or Ti-6Al-4V.")
        composition_kwargs = {"nominal": nominal}
    elif basis == "weight_percent":
        if not percent_text:
            raise ValueError("请输入完整质量百分比，例如 Ti=90,Al=6,V=4。" if values.get("lang") != "en" else "Enter the full weight percentages, for example Ti=90,Al=6,V=4.")
        composition_kwargs = {"weight_percent": percent_text}
    elif basis == "atomic_percent":
        if not percent_text:
            raise ValueError("请输入完整原子百分比，例如 Ti=86,Al=10,V=4。" if values.get("lang") != "en" else "Enter the full atomic percentages, for example Ti=86,Al=10,V=4.")
        composition_kwargs = {"atomic_percent": percent_text}
    else:
        raise ValueError("未知的成分基准。" if values.get("lang") != "en" else "Unknown composition basis.")

    phases = [phase for phase in PHASES if bool(values.get(f"phase_{phase}", False))]
    if not phases:
        raise ValueError("至少选择一个相。" if values.get("lang") != "en" else "Select at least one phase.")

    templates: dict[str, Path] = {}
    for phase in phases:
        raw_path = str(values.get(f"template_{phase}", "")).strip()
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if not path.is_file() or path.suffix.lower() != ".cif":
            label = _PHASE_LABELS[phase]["en" if values.get("lang") == "en" else "zh"]
            raise ValueError(f"{label}: 模板必须是存在的 CIF 文件。" if values.get("lang") != "en" else f"{label}: template must be an existing CIF file.")
        templates[phase] = path.resolve()

    parameter_text = str(values.get("parameter_file", "")).strip()
    parameter_file: Path | None = None
    if parameter_text:
        parameter_file = Path(parameter_text).expanduser()
        if not parameter_file.is_file():
            raise ValueError("参数文件不存在。" if values.get("lang") != "en" else "Parameter file does not exist.")
        parameter_file = parameter_file.resolve()

    offline = bool(values.get("offline", False))
    typed_key = str(values.get("api_key", "")).strip()
    api_key = None if offline else (typed_key or str(environment_key or "").strip() or None)
    return {
        "composition": composition,
        "output_dir": Path(output_text).expanduser().resolve(),
        **composition_kwargs,
        "phases": phases,
        "host": str(values.get("host", "")).strip(),
        "templates": templates,
        "parameter_file": parameter_file,
        "offline": offline,
        "api_key": api_key,
        "max_subsystems": 64,
    }


def _prepare_cifs(**kwargs: Any) -> Any:
    """Import the optional workflow only when a user starts the operation."""

    from .initial_cifs import prepare_cifs

    return prepare_cifs(**kwargs)


def _worker_run(
    kwargs: dict[str, Any], events: queue.Queue[tuple[str, object]]
) -> None:
    """Perform the API call without retaining or touching any Tk widget."""

    try:
        events.put(("done", _prepare_cifs(**kwargs)))
    except Exception as exc:  # Surface provider and validation failures in the dialog.
        events.put(("error", exc))


def _open_path(path: Path) -> None:
    """Open a report or output directory using the platform's registered app."""

    if os.name == "nt":  # pragma: no cover - Windows integration
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif path.is_dir():
        webbrowser.open(path.as_uri())
    else:
        webbrowser.open(path.as_uri())


if tk is not None:

    class InitialCifDialog(tk.Toplevel):
        """Independent window for building and loading initial CIF files."""

        def __init__(
            self,
            master: Any,
            *,
            language: str = "zh",
            on_load: Callable[[list[Path]], Any] | None = None,
            on_close: Callable[[], Any] | None = None,
        ) -> None:
            super().__init__(master)
            self.ui_font = configure_styles(self)
            self.configure(background=BG)
            self.lang = "en" if str(language).lower() == "en" else "zh"
            self._on_load = on_load
            self._on_close = on_close
            self._closed = False
            self._events: queue.Queue[tuple[str, object]] = queue.Queue()
            self._after_id: str | None = None
            self._running = False
            self._result: Any = None
            self._result_paths: list[Path] = []
            self._input_widgets: list[Any] = []
            self._template_vars: dict[str, Any] = {}

            self.title(self._t("title"))
            screen_height = self.winfo_screenheight()
            self._window_height_limit = max(1, min(770, screen_height - 100))
            self._window_width = min(920, max(680, self.winfo_screenwidth() - 60))
            initial_height = min(770, self._window_height_limit)
            self.geometry(f"{self._window_width}x{initial_height}")
            self.minsize(min(820, self._window_width), min(660, initial_height))
            self.protocol("WM_DELETE_WINDOW", self._close)
            self.transient(master)
            self._make_variables()
            self._build_widgets()
            self._set_status(self._t("ready"))

        def _t(self, key: str, **fmt: object) -> str:
            return _TEXT[self.lang][key].format(**fmt)

        def _make_variables(self) -> None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", "Ti-Al-V").strip("._-")
            self.composition_var = tk.StringVar(value="Ti-Al-V")
            self.basis_var = tk.StringVar(value="nominal")
            self.nominal_var = tk.StringVar(value="TC4")
            self.percent_var = tk.StringVar(value="")
            self.host_var = tk.StringVar(value="")
            self.output_var = tk.StringVar(
                value=str((Path.cwd() / f"initial_cifs_{safe_name}_{timestamp}").resolve())
            )
            self.parameter_var = tk.StringVar(value="")
            self.offline_var = tk.BooleanVar(value=not bool(os.environ.get("MP_API_KEY", "").strip()))
            self.api_key_var = tk.StringVar(value="")
            self.show_key_var = tk.BooleanVar(value=False)
            self.phase_vars = {phase: tk.BooleanVar(value=True) for phase in PHASES}
            self.basis_var.trace_add("write", lambda *_args: self._refresh_basis_label())
            self.show_key_var.trace_add("write", lambda *_args: self._refresh_key_visibility())
            self.offline_var.trace_add("write", lambda *_args: self._refresh_key_visibility())

        def _build_widgets(self) -> None:
            outer = ttk.Frame(self)
            outer.pack(fill="both", expand=True)
            footer = ttk.Frame(outer, padding=(14, 4, 14, 10))
            footer.pack(side="bottom", fill="x")
            scroll_host = ttk.Frame(outer)
            scroll_host.pack(fill="both", expand=True)
            self._scroll_canvas = tk.Canvas(
                scroll_host, highlightthickness=0, borderwidth=0, background=BG
            )
            self._scroll_canvas.pack(side="left", fill="both", expand=True)
            self._scrollbar = ttk.Scrollbar(
                scroll_host, orient="vertical", command=self._scroll_canvas.yview
            )
            self._scrollbar.pack(side="right", fill="y")
            self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)
            content = ttk.Frame(self._scroll_canvas, padding=14)
            self._scroll_content = content
            self._scroll_window = self._scroll_canvas.create_window(
                (0, 0), window=content, anchor="nw"
            )
            content.bind("<Configure>", self._on_scroll_content_configure, add="+")
            self._scroll_canvas.bind("<Configure>", self._on_scroll_canvas_configure, add="+")
            self.bind("<MouseWheel>", self._scroll_mousewheel, add="+")
            self.bind("<Button-4>", self._scroll_mousewheel, add="+")
            self.bind("<Button-5>", self._scroll_mousewheel, add="+")
            self.bind("<FocusIn>", self._reveal_focused_control, add="+")

            ttk.Label(content, text=self._t("heading"), style="PageTitle.TLabel").pack(anchor="w")
            ttk.Label(content, text=self._t("scroll_hint"), style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
            self.warning_label = ttk.Label(
                content,
                text=self._t("warning"),
                wraplength=max(400, self._window_width - 80),
                justify="left",
                style="Warning.TLabel",
            )
            self.warning_label.pack(anchor="w", fill="x", pady=(8, 14))

            form = ttk.LabelFrame(content, text=self._t("inputs"), padding=10)
            form.pack(fill="x")
            form.columnconfigure(1, weight=1)
            ttk.Label(form, text=self._t("composition")).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
            self.composition_entry = ttk.Entry(form, textvariable=self.composition_var)
            self.composition_entry.grid(row=0, column=1, sticky="ew", pady=4)
            self._input_widgets.append(self.composition_entry)
            ttk.Label(form, text=self._t("composition_hint"), style="Hint.TLabel").grid(
                row=1, column=1, sticky="w", pady=(0, 5)
            )

            basis_frame = ttk.LabelFrame(form, text=self._t("basis"), padding=(8, 4))
            basis_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(3, 7))
            basis_choices = ttk.Frame(basis_frame)
            basis_choices.grid(row=0, column=0, columnspan=3, sticky="w")
            for basis in ("nominal", "weight_percent", "atomic_percent"):
                radio = ttk.Radiobutton(
                    basis_choices,
                    text=self._t(f"basis_{basis}"),
                    value=basis,
                    variable=self.basis_var,
                )
                radio.pack(side="left", padx=(0, 20))
                self._input_widgets.append(radio)
            self.basis_value_label = ttk.Label(basis_frame, text="")
            self.basis_value_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
            self.nominal_entry = ttk.Entry(basis_frame, textvariable=self.nominal_var, width=28)
            self.nominal_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
            self.percent_entry = ttk.Entry(basis_frame, textvariable=self.percent_var, width=28)
            self.percent_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
            basis_frame.columnconfigure(1, weight=1)
            self._input_widgets.extend((self.nominal_entry, self.percent_entry))
            self.basis_hint = ttk.Label(basis_frame, text="", style="Hint.TLabel", wraplength=580,
                                        justify="left")
            self.basis_hint.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 3))

            ttk.Label(form, text=self._t("host")).grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
            self.host_entry = ttk.Entry(form, textvariable=self.host_var)
            self.host_entry.grid(row=3, column=1, sticky="ew", pady=4)
            self._input_widgets.append(self.host_entry)
            ttk.Label(form, text=self._t("host_hint"), style="Hint.TLabel").grid(
                row=4, column=1, sticky="w", pady=(0, 4)
            )

            ttk.Label(form, text=self._t("output")).grid(row=5, column=0, sticky="w", padx=(0, 8), pady=4)
            output_row = ttk.Frame(form)
            output_row.grid(row=5, column=1, sticky="ew", pady=4)
            output_row.columnconfigure(0, weight=1)
            self.output_entry = ttk.Entry(output_row, textvariable=self.output_var)
            self.output_entry.grid(row=0, column=0, sticky="ew")
            output_button = ttk.Button(output_row, text=self._t("browse_parent"), command=self._browse_output_parent)
            output_button.grid(row=0, column=1, padx=(6, 0))
            self._input_widgets.extend((self.output_entry, output_button))

            phases_frame = ttk.LabelFrame(form, text=self._t("phases"), padding=(8, 4))
            phases_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(7, 0))
            for column, phase in enumerate(PHASES):
                checkbox = ttk.Checkbutton(
                    phases_frame,
                    text=_PHASE_LABELS[phase][self.lang],
                    variable=self.phase_vars[phase],
                )
                checkbox.grid(row=0, column=column, sticky="w", padx=(0, 16))
                self._input_widgets.append(checkbox)

            self.advanced_button = ttk.Button(
                content, text=self._t("advanced_show"), command=self._toggle_advanced,
                style="Disclosure.TButton",
            )
            self.advanced_button.pack(fill="x", pady=(10, 6))
            self.advanced_frame = ttk.LabelFrame(content, text=self._t("advanced"), padding=9)
            self.advanced_frame.columnconfigure(1, weight=1)
            self.advanced_visible = False
            self.advanced_frame.pack_forget()
            self._build_advanced()

            progress_row = ttk.Frame(footer)
            progress_row.pack(fill="x", pady=(6, 3))
            self.status_var = tk.StringVar(value="")
            self.status_label = ttk.Label(progress_row, textvariable=self.status_var)
            self.status_label.pack(side="left", fill="x", expand=True, anchor="w")
            self.progress = ttk.Progressbar(progress_row, mode="indeterminate", length=120)

            results = ttk.LabelFrame(content, text=self._t("results"), padding=7)
            self.results_frame = results
            results.pack(fill="both", expand=True, pady=(4, 5))
            results.columnconfigure(0, weight=1)
            results.rowconfigure(0, weight=1)
            self.tree = ttk.Treeview(
                results,
                columns=("phase", "status", "cif"),
                show="headings",
                height=4,
                selectmode="browse",
            )
            for key, width in (("phase", 145), ("status", 160), ("cif", 270)):
                self.tree.heading(key, text=self._t(f"column_{key}"))
                self.tree.column(key, width=width, anchor="w")
            self.tree.grid(row=0, column=0, sticky="nsew")
            result_scroll = ttk.Scrollbar(results, orient="vertical", command=self.tree.yview)
            result_scroll.grid(row=0, column=1, sticky="ns")
            self.tree.configure(yscrollcommand=result_scroll.set)
            self.tree.bind("<<TreeviewSelect>>", self._show_record_details)
            detail_frame = ttk.Frame(results, style="Card.TFrame")
            detail_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            self.details = tk.Text(detail_frame, height=4, wrap="word", state="disabled",
                                   relief="flat", background=BG, foreground=TEXT,
                                   font=(self.ui_font, 9), padx=8, pady=6,
                                   highlightthickness=1, highlightbackground=BORDER,
                                   highlightcolor=MUTED)
            detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.details.yview)
            self.details.configure(yscrollcommand=detail_scroll.set)
            detail_scroll.pack(side="right", fill="y")
            self.details.pack(fill="x", expand=True)

            actions = ttk.Frame(footer)
            actions.pack(fill="x", pady=(4, 0))
            self.run_button = ttk.Button(actions, text=self._t("run"), command=self._start, style="Primary.TButton")
            self.run_button.pack(side="left")
            self.load_button = ttk.Button(actions, text=self._t("load"), command=self._load_results, state="disabled")
            self.load_button.pack(side="left", padx=(6, 0))
            self.report_button = ttk.Button(actions, text=self._t("open_report"), command=self._open_report, state="disabled")
            self.report_button.pack(side="left", padx=(6, 0))
            self.folder_button = ttk.Button(actions, text=self._t("open_folder"), command=self._open_folder, state="disabled")
            self.folder_button.pack(side="left", padx=(6, 0))
            ttk.Button(actions, text=self._t("close"), command=self._close).pack(side="right")
            for group in (form, self.advanced_frame, results):
                self._style_card_children(group)
            self.bind("<Control-Return>", lambda _event: self._start() if not self._running else None)
            self._refresh_basis_label()
            self._refresh_key_visibility()

        def _style_card_children(self, widget: Any) -> None:
            for child in widget.winfo_children():
                if isinstance(child, ttk.Frame):
                    child.configure(style="Card.TFrame")
                elif isinstance(child, ttk.Label) and not str(child.cget("style")):
                    child.configure(style="Card.TLabel")
                self._style_card_children(child)

        def _on_scroll_content_configure(self, _event: Any = None) -> None:
            bounds = self._scroll_canvas.bbox("all")
            if bounds is not None:
                self._scroll_canvas.configure(scrollregion=bounds)

        def _on_scroll_canvas_configure(self, event: Any) -> None:
            self._scroll_canvas.itemconfigure(self._scroll_window, width=event.width)
            if hasattr(self, "warning_label"):
                self.warning_label.configure(wraplength=max(200, event.width - 60))
            if hasattr(self, "basis_hint"):
                self.basis_hint.configure(wraplength=max(200, event.width - 90))

        def _reveal_focused_control(self, event: Any) -> None:
            widget = event.widget
            ancestor = widget
            while ancestor is not None and ancestor is not self._scroll_content:
                ancestor = getattr(ancestor, "master", None)
            if ancestor is None:
                return
            bounds = self._scroll_canvas.bbox("all")
            if not bounds:
                return
            total = max(1, bounds[3] - bounds[1])
            height = self._scroll_canvas.winfo_height()
            top = widget.winfo_rooty() - self._scroll_content.winfo_rooty()
            bottom = top + widget.winfo_height()
            offset = self._scroll_canvas.canvasy(0)
            if top < offset:
                target = top
            elif bottom > offset + height:
                target = bottom - height
            else:
                return
            self._scroll_canvas.yview_moveto(max(0, min(target, total - height)) / total)

        def _scroll_mousewheel(self, event: Any) -> str | None:
            widget = event.widget
            if widget.winfo_class() in {"Text", "TCombobox", "Listbox", "Spinbox", "TSpinbox", "Treeview"}:
                return None  # Keep native controls' scrolling separate from the form.
            inside_content = widget is self._scroll_canvas
            while widget is not None and not inside_content:
                inside_content = widget is self._scroll_content
                widget = getattr(widget, "master", None)
            if not inside_content:
                return None
            if getattr(event, "num", None) == 4:
                amount = -1
            elif getattr(event, "num", None) == 5:
                amount = 1
            else:
                delta = int(getattr(event, "delta", 0))
                amount = -1 if delta > 0 else 1 if delta < 0 else 0
            if amount:
                self._scroll_canvas.yview_scroll(amount, "units")
            return "break"

        def _build_advanced(self) -> None:
            ttk.Label(self.advanced_frame, text=self._t("parameter_file")).grid(
                row=0, column=0, sticky="w", padx=(0, 8), pady=3
            )
            self.parameter_entry = ttk.Entry(self.advanced_frame, textvariable=self.parameter_var)
            self.parameter_entry.grid(row=0, column=1, sticky="ew", pady=3)
            parameter_button = ttk.Button(
                self.advanced_frame, text=self._t("browse"), command=self._browse_parameter
            )
            parameter_button.grid(row=0, column=2, padx=(6, 0))
            self._input_widgets.extend((self.parameter_entry, parameter_button))

            self.offline_check = ttk.Checkbutton(
                self.advanced_frame,
                text=self._t("offline"),
                variable=self.offline_var,
            )
            self.offline_check.grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 2))
            self._input_widgets.append(self.offline_check)
            ttk.Label(self.advanced_frame, text=self._t("api_key")).grid(
                row=2, column=0, sticky="w", padx=(0, 8), pady=3
            )
            self.api_key_entry = ttk.Entry(
                self.advanced_frame, textvariable=self.api_key_var, show="•"
            )
            self.api_key_entry.grid(row=2, column=1, sticky="ew", pady=3)
            self.show_key_check = ttk.Checkbutton(
                self.advanced_frame,
                text=self._t("show_key"),
                variable=self.show_key_var,
            )
            self.show_key_check.grid(row=2, column=2, sticky="w", padx=(6, 0))
            ttk.Label(self.advanced_frame, text=self._t("key_hint"), style="Hint.TLabel").grid(
                row=3, column=1, columnspan=2, sticky="w", pady=(0, 4)
            )
            self._input_widgets.extend((self.api_key_entry, self.show_key_check))

            for row, phase in enumerate(PHASES, start=4):
                ttk.Label(
                    self.advanced_frame,
                    text=self._t("template", phase=_PHASE_LABELS[phase][self.lang]),
                ).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
                var = tk.StringVar(value="")
                self._template_vars[phase] = var
                entry = ttk.Entry(self.advanced_frame, textvariable=var)
                entry.grid(row=row, column=1, sticky="ew", pady=3)
                button = ttk.Button(
                    self.advanced_frame,
                    text=self._t("browse"),
                    command=lambda name=phase: self._browse_template(name),
                )
                button.grid(row=row, column=2, padx=(6, 0))
                self._input_widgets.extend((entry, button))
            ttk.Label(
                self.advanced_frame,
                text=self._t("parameter_hint"),
                style="Hint.TLabel",
                wraplength=760,
                justify="left",
            ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(5, 0))

        def _refresh_basis_label(self) -> None:
            basis = self.basis_var.get()
            is_nominal = basis == "nominal"
            self.basis_value_label.configure(
                text=self._t("nominal_value") if is_nominal else self._t("percent_value")
            )
            if is_nominal:
                self.nominal_entry.grid()
                self.percent_entry.grid_remove()
                self.basis_hint.configure(text=self._t("nominal_hint"))
            else:
                self.nominal_entry.grid_remove()
                self.percent_entry.grid()
                self.basis_hint.configure(
                    text=self._t("weight_hint" if basis == "weight_percent" else "atomic_hint")
                )

        def _refresh_key_visibility(self) -> None:
            self.api_key_entry.configure(
                show="" if self.show_key_var.get() else "•",
                state="disabled" if self.offline_var.get() else "normal",
            )
            self.show_key_check.configure(state="disabled" if self.offline_var.get() else "normal")

        def _toggle_advanced(self) -> None:
            self.advanced_visible = not self.advanced_visible
            if self.advanced_visible:
                self.advanced_frame.pack(fill="x", pady=(0, 3), after=self.advanced_button)
                self.advanced_button.configure(text=self._t("advanced_hide"))
            else:
                self.advanced_frame.pack_forget()
                self.advanced_button.configure(text=self._t("advanced_show"))
            self.update_idletasks()
            self._on_scroll_content_configure()

        def _browse_output_parent(self) -> None:
            current = Path(self.output_var.get()).expanduser()
            parent = filedialog.askdirectory(
                parent=self,
                title=self._t("choose_parent"),
                initialdir=str(current.parent if current.parent.is_dir() else Path.cwd()),
            )
            if parent:
                suffix = current.name or "initial_cifs"
                self.output_var.set(str((Path(parent) / suffix).resolve()))

        def _browse_parameter(self) -> None:
            selected = filedialog.askopenfilename(
                parent=self,
                title=self._t("choose_parameter"),
                filetypes=(("JSON", "*.json"), ("All files", "*.*")),
            )
            if selected:
                self.parameter_var.set(selected)

        def _browse_template(self, phase: str) -> None:
            selected = filedialog.askopenfilename(
                parent=self,
                title=self._t("choose_template", phase=_PHASE_LABELS[phase][self.lang]),
                filetypes=(("CIF", "*.cif *.CIF"), ("All files", "*.*")),
            )
            if selected:
                self._template_vars[phase].set(selected)

        def _form_values(self) -> dict[str, Any]:
            values: dict[str, Any] = {
                "lang": self.lang,
                "composition": self.composition_var.get(),
                "basis": self.basis_var.get(),
                "nominal": self.nominal_var.get(),
                "percent_text": self.percent_var.get(),
                "host": self.host_var.get(),
                "output_dir": self.output_var.get(),
                "parameter_file": self.parameter_var.get(),
                "offline": self.offline_var.get(),
                "api_key": self.api_key_var.get(),
            }
            values.update({f"phase_{phase}": variable.get() for phase, variable in self.phase_vars.items()})
            values.update(
                {f"template_{phase}": variable.get() for phase, variable in self._template_vars.items()}
            )
            return values

        def _start(self) -> None:
            if self._running:
                return
            try:
                kwargs = prepare_kwargs_from_form(
                    self._form_values(), environment_key=os.environ.get("MP_API_KEY", "")
                )
                output_dir = kwargs["output_dir"]
                if output_dir.exists():
                    raise ValueError(
                        self._t("output_exists", path=output_dir)
                    )
            except (OSError, ValueError) as exc:
                self._set_status(str(exc), error=True)
                messagebox.showerror(self._t("error_title"), str(exc), parent=self)
                return

            self._result = None
            self._result_paths = []
            self.tree.delete(*self.tree.get_children())
            self._write_details("")
            self.load_button.configure(state="disabled")
            self.report_button.configure(state="disabled")
            self.folder_button.configure(state="disabled")
            self._running = True
            self.run_button.configure(state="disabled")
            self._set_form_enabled(False)
            self.progress.pack(side="right")
            self.progress.start(12)
            self._set_status(self._t("running"))
            thread = threading.Thread(
                target=_worker_run, args=(kwargs, self._events), daemon=True, name="initial-cif-worker"
            )
            thread.start()
            self._schedule_poll()

        def _schedule_poll(self) -> None:
            if not self._closed:
                try:
                    self._after_id = self.after(100, self._poll_events)
                except tk.TclError:
                    self._after_id = None

        def _poll_events(self) -> None:
            self._after_id = None
            try:
                kind, payload = self._events.get_nowait()
            except queue.Empty:
                if self._running:
                    self._schedule_poll()
                return
            self._running = False
            self.progress.stop()
            self.progress.pack_forget()
            self.run_button.configure(state="normal")
            self._set_form_enabled(True)
            if kind == "done":
                self._show_result(payload)
            else:
                error = str(payload)
                self._set_status(self._t("failed"), error=True)
                self._write_details(error)
                self.run_button.focus_set()

        def _show_result(self, result: Any) -> None:
            self._result = result
            self._result_paths = [
                Path(record.cif_path).resolve()
                for record in getattr(result, "records", ())
                if getattr(record, "cif_path", None) is not None
                and Path(record.cif_path).is_file()
            ]
            records = tuple(getattr(result, "records", ()))
            for index, record in enumerate(records):
                phase = str(getattr(record, "phase", ""))
                status = str(getattr(record, "status", ""))
                path = getattr(record, "cif_path", None)
                phase_label = _PHASE_LABELS.get(phase, {}).get(self.lang, phase)
                status_label = _STATUS_LABELS.get(status, {}).get(self.lang, status)
                self.tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(phase_label, status_label, Path(path).name if path else "—"),
                    tags=("even" if index % 2 == 0 else "odd", "failed" if not path else "ready"),
                )
            self.tree.tag_configure("odd", background=BG)
            self.tree.tag_configure("failed", foreground=ERROR)
            report_path = getattr(result, "report_path", None)
            output_dir = getattr(result, "output_dir", None)
            exit_code = int(getattr(result, "exit_code", 2))
            if exit_code == 0:
                self._set_status(self._t("complete", count=len(self._result_paths)))
            elif exit_code == 3:
                self._set_status(self._t("partial", count=len(self._result_paths)))
            else:
                self._set_status(self._t("empty"), error=True)
            self.load_button.configure(state="normal" if self._result_paths else "disabled")
            self.report_button.configure(state="normal" if report_path else "disabled")
            self.folder_button.configure(state="normal" if output_dir else "disabled")
            first = next(iter(self.tree.get_children()), None)
            if first is not None:
                self.tree.selection_set(first)
                self.tree.focus(first)
                self._show_record_details()
            elif report_path:
                self._write_details(str(report_path))
            self.update_idletasks()
            bounds = self._scroll_canvas.bbox("all")
            if bounds:
                top = self.results_frame.winfo_y()
                total = max(1, bounds[3] - bounds[1])
                self._scroll_canvas.yview_moveto(max(0, top - 12) / total)

        def _show_record_details(self, _event: Any = None) -> None:
            selection = self.tree.selection()
            if not selection or self._result is None:
                return
            try:
                record = self._result.records[int(selection[0])]
            except (AttributeError, IndexError, TypeError, ValueError):
                return
            detail = str(getattr(record, "note", "") or "")
            path = getattr(record, "cif_path", None)
            if path:
                detail = f"{path}\n{detail}" if detail else str(path)
            self._write_details(detail or self._t("no_details"))

        def _write_details(self, text: str) -> None:
            self.details.configure(state="normal")
            self.details.delete("1.0", "end")
            self.details.insert("1.0", text)
            self.details.configure(state="disabled")

        def _load_results(self) -> None:
            if self._on_load is None or not self._result_paths:
                return
            # This button runs in Tk's event loop; the main-window callback is
            # therefore never invoked from the worker thread.
            self._on_load(list(self._result_paths))
            self._set_status(self._t("loaded", count=len(self._result_paths)))

        def _open_report(self) -> None:
            path = getattr(self._result, "report_path", None)
            self._open_result_path(path)

        def _open_folder(self) -> None:
            path = getattr(self._result, "output_dir", None)
            self._open_result_path(path)

        def _open_result_path(self, raw_path: Any) -> None:
            if raw_path is None:
                return
            path = Path(raw_path)
            if not path.exists():
                self._set_status(self._t("path_missing", path=path), error=True)
                return
            try:
                _open_path(path)
            except OSError as exc:
                self._set_status(str(exc), error=True)

        def _set_status(self, text: str, *, error: bool = False) -> None:
            self.status_var.set(text)
            self.status_label.configure(foreground="#B42318" if error else "#203040")

        def _set_form_enabled(self, enabled: bool) -> None:
            state = "normal" if enabled else "disabled"
            for widget in self._input_widgets:
                try:
                    widget.configure(state=state)
                except tk.TclError:
                    continue
            if enabled:
                self._refresh_key_visibility()

        def _close(self) -> None:
            if self._closed:
                return
            self._closed = True
            if self._after_id is not None:
                try:
                    self.after_cancel(self._after_id)
                except tk.TclError:
                    pass
                self._after_id = None
            # The worker only owns a queue and an immutable request snapshot.
            # It may finish writing output after this window is closed, without
            # calling after(), configure(), or any other Tk method.
            if self._on_close is not None:
                self._on_close()
            self.destroy()

else:

    class InitialCifDialog:  # pragma: no cover - import guard
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("Tkinter is unavailable in this Python installation.")


_TEXT = {
    "zh": {
        "title": "初始 CIF 准备",
        "heading": "为选定相准备可追溯的起始 CIF",
        "scroll_hint": "表单和逐相结果可滚动查看；状态与主操作固定在窗口底部。",
        "warning": "生成文件用于后续结构分析或精修起步。原型晶格和占位是初始假设；它们不代表实测结构、相鉴定、平衡相成分或热分析结果。",
        "inputs": "合金与输出",
        "composition": "成分 / 元素系统",
        "composition_hint": "填写元素系统（例如 Ti-Al-V）；牌号或成分数值在下方按基准填写。",
        "basis": "成分基准",
        "basis_nominal": "名义牌号",
        "basis_weight_percent": "质量百分比",
        "basis_atomic_percent": "原子百分比",
        "nominal_value": "牌号",
        "percent_value": "元素含量",
        "nominal_hint": "TC4、Ti64 或 Ti-6Al-4V 按常用名义成分 6 wt% Al、4 wt% V 处理。",
        "weight_hint": "完整示例 Ti=90,Al=6,V=4，合计 100 wt%。",
        "atomic_hint": "完整示例 Ti=86,Al=10,V=4，合计 100 at%。",
        "host": "基体元素（可选）",
        "host_hint": "留空时按占比最高的元素选择；若最高占比并列或需指定其他基体，请手动填写。",
        "output": "新建输出文件夹",
        "browse_parent": "选择父文件夹…",
        "phases": "目标相（可多选）",
        "advanced_show": "高级选项 ▸",
        "advanced_hide": "高级选项 ▾",
        "advanced": "参数来源与模板",
        "parameter_file": "文献参数 JSON",
        "parameter_hint": "参数 JSON 由用户或代理按文献填写；程序不会搜索论文。无参数时仍可生成清楚标记的起始模型。相模板只用于对应已勾选的相。",
        "offline": "离线：只用随包原型与本地模板，不访问 Materials Project",
        "api_key": "Materials Project API key",
        "show_key": "显示",
        "key_hint": "留空时读取进程环境变量 MP_API_KEY；密钥不会保存到文件。",
        "template": "{phase} 模板 CIF（可选）",
        "browse": "浏览…",
        "results": "逐相结果",
        "column_phase": "目标相",
        "column_status": "来源 / 状态",
        "column_cif": "生成的 CIF",
        "run": "准备 CIF",
        "load": "将结果载入分析",
        "open_report": "查看报告",
        "open_folder": "打开输出文件夹",
        "close": "关闭",
        "ready": "填写参数后开始。",
        "running": "正在准备起始 CIF…完成后会逐相显示结果。",
        "complete": "完成：已准备 {count} 个 CIF。",
        "partial": "部分完成：已准备 {count} 个 CIF；查看各相状态和报告。",
        "empty": "没有可用 CIF；请查看逐相状态和报告。",
        "failed": "准备失败；请查看下方错误信息。",
        "loaded": "已将 {count} 个 CIF 加入主窗口的本地分析列表。",
        "no_details": "该相没有附加说明。",
        "path_missing": "结果路径不存在：{path}",
        "output_exists": "输出目标已存在。为避免混入旧结果，请选择一个新的文件夹：\n{path}",
        "error_title": "无法开始",
        "choose_parent": "选择新输出文件夹的父目录",
        "choose_parameter": "选择文献参数 JSON",
        "choose_template": "选择 {phase} 模板 CIF",
    },
    "en": {
        "title": "Initial CIF preparation",
        "heading": "Prepare traceable starting CIFs for selected phases",
        "scroll_hint": "The form and phase results scroll; status and main actions stay at the bottom.",
        "warning": "These files are starting points for later structural analysis or refinement. Prototype lattices and occupancies are initial assumptions; they do not represent measured structures, phase identification, equilibrium phase chemistry, or thermal analysis.",
        "inputs": "Alloy and output",
        "composition": "Composition / element system",
        "composition_hint": "Enter the element system (for example Ti-Al-V); enter the grade or amounts below using the selected basis.",
        "basis": "Composition basis",
        "basis_nominal": "Nominal grade",
        "basis_weight_percent": "Weight percent",
        "basis_atomic_percent": "Atomic percent",
        "nominal_value": "Grade",
        "percent_value": "Element amounts",
        "nominal_hint": "TC4, Ti64, and Ti-6Al-4V use the common nominal composition 6 wt% Al and 4 wt% V.",
        "weight_hint": "Complete example: Ti=90,Al=6,V=4; total = 100 wt%.",
        "atomic_hint": "Complete example: Ti=86,Al=10,V=4; total = 100 at%.",
        "host": "Host element (optional)",
        "host_hint": "When blank, the workflow chooses the element with the largest fraction; specify a host for ties or a different parent lattice.",
        "output": "New output folder",
        "browse_parent": "Choose parent…",
        "phases": "Target phases (select any)",
        "advanced_show": "Advanced options ▸",
        "advanced_hide": "Advanced options ▾",
        "advanced": "Parameter sources and templates",
        "parameter_file": "Literature parameter JSON",
        "parameter_hint": "The user or agent supplies literature-backed values in JSON; the program does not search papers. Starting models remain clearly marked when no parameters are supplied. Templates apply only to checked phases.",
        "offline": "Offline: use packaged prototypes and local templates; do not query Materials Project",
        "api_key": "Materials Project API key",
        "show_key": "Show",
        "key_hint": "When blank, read MP_API_KEY from the process environment. The key is never saved to a file.",
        "template": "{phase} template CIF (optional)",
        "browse": "Browse…",
        "results": "Per-phase results",
        "column_phase": "Target phase",
        "column_status": "Source / status",
        "column_cif": "Output CIF",
        "run": "Prepare CIFs",
        "load": "Load results for analysis",
        "open_report": "View report",
        "open_folder": "Open output folder",
        "close": "Close",
        "ready": "Enter the inputs and start.",
        "running": "Preparing starting CIFs… per-phase results will appear when complete.",
        "complete": "Complete: prepared {count} CIF files.",
        "partial": "Partial: prepared {count} CIF files; inspect phase status and report.",
        "empty": "No CIF files are available; inspect phase status and report.",
        "failed": "Preparation failed; see the error details below.",
        "loaded": "Added {count} CIF files to the main window's local analysis list.",
        "no_details": "No additional details for this phase.",
        "path_missing": "Result path does not exist: {path}",
        "output_exists": "The output target already exists. Choose a new folder to keep results unambiguous:\n{path}",
        "error_title": "Could not start",
        "choose_parent": "Choose the parent folder for a new output folder",
        "choose_parameter": "Choose literature parameter JSON",
        "choose_template": "Choose {phase} template CIF",
    },
}
