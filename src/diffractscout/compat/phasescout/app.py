"""Tkinter GUI for downloading CIF files from Materials Project."""

from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk

from .mp_client import CifNameMeta, MaterialsProjectService, MaterialSummary, parse_mpids


from ..paths import user_data_dir

APP_DIR = user_data_dir()
CONFIG_DIR = APP_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "settings.json"
DEFAULT_DOWNLOAD_DIR = APP_DIR / "downloads"


class PhaseScoutApp:
    """Desktop GUI application (PhaseScout)."""

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("PhaseScout")
        self.root.geometry("1060x760")
        self.root.minsize(900, 640)

        self.api_key_var = StringVar(value=self._initial_api_key())
        self.output_dir_var = StringVar(value=str(DEFAULT_DOWNLOAD_DIR))
        self.chemsys_var = StringVar()
        self.max_results_var = IntVar(value=100)
        self.conventional_cell_var = BooleanVar(value=True)
        self.include_elasticity_var = BooleanVar(value=True)
        self.status_var = StringVar(value="Ready")

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.search_results: list[MaterialSummary] = []
        self.busy = False
        self.action_buttons: list[ttk.Button] = []

        self._build_ui()
        self._poll_events()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 14, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")

        header = ttk.Frame(self.root, padding=(14, 12, 14, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="PhaseScout", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="侦察可能相 · 从 Materials Project 收获 CIF（DFT 结构；实验对比前请确认相、晶胞与来源）。",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        settings = ttk.LabelFrame(self.root, text="API 与输出设置", padding=10)
        settings.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 10))
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="API key").grid(row=0, column=0, sticky="w", padx=(0, 8))
        api_entry = ttk.Entry(settings, textvariable=self.api_key_var, show="*")
        api_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        save_button = ttk.Button(settings, text="保存到本机", command=self._save_api_key)
        save_button.grid(row=0, column=2, padx=(0, 8))
        clear_button = ttk.Button(settings, text="清除保存", command=self._clear_saved_api_key)
        clear_button.grid(row=0, column=3)

        ttk.Label(settings, text="输出目录").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(settings, textvariable=self.output_dir_var).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(8, 0))
        ttk.Button(settings, text="选择目录", command=self._choose_output_dir).grid(row=1, column=2, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(settings, text="导出标准常规晶胞", variable=self.conventional_cell_var).grid(
            row=1,
            column=3,
            sticky="w",
            pady=(8, 0),
        )
        ttk.Checkbutton(settings, text="同步查询 Cij 弹性常数", variable=self.include_elasticity_var).grid(
            row=2,
            column=1,
            sticky="w",
            pady=(8, 0),
        )

        main = ttk.Notebook(self.root)
        main.grid(row=2, column=0, sticky="nsew", padx=14)

        mpid_tab = ttk.Frame(main, padding=12)
        mpid_tab.columnconfigure(0, weight=1)
        mpid_tab.rowconfigure(1, weight=1)
        main.add(mpid_tab, text="按 MP-ID 下载")

        ttk.Label(mpid_tab, text="输入 MP-ID，支持逗号、空格或换行分隔，例如：mp-23, mp-149").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.mpid_text = Text(mpid_tab, height=10, wrap="word")
        self.mpid_text.grid(row=1, column=0, sticky="nsew", pady=(8, 10))
        self.mpid_text.insert("1.0", "mp-23")

        mpid_actions = ttk.Frame(mpid_tab)
        mpid_actions.grid(row=2, column=0, sticky="ew")
        download_mpid_button = ttk.Button(mpid_actions, text="下载这些 CIF", command=self._download_mpids)
        download_mpid_button.pack(side="left")
        self.action_buttons.append(download_mpid_button)

        search_tab = ttk.Frame(main, padding=12)
        search_tab.columnconfigure(0, weight=1)
        search_tab.rowconfigure(1, weight=1)
        main.add(search_tab, text="按化学体系搜索")

        search_controls = ttk.Frame(search_tab)
        search_controls.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        search_controls.columnconfigure(1, weight=1)
        ttk.Label(search_controls, text="化学体系").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(search_controls, textvariable=self.chemsys_var).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(search_controls, text="最多结果").grid(row=0, column=2, padx=(0, 6))
        ttk.Spinbox(search_controls, from_=1, to=500, textvariable=self.max_results_var, width=7).grid(
            row=0,
            column=3,
            padx=(0, 8),
        )
        search_button = ttk.Button(search_controls, text="搜索", command=self._search_chemsys)
        search_button.grid(row=0, column=4)
        self.action_buttons.append(search_button)

        columns = ("material_id", "formula", "hull", "band_gap", "crystal_system", "spacegroup")
        self.results_tree = ttk.Treeview(search_tab, columns=columns, show="headings", selectmode="extended")
        headings = {
            "material_id": "Material ID",
            "formula": "Formula",
            "hull": "E above hull (eV/atom)",
            "band_gap": "Band gap (eV)",
            "crystal_system": "Crystal system",
            "spacegroup": "Space group",
        }
        widths = {
            "material_id": 110,
            "formula": 120,
            "hull": 160,
            "band_gap": 120,
            "crystal_system": 130,
            "spacegroup": 180,
        }
        for column in columns:
            self.results_tree.heading(column, text=headings[column])
            self.results_tree.column(column, width=widths[column], anchor="w")

        y_scroll = ttk.Scrollbar(search_tab, orient="vertical", command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=y_scroll.set)
        self.results_tree.grid(row=1, column=0, sticky="nsew")
        y_scroll.grid(row=1, column=1, sticky="ns")

        search_actions = ttk.Frame(search_tab)
        search_actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        selected_button = ttk.Button(search_actions, text="下载选中 CIF", command=self._download_selected_results)
        selected_button.pack(side="left", padx=(0, 8))
        all_button = ttk.Button(search_actions, text="下载全部搜索结果", command=self._download_all_results)
        all_button.pack(side="left")
        self.action_buttons.extend([selected_button, all_button])

        log_frame = ttk.LabelFrame(self.root, text="日志", padding=8)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=14, pady=12)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = Text(log_frame, height=8, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.grid(row=0, column=1, sticky="ns")

        status = ttk.Frame(self.root, padding=(14, 0, 14, 10))
        status.grid(row=4, column=0, sticky="ew")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")

        self._log("启动完成。API key 优先读取环境变量 MP_API_KEY，其次读取本机 config/settings.json。")

    def _initial_api_key(self) -> str:
        env_key = os.environ.get("MP_API_KEY", "").strip()
        if env_key:
            return env_key
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return str(data.get("api_key", "")).strip()
        except FileNotFoundError:
            return ""
        except Exception:
            return ""

    def _save_api_key(self) -> None:
        key = self.api_key_var.get().strip()
        if not key:
            messagebox.showwarning("缺少 API key", "请先输入 API key。")
            return
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({"api_key": key}, indent=2), encoding="utf-8")
        self._log("API key 已保存到本机 config/settings.json。不要把该文件公开分享。")

    def _clear_saved_api_key(self) -> None:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
        self._log("已清除本机保存的 API key；环境变量 MP_API_KEY 不受影响。")

    def _choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(APP_DIR))
        if selected:
            self.output_dir_var.set(selected)

    def _api_key(self) -> str:
        key = self.api_key_var.get().strip()
        if not key:
            raise ValueError("缺少 API key。请在上方输入，或设置环境变量 MP_API_KEY。")
        return key

    def _output_dir(self) -> Path:
        path = Path(self.output_dir_var.get().strip() or DEFAULT_DOWNLOAD_DIR)
        return path.expanduser().resolve()

    def _run_worker(self, label: str, target) -> None:
        if self.busy:
            messagebox.showinfo("正在运行", "当前任务还没有结束，请等待。")
            return
        self._set_busy(True, label)

        def worker() -> None:
            try:
                target()
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("done", label))

        threading.Thread(target=worker, daemon=True).start()

    def _download_mpids(self) -> None:
        text = self.mpid_text.get("1.0", "end")
        mpids, invalid = parse_mpids(text)
        if invalid:
            messagebox.showwarning("MP-ID 格式错误", "以下条目不是有效 MP-ID：\n" + "\n".join(invalid[:20]))
            return
        if not mpids:
            messagebox.showwarning("缺少 MP-ID", "请至少输入一个 MP-ID，例如 mp-23。")
            return

        try:
            api_key = self._api_key()
            output_dir = self._output_dir()
            conventional_cell = self.conventional_cell_var.get()
            include_elasticity = self.include_elasticity_var.get()
        except Exception as exc:
            messagebox.showerror("设置错误", str(exc))
            return

        def task() -> None:
            suffix = "，并同步查询 Cij 弹性常数" if include_elasticity else ""
            self.events.put(("log", f"开始下载 {len(mpids)} 个 CIF{suffix}。"))
            service = MaterialsProjectService(api_key)
            results = service.download_cifs(
                mpids,
                output_dir,
                conventional_cell,
                include_elasticity=include_elasticity,
                name_meta=self._name_meta_for_mpids(mpids),
            )
            self.events.put(("download_results", results))

        self._run_worker("下载 MP-ID CIF", task)

    def _search_chemsys(self) -> None:
        chemsys = self.chemsys_var.get().strip()
        if not chemsys:
            messagebox.showwarning("缺少化学体系", "请输入化学体系，例如 Ni-Al。")
            return

        try:
            max_results = int(self.max_results_var.get())
        except Exception:
            max_results = 100
            self.max_results_var.set(max_results)

        try:
            api_key = self._api_key()
        except Exception as exc:
            messagebox.showerror("设置错误", str(exc))
            return

        def task() -> None:
            self.events.put(("log", f"开始搜索化学体系 {chemsys}，最多 {max_results} 条。"))
            service = MaterialsProjectService(api_key)
            results = service.search_chemsys(chemsys, max_results)
            self.events.put(("search_results", results))

        self._run_worker("搜索材料", task)

    def _download_selected_results(self) -> None:
        selected_items = self.results_tree.selection()
        if not selected_items:
            messagebox.showwarning("未选择结果", "请先在表格中选择至少一个材料。")
            return
        mpids = [self.results_tree.item(item, "values")[0] for item in selected_items]
        self._download_result_mpids(mpids, "下载选中 CIF")

    def _download_all_results(self) -> None:
        if not self.search_results:
            messagebox.showwarning("没有搜索结果", "请先完成一次化学体系搜索。")
            return
        mpids = [item.material_id for item in self.search_results]
        self._download_result_mpids(mpids, "下载全部搜索结果")

    def _download_result_mpids(self, mpids: list[str], label: str) -> None:
        try:
            api_key = self._api_key()
            output_dir = self._output_dir()
            conventional_cell = self.conventional_cell_var.get()
            include_elasticity = self.include_elasticity_var.get()
        except Exception as exc:
            messagebox.showerror("设置错误", str(exc))
            return

        def task() -> None:
            suffix = "，并同步查询 Cij 弹性常数" if include_elasticity else ""
            self.events.put(("log", f"开始下载 {len(mpids)} 个搜索结果 CIF{suffix}。"))
            service = MaterialsProjectService(api_key)
            results = service.download_cifs(
                mpids,
                output_dir,
                conventional_cell,
                include_elasticity=include_elasticity,
                name_meta=self._name_meta_for_mpids(mpids),
            )
            self.events.put(("download_results", results))

        self._run_worker(label, task)

    def _name_meta_for_mpids(self, mpids: list[str]) -> dict[str, CifNameMeta]:
        """Build CIF name metadata from current search rows when available."""

        by_id = {
            str(item.material_id).strip().lower(): item for item in self.search_results
        }
        meta: dict[str, CifNameMeta] = {}
        for mpid in mpids:
            key = str(mpid).strip().lower()
            summary = by_id.get(key)
            if summary is not None:
                meta[key] = CifNameMeta.from_material_summary(summary)
        return meta

    def _poll_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self._log(str(payload))
            elif kind == "error":
                self._log("错误: " + str(payload))
                messagebox.showerror("任务失败", str(payload))
            elif kind == "search_results":
                self._show_search_results(payload)  # type: ignore[arg-type]
            elif kind == "download_results":
                self._show_download_results(payload)  # type: ignore[arg-type]
            elif kind == "done":
                self._set_busy(False, "Ready")

        self.root.after(100, self._poll_events)

    def _show_search_results(self, results: list[MaterialSummary]) -> None:
        self.search_results = results
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)

        for result in results:
            self.results_tree.insert(
                "",
                "end",
                values=(
                    result.material_id,
                    result.formula,
                    self._format_float(result.energy_above_hull),
                    self._format_float(result.band_gap),
                    result.crystal_system,
                    result.spacegroup,
                ),
            )

        self._log(f"搜索完成：找到 {len(results)} 条结果。")

    def _show_download_results(self, results) -> None:
        ok_count = 0
        fail_count = 0
        elasticity_ok = 0
        elasticity_missing = 0
        elasticity_dirs = set()
        for result in results:
            if result.ok:
                ok_count += 1
                self._log(f"保存成功: {result.material_id} -> {result.path}")
                if result.elasticity_found is True:
                    elasticity_ok += 1
                    if result.elasticity_path is not None:
                        elasticity_dirs.add(result.elasticity_path.parent)
                    self._log(f"Cij 保存成功: {result.material_id} -> {result.elasticity_path}")
                elif result.elasticity_found is False:
                    elasticity_missing += 1
                    if result.elasticity_path is not None:
                        elasticity_dirs.add(result.elasticity_path.parent)
                    self._log(f"Cij 未获得: {result.material_id} -> {result.elasticity_error}")
            else:
                fail_count += 1
                self._log(f"保存失败: {result.material_id} -> {result.error}")
        self._log(f"下载结束：成功 {ok_count} 个，失败 {fail_count} 个。")
        if elasticity_ok or elasticity_missing:
            self._log(f"Cij 查询结束：获得 {elasticity_ok} 个，缺失/失败 {elasticity_missing} 个。")
            for directory in sorted(elasticity_dirs, key=str):
                self._log(f"Cij 索引: {directory / 'elasticity_index.csv'}")
                self._log(
                    f"下游 CIF2Peaks：将文件夹拖入即可自动匹配 Cij → {directory}"
                )

    def _set_busy(self, busy: bool, label: str) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in self.action_buttons:
            button.configure(state=state)
        self.status_var.set(label if busy else "Ready")

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    @staticmethod
    def _format_float(value: float | None) -> str:
        if value is None:
            return ""
        try:
            return f"{float(value):.4f}"
        except Exception:
            return str(value)


def main() -> None:
    DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    root = Tk()
    PhaseScoutApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
