from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import re
import sys
from collections.abc import Callable
from typing import Mapping, Sequence

import numpy as np

from .batch import export_output_paths
from .constants import DEFAULT_XRD_SOURCE, X_RAY_ENERGY_WAVELENGTH_KEV_A
from .elastic import ElasticConstants
from .elastic_io import load_elastic_for_cif
from .exporters import export_cif2peaks_pattern_workbook, export_cif2peaks_workbook
from .models import Cif2PeaksExportPayload, Cif2PeaksSettings, XrdAxisMode
from .plotting import (
    FIGURE_EXPORT_PRESETS,
    export_xrd_pattern_eps,
    export_xrd_pattern_pdf,
    export_xrd_pattern_png,
    export_xrd_pattern_svg,
    export_xrd_pattern_tiff,
)
from .service import Cif2PeaksService
from .utils import friendly_cif_issue_message


@dataclass(frozen=True)
class SimpleGuiExportResult:
    output_path: Path
    total_peaks: int
    phase_rows: list[tuple[str, str, str, int, str, str]]
    peak_output_path: Path | None = None
    pattern_output_path: Path | None = None
    publication_figure_paths: list[Path] = field(default_factory=list)
    phase_error_flags: list[bool] = field(default_factory=list)


@dataclass(frozen=True)
class SimpleGuiPreviewResult:
    ready_count: int
    failed_count: int
    phase_rows: list[tuple[str, str, str, str, str, str]]


@dataclass(frozen=True)
class GuiExportDiagnostics:
    total_phases: int
    ready_count: int
    failed_count: int
    warning_count: int
    zero_peak_count: int


@dataclass(frozen=True)
class GuiCifInputUpdate:
    added_count: int
    ignored_count: int


SUPPORTED_GUI_LANGUAGES = ("zh", "en")
GUI_PUBLICATION_PRESET_LABELS = tuple(
    name for name in ("publication", "single_column", "double_column", "presentation", "raw_inspection") if name in FIGURE_EXPORT_PRESETS
)
APP_DISPLAY_NAME = "CIF2peaks"
DEVELOPER_CREDIT = "Developed by Dr. GONG Delun"
GUI_THEME = {
    "surface": "#e8edf3",
    "panel": "#ffffff",
    "panel_raised": "#fdfefe",
    "panel_muted": "#f5f7fb",
    "panel_alt": "#f8fafc",
    "section_header": "#f1f5f9",
    "status_bg": "#eef6ff",
    "primary": "#2563eb",
    "primary_active": "#1d4ed8",
    "accent": "#0f766e",
    "success": "#188038",
    "warning": "#b7791f",
    "danger": "#b3261e",
    "focus": "#60a5fa",
    "border": "#cbd5e1",
    "border_strong": "#94a3b8",
    "text": "#111827",
    "muted": "#526070",
    "subtle": "#7b8794",
    "table_header": "#dbe5f1",
}
GUI_WORKBENCH_LAYOUT = {
    "geometry": "1200x760",
    "minsize": (1040, 680),
    "sidebar_width": 330,
    "scrollable_main": True,
}
CIJ_TABLE_SIZE = 6
GUI_TOOLTIP_KEYS = {
    "add_files": "tooltip_add_files",
    "add_folder": "tooltip_add_folder",
    "remove_selected": "tooltip_remove_selected",
    "clear_files": "tooltip_clear_files",
    "display_name": "tooltip_display_name",
    "elastic_cubic": "tooltip_elastic_cubic",
    "elastic_matrix": "tooltip_elastic_matrix",
    "elastic_source": "tooltip_elastic_source",
    "apply_elastic": "tooltip_apply_elastic",
    "clear_elastic": "tooltip_clear_elastic",
    "paste_elastic": "tooltip_paste_elastic",
    "copy_elastic": "tooltip_copy_elastic",
    "fill_cubic_elastic": "tooltip_fill_cubic_elastic",
    "output_file": "tooltip_output_file",
    "choose_output": "tooltip_choose_output",
    "xray_preset": "tooltip_xray_preset",
    "manual_energy": "tooltip_manual_energy",
    "d_range": "tooltip_d_range",
    "export_peaks": "tooltip_export_peaks",
    "export_patterns": "tooltip_export_patterns",
    "pattern_axis": "tooltip_pattern_axis",
    "publication_export": "tooltip_publication_export",
    "figure_preset": "tooltip_figure_preset",
    "export_excel": "tooltip_export_excel",
    "open_excel": "tooltip_open_excel",
}
GUI_TEXT = {
    "zh": {
        "window_title": "CIF2peaks - CIF 转 Excel",
        "app_title": "CIF2peaks",
        "app_subtitle": "CIF 晶体结构到理论粉末 XRD 峰表的数据工作台",
        "developer_credit": DEVELOPER_CREDIT,
        "toggle_language": "English",
        "workspace_section": "XRD Peak Reference Workbench",
        "data_source_title": "CIF 数据源",
        "parameters_title": "导出参数",
        "required_parameters_group": "必需参数",
        "output_content_group": "输出内容",
        "optional_outputs_group": "可选输出",
        "advanced_elastic_group": "可选高级项：Cij 弹性常数",
        "preview_title": "峰表预览",
        "status_ready": "就绪",
        "files_panel": "1. 添加 CIF 文件并命名",
        "display_name_label": "选中 CIF 显示名",
        "apply_display_name": "应用相名",
        "reset_display_name": "恢复文件名",
        "elastic_cubic_label": "选中相 Cij 快速填充 (C11, C12, C44 / GPa)",
        "elastic_matrix_label": "6x6 Cij 表格 (GPa)，可从 Excel/Origin 直接粘贴",
        "elastic_source_label": "Cij 来源",
        "fill_cubic_elastic": "填充立方",
        "paste_elastic": "粘贴矩阵",
        "copy_elastic": "复制矩阵",
        "apply_elastic": "应用 Cij",
        "clear_elastic": "清除 Cij",
        "elastic_apply_failed_title": "Cij 输入无效",
        "elastic_paste_failed_title": "粘贴 Cij 失败",
        "elastic_status_empty": "Cij 状态：未应用",
        "elastic_status_value": "Cij 状态：{status}",
        "elastic_status_with_warning": "Cij 状态：{status} - {warning}",
        "elastic_status_input_error": "Cij 输入错误：{warning}",
        "elastic_status_ready_to_apply": "已填入 Cij，点击“应用 Cij”保存到当前相。",
        "elastic_auto_loaded": "已从 PhaseScout 旁路自动加载 Cij：{count} 个相。",
        "elastic_copied": "已复制 Cij 表格。",
        "add_files": "添加 CIF",
        "add_folder": "添加文件夹",
        "remove_selected": "移除选中",
        "clear_files": "清空列表",
        "settings_panel": "2. 保存位置和 X 射线参数",
        "output_file": "结果文件",
        "choose_output": "选择输出",
        "xray_preset": "X 射线预设",
        "manual_energy": "手动能量 keV",
        "d_range": "d 范围",
        "publication_export": "同时导出论文级图（SVG/PDF/EPS/PNG/TIFF）",
        "figure_preset": "图像预设",
        "settings_hint": "手动能量非空时优先生效；留空则使用上方预设。",
        "preview_panel": "3. CIF 预览 / 导出结果",
        "activity_log_title": "运行记录",
        "tree_display_name": "显示名",
        "tree_formula": "化学式",
        "tree_space_group": "空间群",
        "tree_status": "状态 / 峰数",
        "tree_warning": "错误 / 警告",
        "tree_elastic": "弹性常数",
        "export_excel": "导出结果",
        "open_excel": "打开 Excel",
        "no_cif": "尚未添加 CIF 文件",
        "cif_count": "已添加 {count} 个 CIF 文件",
        "drop_hint_available": "可直接把 CIF 文件或文件夹拖到这里。",
        "drop_hint_unavailable": "当前环境未启用窗口拖放；请使用“添加文件”或把 CIF 拖到 EXE 图标上启动。",
        "ready_to_add": "准备就绪：添加 CIF 文件后，直接点击“导出结果”。",
        "ready_to_export": "可以导出：确认保存位置和图像选项后点击“导出结果”。",
        "reading_cif": "正在读取 CIF 基本信息...",
        "recognized_with_failures": "已识别 {ready} 个 CIF；{failed} 个无法读取，仍可导出其它可用文件。",
        "recognized_ready": "已识别 {ready} 个 CIF：确认保存位置和图像选项后点击“导出结果”。",
        "add_source": "{source}：新增 {added} 个 CIF{suffix}。",
        "add_source_none": "{source}：没有新增 CIF，已忽略 {ignored} 项（JSON 等非 CIF 不会进列表；同目录旁路仍可自动匹配 Cij）。",
        "ignored_suffix": "，忽略 {ignored} 项非 CIF/重复项",
        "source_add_files": "添加文件",
        "source_add_folder": "添加文件夹",
        "source_drop": "拖入文件",
        "choose_cif_title": "选择 CIF 文件",
        "choose_folder_title": "选择包含 CIF 文件的文件夹",
        "save_output_title": "保存 Excel 结果",
        "excel_filetype": "Excel workbook",
        "energy_manual": "手动能量：{energy} keV",
        "energy_preset": "预设：{preset}",
        "unrestricted": "不限制",
        "d_range_summary": "d {lower}-{upper} Å",
        "d_unrestricted_summary": "d: 不限制",
        "settings_summary": "{source}，{range}",
        "to_text": " 到 ",
        "angstrom": " Å",
        "exporting": "正在计算 XRD 峰表并写入 Excel，请稍候...",
        "export_failed_status": "导出失败。",
        "select_export_type": "请至少选择一种导出内容：峰位表或 XRD 谱线。",
        "export_failed_title": "导出失败",
        "export_done_title": "导出完成",
        "export_cancelled_overwrite": "已取消导出：目标文件已存在。",
        "result_next_step": "下一步：先打开 使用说明 看阅读顺序，再看 Summary 检查错误/警告，常用峰表看 推荐峰表。",
        "log_ready": "就绪：等待添加 CIF 文件。",
        "log_added": "{source}：加入 {added} 个 CIF{suffix}。",
        "log_add_none": "{source}：没有新增 CIF，已忽略 {ignored} 项。",
        "log_cleared": "已清空当前 CIF 列表和预览。",
        "log_preview_reading": "正在读取 CIF 元数据。",
        "log_preview_ready": "预览完成：{ready} 个 CIF 可导出。",
        "log_preview_with_failures": "预览完成：{ready} 个可导出，{failed} 个无法读取。",
        "log_exporting": "开始导出：正在计算峰表并写入结果文件。",
        "log_export_done": "导出完成：{peaks} 条峰记录；失败 {failed} 个，警告 {warnings} 个，零峰 {zero_peaks} 个。",
        "log_export_failed": "导出失败：请查看错误提示。",
        "log_export_cancelled": "导出已取消：目标文件已存在。",
        "drop_unavailable_short": "当前窗口拖放不可用；请使用“添加文件”或把 CIF 拖到 EXE 图标上启动。",
        "preview_pending": "待导出",
        "preview_failed": "无法读取",
        "default_output_name": "CIF2Peaks峰表.xlsx",
        "tooltip_add_files": "选择一个或多个 CIF 文件加入当前批量导出列表。",
        "tooltip_add_folder": "选择文件夹后自动递归加入其中的 CIF 文件。",
        "tooltip_remove_selected": "仅从当前列表移除选中的 CIF，不删除磁盘文件。",
        "tooltip_clear_files": "清空当前 CIF 列表和预览，不删除磁盘文件。",
        "tooltip_display_name": "为选中的 CIF 设置导出表中的相名；留空则使用文件名。",
        "tooltip_elastic_cubic": "输入 C11,C12,C44 后点击“填充立方”，自动生成完整 6x6 Cij 表格。",
        "tooltip_elastic_matrix": "逐格输入 Cij，或从 Excel、Origin、文本中复制完整 6x6 矩阵后粘贴。",
        "tooltip_elastic_source": "记录该相 Cij 的文献、数据库或备注来源，会写入 Elastic Constants 工作表。",
        "tooltip_apply_elastic": "校验并把当前 Cij 表格保存到选中的 CIF 相。",
        "tooltip_clear_elastic": "清除选中 CIF 相已保存的 Cij，不删除 CIF 文件。",
        "tooltip_paste_elastic": "从剪贴板读取完整 6x6 Cij 矩阵并填入表格。",
        "tooltip_copy_elastic": "把当前 6x6 Cij 表格复制为制表符分隔文本。",
        "tooltip_fill_cubic_elastic": "用 C11,C12,C44 生成立方晶系 Cij 矩阵并填入表格。",
        "tooltip_output_file": "Excel 工作簿保存路径；导出会写入该文件。",
        "tooltip_choose_output": "选择或更改 Excel 输出位置。",
        "tooltip_xray_preset": "选择常用 X 射线波长/能量；手动能量非空时优先使用手动值。",
        "tooltip_manual_energy": "可选，单位 keV；用于同步辐射等非 Cu Kα 条件。",
        "tooltip_d_range": "可选，只导出指定 d 间距范围内的理论峰。",
        "tooltip_publication_export": "导出 Excel 的同时，为每个可计算相生成论文级 SVG/PDF/EPS 矢量图和 600 dpi PNG/TIFF 位图。",
        "tooltip_figure_preset": "选择论文级图的尺寸、DPI、字体和线宽预设；默认 publication 适合论文初稿。",
        "tooltip_export_excel": "计算理论 XRD 峰表并写入 Excel；若已勾选论文级图，也会同时导出图像文件。",
        "tooltip_open_excel": "打开最近一次成功导出的 Excel 文件。",
        "confirm_clear_title": "清空 CIF 列表",
        "confirm_clear_message": "确定清空当前 CIF 列表和预览吗？这不会删除磁盘上的原始文件。",
        "confirm_overwrite_title": "覆盖已有文件",
        "confirm_overwrite_message": "目标输出文件已存在：\n{path}\n\n是否覆盖该文件？",
    },
    "en": {
        "window_title": "CIF2peaks - CIF to Excel",
        "app_title": "CIF2peaks",
        "app_subtitle": "A data workbench for CIF structures and theoretical powder XRD peak tables",
        "developer_credit": DEVELOPER_CREDIT,
        "toggle_language": "中文",
        "workspace_section": "XRD Peak Reference Workbench",
        "data_source_title": "CIF data source",
        "parameters_title": "Export parameters",
        "required_parameters_group": "Required settings",
        "output_content_group": "Output content",
        "optional_outputs_group": "Optional outputs",
        "advanced_elastic_group": "Optional advanced: Cij elastic constants",
        "preview_title": "Peak table preview",
        "status_ready": "Ready",
        "files_panel": "1. Add and name CIF files",
        "display_name_label": "Selected CIF display name",
        "apply_display_name": "Apply phase name",
        "reset_display_name": "Use file name",
        "elastic_cubic_label": "Selected phase Cij quick fill (C11, C12, C44 / GPa)",
        "elastic_matrix_label": "6x6 Cij table (GPa); paste directly from Excel/Origin",
        "elastic_source_label": "Cij source",
        "fill_cubic_elastic": "Fill cubic",
        "paste_elastic": "Paste matrix",
        "copy_elastic": "Copy matrix",
        "apply_elastic": "Apply Cij",
        "clear_elastic": "Clear Cij",
        "elastic_apply_failed_title": "Invalid Cij input",
        "elastic_paste_failed_title": "Cij paste failed",
        "elastic_status_empty": "Cij status: not applied",
        "elastic_status_value": "Cij status: {status}",
        "elastic_status_with_warning": "Cij status: {status} - {warning}",
        "elastic_status_input_error": "Cij input error: {warning}",
        "elastic_status_ready_to_apply": "Cij table filled. Click Apply Cij to save it to the selected phase.",
        "elastic_auto_loaded": "Auto-loaded PhaseScout Cij sidecars for {count} phase(s).",
        "elastic_copied": "Copied the Cij table.",
        "add_files": "Add CIFs",
        "add_folder": "Add folder",
        "remove_selected": "Remove selected",
        "clear_files": "Clear list",
        "settings_panel": "2. Output and X-ray settings",
        "output_file": "Output file",
        "choose_output": "Choose output",
        "xray_preset": "X-ray preset",
        "manual_energy": "Manual energy keV",
        "d_range": "d range",
        "publication_export": "Export figures (SVG/PDF/EPS/PNG/TIFF)",
        "figure_preset": "Figure preset",
        "settings_hint": "Manual energy overrides preset; blank uses preset.",
        "preview_panel": "3. CIF preview / export result",
        "activity_log_title": "Activity log",
        "tree_display_name": "Display name",
        "tree_formula": "Formula",
        "tree_space_group": "Space group",
        "tree_status": "Status / peaks",
        "tree_warning": "Error / warning",
        "tree_elastic": "Elastic constants",
        "export_excel": "Export results",
        "open_excel": "Open Excel",
        "no_cif": "No CIF files added",
        "cif_count": "{count} CIF file(s) added",
        "drop_hint_available": "You can drop CIF files or folders here.",
        "drop_hint_unavailable": "Window drag-and-drop is unavailable; use Add files or launch by dropping CIFs onto the EXE.",
        "ready_to_add": "Ready: add CIF files, then click Export results.",
        "ready_to_export": "Ready to export: confirm the output path and figure options, then click Export results.",
        "reading_cif": "Reading CIF metadata...",
        "recognized_with_failures": "Recognized {ready} CIF file(s); {failed} could not be read, but usable files can still be exported.",
        "recognized_ready": "Recognized {ready} CIF file(s): confirm the output path and figure options, then click Export results.",
        "add_source": "{source}: added {added} CIF file(s){suffix}.",
        "add_source_none": "{source}: no new CIF files; ignored {ignored} item(s) (non-CIF such as JSON are not listed; same-folder sidecars still auto-match Cij).",
        "ignored_suffix": ", ignored {ignored} non-CIF/duplicate item(s)",
        "source_add_files": "Add files",
        "source_add_folder": "Add folder",
        "source_drop": "Drop",
        "choose_cif_title": "Choose CIF files",
        "choose_folder_title": "Choose a folder containing CIF files",
        "save_output_title": "Save Excel result",
        "excel_filetype": "Excel workbook",
        "energy_manual": "Manual energy: {energy} keV",
        "energy_preset": "Preset: {preset}",
        "unrestricted": "unrestricted",
        "d_range_summary": "d {lower}-{upper} Å",
        "d_unrestricted_summary": "d: unrestricted",
        "settings_summary": "{source}, {range}",
        "to_text": " to ",
        "angstrom": " Å",
        "exporting": "Calculating XRD peaks and writing Excel. Please wait...",
        "export_failed_status": "Export failed.",
        "select_export_type": "Select at least one output: peak table or XRD pattern data.",
        "export_failed_title": "Export failed",
        "export_done_title": "Export complete",
        "export_cancelled_overwrite": "Export cancelled: target file already exists.",
        "result_next_step": "Next step: open the User Guide for reading order, check Summary for errors/warnings, then use the Recommended peak table.",
        "log_ready": "Ready: waiting for CIF files.",
        "log_added": "{source}: added {added} CIF file(s){suffix}.",
        "log_add_none": "{source}: no new CIF files; ignored {ignored} item(s).",
        "log_cleared": "Cleared the current CIF list and preview.",
        "log_preview_reading": "Reading CIF metadata.",
        "log_preview_ready": "Preview complete: {ready} CIF file(s) ready to export.",
        "log_preview_with_failures": "Preview complete: {ready} ready, {failed} could not be read.",
        "log_exporting": "Started export: calculating peak tables and writing result files.",
        "log_export_done": "Export complete: {peaks} peak record(s); {failed} failed, {warnings} warning(s), {zero_peaks} zero-peak phase(s).",
        "log_export_failed": "Export failed: see the error message.",
        "log_export_cancelled": "Export cancelled: target file already exists.",
        "drop_unavailable_short": "Window drag-and-drop is unavailable; use Add files or launch by dropping CIFs onto the EXE.",
        "preview_pending": "Ready",
        "preview_failed": "Cannot read",
        "default_output_name": "CIF2Peaks_peak_table.xlsx",
        "tooltip_add_files": "Choose one or more CIF files for the current batch export.",
        "tooltip_add_folder": "Choose a folder and add CIF files from it recursively.",
        "tooltip_remove_selected": "Remove selected CIFs from this list only; source files are not deleted.",
        "tooltip_clear_files": "Clear the current CIF list and preview; source files are not deleted.",
        "tooltip_display_name": "Set the phase name used in exported tables; leave blank to use the file name.",
        "tooltip_elastic_cubic": "Enter C11,C12,C44 and click Fill cubic to generate a full 6x6 Cij table.",
        "tooltip_elastic_matrix": "Enter Cij cell by cell, or paste a full 6x6 matrix copied from Excel, Origin, or text.",
        "tooltip_elastic_source": "Record the literature, database, or note source for this phase's Cij; it is exported in the Elastic Constants sheet.",
        "tooltip_apply_elastic": "Validate and save the current Cij table to the selected CIF phase.",
        "tooltip_clear_elastic": "Clear the saved Cij for the selected CIF phase without deleting the CIF file.",
        "tooltip_paste_elastic": "Read a full 6x6 Cij matrix from the clipboard and fill the table.",
        "tooltip_copy_elastic": "Copy the current 6x6 Cij table as tab-separated text.",
        "tooltip_fill_cubic_elastic": "Use C11,C12,C44 to generate a cubic Cij matrix and fill the table.",
        "tooltip_output_file": "Excel workbook path that will be written during export.",
        "tooltip_choose_output": "Choose or change the Excel output location.",
        "tooltip_xray_preset": "Select a common X-ray wavelength/energy; manual energy takes priority when filled.",
        "tooltip_manual_energy": "Optional, in keV; useful for synchrotron conditions or non-Cu Kalpha setups.",
        "tooltip_d_range": "Optional; export theoretical peaks only within the selected d-spacing range.",
        "tooltip_publication_export": "Generate publication-style SVG/PDF/EPS vector figures plus 600 dpi PNG/TIFF rasters for each calculable phase alongside the Excel workbook.",
        "tooltip_figure_preset": "Choose the figure size, DPI, font and line-width preset; publication is the default manuscript draft style.",
        "tooltip_export_excel": "Calculate theoretical XRD peak tables and write the Excel workbook; if publication figures are enabled, export those image files too.",
        "tooltip_open_excel": "Open the most recently exported Excel workbook.",
        "confirm_clear_title": "Clear CIF list",
        "confirm_clear_message": "Clear the current CIF list and preview? This will not delete source files from disk.",
        "confirm_overwrite_title": "Overwrite existing file",
        "confirm_overwrite_message": "The target output file already exists:\n{path}\n\nOverwrite this file?",
    },
}

GUI_XRAY_PRESET_LABELS = ["Cu Kα", "30 keV", "83 keV"]
GUI_XRAY_PRESETS = {
    "Cu Kα": None,
    "Cu Ka": None,
    "30 keV": 30.0,
    "83 keV": 83.0,
}

GUI_TEXT["zh"].update(
    {
        "export_peaks": "导出峰位表",
        "export_patterns": "导出XRD谱线",
        "pattern_axis": "谱线 x轴",
        "tooltip_export_peaks": "导出原有 hkl/d/2θ 峰位表。",
        "tooltip_export_patterns": "导出每个 CIF 的连续模拟 XRD 谱线 x-y 数据到单独 Excel。",
        "tooltip_pattern_axis": "选择谱线数据表中 x 列使用 2θ、d、q 或 g。",
    }
)
GUI_TEXT["en"].update(
    {
        "export_peaks": "Export peak table",
        "export_patterns": "Export XRD pattern data",
        "pattern_axis": "Pattern x axis",
        "tooltip_export_peaks": "Export the hkl/d/2theta peak reference workbook.",
        "tooltip_export_patterns": "Export continuous simulated XRD x-y profile data for each CIF to a separate Excel workbook.",
        "tooltip_pattern_axis": "Choose whether the pattern data x column uses 2theta, d, q, or g.",
    }
)


def _gui_text(language: str, key: str, **kwargs: object) -> str:
    language_key = language if language in GUI_TEXT else "zh"
    template = GUI_TEXT[language_key][key]
    return template.format(**kwargs) if kwargs else template


def should_clear_gui_files(file_count: int, confirm: Callable[[], bool]) -> bool:
    return file_count <= 0 or confirm()


def should_overwrite_gui_output(output_path: str | Path, confirm: Callable[[Path], bool]) -> bool:
    path = normalize_xlsx_output_path(output_path)
    return not path.exists() or confirm(path)


def should_overwrite_gui_outputs(output_paths: Sequence[str | Path | None], confirm: Callable[[Path], bool]) -> bool:
    seen: set[Path] = set()
    for output_path in output_paths:
        if output_path is None:
            continue
        path = Path(output_path).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        if path.exists() and not confirm(path):
            return False
    return True


def gui_export_control_states(
    *,
    has_files: bool,
    export_peaks: bool,
    export_patterns: bool,
    export_publication_figures: bool,
    is_busy: bool = False,
) -> dict[str, str]:
    has_output = export_peaks or export_patterns
    return {
        "export_button": "normal" if has_files and has_output and not is_busy else "disabled",
        "pattern_axis": "readonly" if export_patterns else "disabled",
        "figure_preset": "readonly" if export_publication_figures else "disabled",
    }


def _resolved_display_name_lookup(display_names: Mapping[str | Path, str] | None) -> dict[Path, str]:
    if display_names is None:
        return {}
    lookup: dict[Path, str] = {}
    for key, value in display_names.items():
        try:
            path = Path(key).expanduser().resolve()
        except OSError:
            continue
        lookup[path] = str(value).strip()
    return lookup


def _display_name_for_path(path: Path, display_name_lookup: Mapping[Path, str]) -> str:
    resolved = Path(path).expanduser().resolve()
    return display_name_lookup.get(resolved, "").strip() or resolved.name


def _apply_display_names_to_phases(
    phases: Sequence[object],
    display_names: Mapping[str | Path, str] | None,
) -> None:
    lookup = _resolved_display_name_lookup(display_names)
    for phase in phases:
        phase_path = getattr(phase, "cif_path")
        setattr(phase, "phase_name", _display_name_for_path(phase_path, lookup))


def _resolved_elastic_constants_lookup(
    elastic_constants: Mapping[str | Path, ElasticConstants] | None,
) -> dict[Path, ElasticConstants]:
    if elastic_constants is None:
        return {}
    lookup: dict[Path, ElasticConstants] = {}
    for key, value in elastic_constants.items():
        try:
            path = Path(key).expanduser().resolve()
        except OSError:
            continue
        lookup[path] = value
    return lookup


def _apply_elastic_constants_to_phases(
    phases: Sequence[object],
    elastic_constants: Mapping[str | Path, ElasticConstants] | None,
) -> None:
    lookup = _resolved_elastic_constants_lookup(elastic_constants)
    for phase in phases:
        phase_path = Path(getattr(phase, "cif_path")).expanduser().resolve()
        setattr(phase, "elastic_constants", lookup.get(phase_path))


def _phase_elastic_status_text(phase: object) -> str:
    elastic = getattr(phase, "elastic_constants", None)
    return "no_elastic_constants" if elastic is None else elastic.status


def _elastic_cubic_summary(elastic: ElasticConstants | None) -> str:
    if elastic is None or not elastic.stiffness_GPa:
        return ""
    matrix = elastic.stiffness_matrix_GPa
    if matrix.shape != (6, 6):
        return ""
    c11 = matrix[0, 0]
    c12 = matrix[0, 1]
    c44 = matrix[3, 3]
    cubic_pattern = np.zeros((6, 6), dtype=float)
    cubic_pattern[0, 0] = cubic_pattern[1, 1] = cubic_pattern[2, 2] = c11
    cubic_pattern[0, 1] = cubic_pattern[0, 2] = cubic_pattern[1, 0] = c12
    cubic_pattern[1, 2] = cubic_pattern[2, 0] = cubic_pattern[2, 1] = c12
    cubic_pattern[3, 3] = cubic_pattern[4, 4] = cubic_pattern[5, 5] = c44
    if not np.allclose(matrix, cubic_pattern, rtol=1e-6, atol=1e-8):
        return ""
    return f"{c11:g}, {c12:g}, {c44:g}"


def _parse_finite_cij_value(value: object, label: str) -> float:
    try:
        number = float(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number.")
    return number


def _parse_cubic_cij(text: str, source: str = "") -> ElasticConstants:
    values = [item for item in re.split(r"[\s,;]+", text.strip()) if item]
    if len(values) != 3:
        raise ValueError("Enter exactly three Cij values: C11, C12, C44 in GPa.")
    c11, c12, c44 = (
        _parse_finite_cij_value(value, label)
        for value, label in zip(values, ("C11", "C12", "C44"), strict=True)
    )
    return ElasticConstants.from_cubic(c11_GPa=c11, c12_GPa=c12, c44_GPa=c44, source=source.strip())


def _blank_cij_table_values() -> list[list[str]]:
    return [["" for _column in range(CIJ_TABLE_SIZE)] for _row in range(CIJ_TABLE_SIZE)]


def _parse_cij_paste_matrix(text: str) -> list[list[str]]:
    rows = [[value for value in re.split(r"[\s,;]+", line.strip()) if value] for line in text.strip().splitlines() if line.strip()]
    flat_count = CIJ_TABLE_SIZE * CIJ_TABLE_SIZE
    if len(rows) == 1 and len(rows[0]) == flat_count:
        flat = rows[0]
        return [flat[index : index + CIJ_TABLE_SIZE] for index in range(0, flat_count, CIJ_TABLE_SIZE)]
    if len(rows) == CIJ_TABLE_SIZE and all(len(row) == CIJ_TABLE_SIZE for row in rows):
        return rows
    raise ValueError("Paste a full 6x6 Cij matrix: six rows with six GPa values per row.")


def _parse_cij_table_values(values: Sequence[Sequence[object]], source: str = "") -> ElasticConstants:
    rows = [list(row) for row in values]
    if len(rows) != CIJ_TABLE_SIZE or any(len(row) != CIJ_TABLE_SIZE for row in rows):
        raise ValueError("Cij table must be 6x6: enter six rows with six GPa values per row.")

    matrix: list[list[float]] = []
    for row_index, row in enumerate(rows, start=1):
        parsed_row: list[float] = []
        for column_index, value in enumerate(row, start=1):
            label = f"C{row_index}{column_index}"
            text = str(value).strip()
            if not text:
                raise ValueError(f"{label} is required.")
            parsed_row.append(_parse_finite_cij_value(text, label))
        matrix.append(parsed_row)
    return ElasticConstants.from_matrix(matrix, source=source.strip())


def _parse_full_cij_matrix(text: str, source: str = "") -> ElasticConstants:
    try:
        values = _parse_cij_paste_matrix(text)
    except ValueError:
        raise ValueError("Paste a full 6x6 Cij matrix: six rows with six GPa values per row.") from None
    return _parse_cij_table_values(values, source=source)


def _format_cij_number(value: object) -> str:
    number = float(value)
    if abs(number) < 1e-12:
        number = 0.0
    return f"{number:g}"


def _format_cij_table_values(elastic: ElasticConstants | None) -> list[list[str]]:
    if elastic is None or not elastic.stiffness_GPa:
        return _blank_cij_table_values()
    matrix = elastic.stiffness_matrix_GPa
    if matrix.shape != (CIJ_TABLE_SIZE, CIJ_TABLE_SIZE):
        return _blank_cij_table_values()
    return [[_format_cij_number(matrix[row, column]) for column in range(CIJ_TABLE_SIZE)] for row in range(CIJ_TABLE_SIZE)]


def _cubic_cij_table_values(text: str) -> list[list[str]]:
    return _format_cij_table_values(_parse_cubic_cij(text))


def _format_cij_matrix(elastic: ElasticConstants | None) -> str:
    values = _format_cij_table_values(elastic)
    if not any(any(cell for cell in row) for row in values):
        return ""
    return "\n".join(" ".join(row) for row in values)


def _elastic_status_feedback(elastic: ElasticConstants | None, language: str = "zh") -> str:
    if elastic is None:
        return _gui_text(language, "elastic_status_empty")
    warnings = " | ".join(elastic.warnings)
    if warnings:
        return _gui_text(language, "elastic_status_with_warning", status=elastic.status, warning=warnings)
    return _gui_text(language, "elastic_status_value", status=elastic.status)


def _elastic_status_style_name(elastic: ElasticConstants | None) -> str:
    if elastic is None:
        return "ElasticMuted.TLabel"
    if elastic.status == "invalid_elastic_constants":
        return "ElasticError.TLabel"
    if elastic.status == "valid_with_warnings":
        return "ElasticWarning.TLabel"
    return "ElasticValid.TLabel"


def _safe_filename_stem(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned[:80] or "phase"


def _publication_figure_path(output: Path, phase_name: str, index: int, suffix: str) -> Path:
    phase_stem = _safe_filename_stem(phase_name)
    return output.with_name(f"{output.stem}_{index:02d}_{phase_stem}_publication{suffix}")


def _configure_workbench_theme(root: object, style: object) -> None:
    try:
        style.theme_use("clam")
    except Exception:
        pass
    root.configure(background=GUI_THEME["surface"])
    font = ("Microsoft YaHei UI", 10)
    style.configure(".", font=font)
    style.configure("TFrame", background=GUI_THEME["surface"])
    style.configure("Workbench.TFrame", background=GUI_THEME["surface"])
    style.configure("Header.TFrame", background=GUI_THEME["surface"])
    style.configure(
        "Card.TFrame",
        background=GUI_THEME["panel_raised"],
        relief="solid",
        borderwidth=1,
        bordercolor=GUI_THEME["border"],
        lightcolor=GUI_THEME["panel"],
        darkcolor=GUI_THEME["border"],
    )
    style.configure("CardBody.TFrame", background=GUI_THEME["panel_raised"])
    style.configure("PanelMuted.TFrame", background=GUI_THEME["panel_muted"])
    style.configure("Toolbar.TFrame", background=GUI_THEME["panel_raised"])
    style.configure("SectionHeader.TFrame", background=GUI_THEME["section_header"])
    style.configure("DataAccent.TFrame", background=GUI_THEME["accent"])
    style.configure("SettingsAccent.TFrame", background=GUI_THEME["primary"])
    style.configure("PreviewAccent.TFrame", background=GUI_THEME["success"])
    style.configure("Status.TFrame", background=GUI_THEME["status_bg"], relief="solid", borderwidth=1)
    style.configure("Footer.TFrame", background=GUI_THEME["surface"])
    style.configure("TLabel", background=GUI_THEME["surface"], foreground=GUI_THEME["text"])
    style.configure("Card.TLabel", background=GUI_THEME["panel_raised"], foreground=GUI_THEME["text"])
    style.configure("Title.TLabel", font=("Microsoft YaHei UI", 22, "bold"), foreground=GUI_THEME["text"])
    style.configure(
        "Section.TLabel",
        font=("Microsoft YaHei UI", 12, "bold"),
        background=GUI_THEME["panel_raised"],
        foreground=GUI_THEME["text"],
    )
    style.configure(
        "SectionTitle.TLabel",
        font=("Microsoft YaHei UI", 12, "bold"),
        background=GUI_THEME["section_header"],
        foreground=GUI_THEME["text"],
    )
    style.configure("Subtitle.TLabel", font=("Microsoft YaHei UI", 10), foreground=GUI_THEME["muted"])
    style.configure("CardSubtitle.TLabel", font=("Microsoft YaHei UI", 9), background=GUI_THEME["panel_raised"], foreground=GUI_THEME["muted"])
    style.configure("Credit.TLabel", font=("Microsoft YaHei UI", 9), foreground=GUI_THEME["subtle"])
    style.configure("Status.TLabel", font=("Microsoft YaHei UI", 10), background=GUI_THEME["status_bg"], foreground=GUI_THEME["muted"])
    style.configure("ElasticMuted.TLabel", font=("Microsoft YaHei UI", 9), background=GUI_THEME["panel_raised"], foreground=GUI_THEME["muted"])
    style.configure("ElasticValid.TLabel", font=("Microsoft YaHei UI", 9), background=GUI_THEME["panel_raised"], foreground=GUI_THEME["success"])
    style.configure("ElasticWarning.TLabel", font=("Microsoft YaHei UI", 9), background=GUI_THEME["panel_raised"], foreground=GUI_THEME["warning"])
    style.configure("ElasticError.TLabel", font=("Microsoft YaHei UI", 9), background=GUI_THEME["panel_raised"], foreground=GUI_THEME["danger"])
    style.configure("TEntry", padding=(5, 4), fieldbackground=GUI_THEME["panel"], bordercolor=GUI_THEME["border"])
    style.map(
        "TEntry",
        bordercolor=[("focus", GUI_THEME["focus"]), ("!disabled", GUI_THEME["border"])],
        fieldbackground=[("disabled", GUI_THEME["panel_muted"]), ("!disabled", GUI_THEME["panel"])],
        foreground=[("disabled", GUI_THEME["subtle"]), ("!disabled", GUI_THEME["text"])],
    )
    style.configure("TCombobox", padding=(5, 4), fieldbackground=GUI_THEME["panel"], bordercolor=GUI_THEME["border"])
    style.map(
        "TCombobox",
        bordercolor=[("focus", GUI_THEME["focus"]), ("!disabled", GUI_THEME["border"])],
        fieldbackground=[("readonly", GUI_THEME["panel"])],
        selectbackground=[("readonly", GUI_THEME["panel"])],
        selectforeground=[("readonly", GUI_THEME["text"])],
    )
    style.configure("TCheckbutton", background=GUI_THEME["panel_raised"], foreground=GUI_THEME["text"], padding=(0, 2))
    style.map("TCheckbutton", foreground=[("disabled", GUI_THEME["subtle"]), ("!disabled", GUI_THEME["text"])])
    style.configure("Primary.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=(22, 12), foreground="#ffffff")
    style.map(
        "Primary.TButton",
        background=[
            ("disabled", GUI_THEME["border_strong"]),
            ("active", GUI_THEME["primary_active"]),
            ("!disabled", GUI_THEME["primary"]),
        ],
        foreground=[("disabled", GUI_THEME["panel_muted"]), ("!disabled", "#ffffff")],
    )
    style.configure("Action.TButton", padding=(10, 6), foreground=GUI_THEME["text"])
    style.map(
        "Action.TButton",
        background=[("active", GUI_THEME["panel_muted"]), ("!disabled", GUI_THEME["panel"])],
        foreground=[("disabled", GUI_THEME["subtle"]), ("active", GUI_THEME["primary"]), ("!disabled", GUI_THEME["text"])],
    )
    style.configure("Language.TButton", padding=(12, 6), foreground=GUI_THEME["muted"])
    style.map("Language.TButton", foreground=[("active", GUI_THEME["primary"]), ("!disabled", GUI_THEME["muted"])])
    style.configure(
        "Workbench.Treeview",
        rowheight=30,
        fieldbackground=GUI_THEME["panel"],
        background=GUI_THEME["panel"],
        foreground=GUI_THEME["text"],
        bordercolor=GUI_THEME["border"],
    )
    style.map(
        "Workbench.Treeview",
        background=[("selected", GUI_THEME["primary"])],
        foreground=[("selected", "#ffffff")],
    )
    style.configure(
        "Workbench.Treeview.Heading",
        font=("Microsoft YaHei UI", 10, "bold"),
        background=GUI_THEME["table_header"],
        foreground=GUI_THEME["text"],
        relief="flat",
        padding=(8, 7),
    )


def _configure_tcl_tk_environment(python_base: str | Path | None = None) -> None:
    base = Path(sys.base_prefix if python_base is None else python_base)
    tcl_dir = base / "tcl" / "tcl8.6"
    tk_dir = base / "tcl" / "tk8.6"

    current_tcl = Path(os.environ.get("TCL_LIBRARY", ""))
    current_tk = Path(os.environ.get("TK_LIBRARY", ""))
    if not (current_tcl / "init.tcl").exists() and (tcl_dir / "init.tcl").exists():
        os.environ["TCL_LIBRARY"] = str(tcl_dir)
    if not (current_tk / "tk.tcl").exists() and (tk_dir / "tk.tcl").exists():
        os.environ["TK_LIBRARY"] = str(tk_dir)


def _parse_float(value: str | float | int, field_name: str) -> float:
    try:
        number = float(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    return number


def _parse_optional_positive_float(value: str | float | int | None, field_name: str) -> float | None:
    if value is None or not str(value).strip():
        return None
    number = _parse_float(value, field_name)
    if number <= 0:
        raise ValueError(f"{field_name} must be greater than 0.")
    return number


def _two_theta_deg_for_d_spacing(d_spacing_A: float, wavelength_A: float) -> float | None:
    argument = wavelength_A / (2.0 * d_spacing_A)
    if argument > 1.0:
        if math.isclose(argument, 1.0, rel_tol=0.0, abs_tol=1e-12):
            argument = 1.0
        else:
            return None
    return math.degrees(2.0 * math.asin(argument))


def _apply_d_range_to_settings(
    settings: Cif2PeaksSettings,
    d_min_A: str | float | int | None,
    d_max_A: str | float | int | None,
) -> Cif2PeaksSettings:
    min_A = _parse_optional_positive_float(d_min_A, "d min")
    max_A = _parse_optional_positive_float(d_max_A, "d max")
    if min_A is not None and max_A is not None and min_A >= max_A:
        raise ValueError("d range must satisfy d_min < d_max.")

    half_wavelength = settings.wavelength_A / 2.0
    if max_A is not None and max_A < half_wavelength:
        raise ValueError("d range has no observable first-order Bragg peaks for this wavelength.")

    two_theta_min = 0.0
    if max_A is not None:
        converted_min = _two_theta_deg_for_d_spacing(max_A, settings.wavelength_A)
        if converted_min is None:
            raise ValueError("d range has no observable first-order Bragg peaks for this wavelength.")
        two_theta_min = converted_min

    if min_A is None or min_A < half_wavelength:
        two_theta_max = 180.0
    else:
        converted_max = _two_theta_deg_for_d_spacing(min_A, settings.wavelength_A)
        two_theta_max = 180.0 if converted_max is None else converted_max

    if two_theta_min >= two_theta_max:
        raise ValueError("d range has no observable first-order Bragg peaks for this wavelength.")

    settings.d_min_A = min_A
    settings.d_max_A = max_A
    settings.two_theta_min_deg = two_theta_min
    settings.two_theta_max_deg = two_theta_max
    return settings


def build_gui_settings(
    energy_keV: str | float,
    two_theta_min: str | float = 0.0,
    two_theta_max: str | float = 180.0,
) -> Cif2PeaksSettings:
    energy = _parse_float(energy_keV, "X-ray energy keV")
    min_deg = _parse_float(two_theta_min, "2theta min")
    max_deg = _parse_float(two_theta_max, "2theta max")
    if energy <= 0:
        raise ValueError("X-ray energy keV must be greater than 0.")
    if min_deg < 0 or max_deg > 180 or min_deg >= max_deg:
        raise ValueError("2theta range must satisfy 0 <= min < max <= 180.")
    return Cif2PeaksSettings(
        input_mode="energy",
        energy_keV=energy,
        wavelength_A=X_RAY_ENERGY_WAVELENGTH_KEV_A / energy,
        two_theta_min_deg=min_deg,
        two_theta_max_deg=max_deg,
    )


def build_beginner_gui_settings(
    two_theta_min: str | float = 0.0,
    two_theta_max: str | float = 180.0,
    energy_keV: str | float | None = None,
    xray_preset: str = "Cu Kα",
) -> Cif2PeaksSettings:
    if energy_keV is not None and str(energy_keV).strip():
        return build_gui_settings(energy_keV, two_theta_min, two_theta_max)

    min_deg = _parse_float(two_theta_min, "2theta min")
    max_deg = _parse_float(two_theta_max, "2theta max")
    if min_deg < 0 or max_deg > 180 or min_deg >= max_deg:
        raise ValueError("2theta range must satisfy 0 <= min < max <= 180.")
    if xray_preset not in GUI_XRAY_PRESETS:
        raise ValueError(f"Unknown X-ray preset: {xray_preset}")

    preset_energy = GUI_XRAY_PRESETS[xray_preset]
    if preset_energy is not None:
        return Cif2PeaksSettings(
            input_mode="energy",
            source_preset=xray_preset,
            energy_keV=preset_energy,
            wavelength_A=X_RAY_ENERGY_WAVELENGTH_KEV_A / preset_energy,
            two_theta_min_deg=min_deg,
            two_theta_max_deg=max_deg,
        )

    return Cif2PeaksSettings(
        input_mode="source",
        source_preset=DEFAULT_XRD_SOURCE,
        two_theta_min_deg=min_deg,
        two_theta_max_deg=max_deg,
    )


def build_beginner_gui_settings_from_d_range(
    d_min_A: str | float | None = None,
    d_max_A: str | float | None = None,
    energy_keV: str | float | None = None,
    xray_preset: str = GUI_XRAY_PRESET_LABELS[0],
) -> Cif2PeaksSettings:
    settings = build_beginner_gui_settings(0.0, 180.0, energy_keV, xray_preset)
    return _apply_d_range_to_settings(settings, d_min_A, d_max_A)


def normalize_xlsx_output_path(output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    return path


def planned_gui_output_paths(
    output_path: str | Path,
    selected_paths: Sequence[str | Path],
    *,
    display_names: Mapping[str | Path, str] | None = None,
    export_peaks: bool,
    export_patterns: bool,
    export_publication_figures: bool,
) -> list[Path]:
    output = normalize_xlsx_output_path(output_path)
    peak_output, pattern_output = export_output_paths(output, export_peaks=export_peaks, export_patterns=export_patterns)
    planned_paths = [path.resolve() for path in (peak_output, pattern_output) if path is not None]
    primary_output = peak_output or pattern_output
    if not export_publication_figures or primary_output is None:
        return planned_paths

    display_name_lookup = _resolved_display_name_lookup(display_names)
    for index, selected_path in enumerate(selected_paths, start=1):
        phase_name = _display_name_for_path(Path(selected_path), display_name_lookup)
        planned_paths.extend(
            _publication_figure_path(primary_output, phase_name, index, suffix).resolve()
            for suffix in (".svg", ".pdf", ".eps", ".png", ".tif")
        )
    return planned_paths


def split_drop_event_paths(drop_data: str, splitlist: Callable[[str], Sequence[str]]) -> list[str]:
    text = str(drop_data).strip()
    if not text:
        return []
    try:
        return [str(item) for item in splitlist(text) if str(item).strip()]
    except Exception:
        return [text]


def add_gui_cif_inputs(selected_paths: list[Path], inputs: Sequence[str | Path]) -> GuiCifInputUpdate:
    added_count = 0
    ignored_count = 0
    seen: set[Path] = set()
    for path in selected_paths:
        try:
            seen.add(Path(path).expanduser().resolve())
        except OSError:
            continue

    for item in inputs:
        candidate = Path(item).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError:
            ignored_count += 1
            continue

        if resolved.is_dir():
            candidates = sorted(
                (path for path in resolved.rglob("*") if path.is_file() and path.suffix.lower() == ".cif"),
                key=lambda value: str(value).lower(),
            )
        elif resolved.is_file() and resolved.suffix.lower() == ".cif":
            candidates = [resolved]
        else:
            candidates = []

        if not candidates:
            ignored_count += 1
            continue

        for path in candidates:
            resolved_path = path.resolve()
            if resolved_path in seen:
                ignored_count += 1
                continue
            selected_paths.append(resolved_path)
            seen.add(resolved_path)
            added_count += 1
    return GuiCifInputUpdate(added_count=added_count, ignored_count=ignored_count)


def initial_gui_cif_paths(inputs: Sequence[str | Path]) -> list[Path]:
    paths: list[Path] = []
    add_gui_cif_inputs(paths, inputs)
    return paths


def suggest_output_path(cif_paths: Sequence[str | Path]) -> Path:
    paths = [Path(path).expanduser() for path in cif_paths]
    if not paths:
        return Path.home() / "Desktop" / "CIF2Peaks峰表.xlsx"
    parent = paths[0].parent if paths[0].parent != Path("") else Path.cwd()
    if len(paths) == 1:
        return parent / f"{paths[0].stem}_CIF2Peaks峰表.xlsx"
    return parent / f"CIF2Peaks峰表_{len(paths)}个CIF.xlsx"


def next_gui_output_path(current_output: str | Path, cif_paths: Sequence[str | Path], user_customized: bool) -> Path:
    if user_customized and str(current_output).strip():
        return Path(current_output).expanduser()
    return suggest_output_path(cif_paths)


def _format_error_guidance(language: str, problem: str, cause: str, next_step: str) -> str:
    if language == "en":
        return f"Problem: {problem}\nLikely cause: {cause}\nNext step: {next_step}"
    return f"哪里出错：{problem}\n可能原因：{cause}\n下一步：{next_step}"


def friendly_error_message(exc: Exception, language: str = "zh") -> str:
    message = str(exc)
    lower = message.lower()
    language_key = language if language in SUPPORTED_GUI_LANGUAGES else "zh"
    if isinstance(exc, PermissionError):
        return _format_error_guidance(
            language_key,
            "无法写入结果文件。" if language_key == "zh" else "The result file could not be written.",
            "目标 Excel 可能被 Excel 打开，或当前文件夹没有写入权限。" if language_key == "zh" else "The target workbook may be open in Excel, or the folder may not be writable.",
            "请先关闭 Excel 中的同名文件，或换一个有写入权限的输出位置后重新导出。" if language_key == "zh" else "Close the workbook in Excel, or choose another writable output folder, then export again.",
        )
    if "select at least one cif" in lower:
        return _format_error_guidance(
            language_key,
            "还没有可导出的 CIF 文件。" if language_key == "zh" else "No CIF file has been selected for export.",
            "文件列表为空，导出流程没有输入结构。" if language_key == "zh" else "The file list is empty, so the export has no input structure.",
            "请先点击“添加文件”或“添加文件夹”，至少加入一个 CIF 后再导出。" if language_key == "zh" else "Use Add files or Add folder to add at least one CIF before exporting.",
        )
    if "must be a number" in lower:
        return _format_error_guidance(
            language_key,
            "某个参数不是有效数字。" if language_key == "zh" else "A parameter is not a valid number.",
            "输入框中可能包含空格以外的文字、单位符号或非法字符。" if language_key == "zh" else "The field may contain text, unit symbols, or invalid characters.",
            "请只填写数字；不确定时可以清空该项并使用默认设置。" if language_key == "zh" else "Enter numbers only; clear the field to use the default setting if unsure.",
        )
    if "x-ray energy kev must be greater than 0" in lower:
        return _format_error_guidance(
            language_key,
            "X 射线能量参数无效。" if language_key == "zh" else "The X-ray energy value is invalid.",
            "手动能量必须大于 0 keV。" if language_key == "zh" else "Manual energy must be greater than 0 keV.",
            "请填写正数；也可以留空，使用上方 X 射线预设。" if language_key == "zh" else "Enter a positive number, or leave it blank to use the selected X-ray preset.",
        )
    if "unknown x-ray preset" in lower:
        return _format_error_guidance(
            language_key,
            "X 射线预设不正确。" if language_key == "zh" else "The X-ray preset is not recognized.",
            "界面状态或输入值与内置预设列表不一致。" if language_key == "zh" else "The UI value does not match the built-in preset list.",
            "请选择 Cu Kα、30 keV 或 83 keV，或直接填写手动能量。" if language_key == "zh" else "Choose Cu Kalpha, 30 keV, or 83 keV, or enter a manual energy value.",
        )
    if "d range" in lower or "d min" in lower or "d max" in lower:
        return _format_error_guidance(
            language_key,
            "d 范围设置无效。" if language_key == "zh" else "The d-spacing range is invalid.",
            "d_min/d_max 需要是正数且 d_min < d_max；当前波长下也可能没有可观测一阶 Bragg 峰。" if language_key == "zh" else "d_min/d_max must be positive with d_min < d_max; the selected wavelength may also make the requested range unobservable.",
            "请修正 d 范围；不需要筛选时留空，若不可观测请增大 d_max 或调整 X 射线能量。" if language_key == "zh" else "Fix the d range; leave it blank for no filter, or increase d_max/change the X-ray energy if no peak is observable.",
        )
    if "2theta range" in lower:
        return _format_error_guidance(
            language_key,
            "2θ 范围设置无效。" if language_key == "zh" else "The 2theta range is invalid.",
            "范围边界必须满足 0 <= 最小值 < 最大值 <= 180。" if language_key == "zh" else "The range must satisfy 0 <= minimum < maximum <= 180.",
            "请检查 2θ 最小值和最大值，或恢复默认范围。" if language_key == "zh" else "Check the 2theta minimum/maximum values, or restore the default range.",
        )
    if isinstance(exc, FileNotFoundError) or "missing cif" in lower:
        return _format_error_guidance(
            language_key,
            "找不到某些 CIF 文件。" if language_key == "zh" else "Some CIF files could not be found.",
            "文件可能被移动、重命名、删除，或外部磁盘/网络路径不可用。" if language_key == "zh" else "The file may have been moved, renamed, deleted, or the drive/network path may be unavailable.",
            "请重新选择文件或文件夹，然后再次导出。" if language_key == "zh" else "Select the files or folder again, then retry the export.",
        )
    return _format_error_guidance(
        language_key,
        "处理失败。" if language_key == "zh" else "Processing failed.",
        message or ("未知错误。" if language_key == "zh" else "Unknown error."),
        "请检查输入文件、输出路径和参数；如果仍失败，请保留错误信息用于排查。" if language_key == "zh" else "Check the input files, output path, and parameters; keep this error message if it still fails.",
    )


def preview_simple_gui_inputs(
    cif_paths: Sequence[str | Path],
    display_names: Mapping[str | Path, str] | None = None,
    language: str = "zh",
    *,
    elastic_constants: Mapping[str | Path, ElasticConstants] | None = None,
) -> SimpleGuiPreviewResult:
    resolved_cifs = initial_gui_cif_paths(cif_paths)
    service = Cif2PeaksService()
    phases = service.load_phases(resolved_cifs)
    _apply_display_names_to_phases(phases, display_names)
    _apply_elastic_constants_to_phases(phases, elastic_constants)

    phase_rows: list[tuple[str, str, str, str, str, str]] = []
    ready_count = 0
    failed_count = 0
    for phase in phases:
        if phase.error:
            status = _gui_text(language, "preview_failed")
            failed_count += 1
        else:
            status = _gui_text(language, "preview_pending")
            ready_count += 1
        phase_rows.append(
            (
                phase.phase_name,
                phase.display_formula,
                phase.display_space_group,
                status,
                friendly_cif_issue_message(phase.error, phase.warning_messages),
                _phase_elastic_status_text(phase),
            )
        )

    return SimpleGuiPreviewResult(
        ready_count=ready_count,
        failed_count=failed_count,
        phase_rows=phase_rows,
    )


def run_simple_gui_export(
    cif_paths: Sequence[str | Path],
    output_path: str | Path,
    *,
    energy_keV: str | float | None = None,
    xray_preset: str = "Cu Kα",
    two_theta_min: str | float = 0.0,
    two_theta_max: str | float = 180.0,
    d_min_A: str | float | None = None,
    d_max_A: str | float | None = None,
    display_names: Mapping[str | Path, str] | None = None,
    elastic_constants: Mapping[str | Path, ElasticConstants] | None = None,
    export_peaks: bool = True,
    export_patterns: bool = False,
    pattern_axis: XrdAxisMode = "two_theta",
    export_publication_svg: bool = False,
    publication_preset: str = "publication",
) -> SimpleGuiExportResult:
    if not export_peaks and not export_patterns:
        raise ValueError("At least one export type must be enabled.")
    resolved_cifs = [Path(path).expanduser().resolve() for path in cif_paths]
    if not resolved_cifs:
        raise ValueError("Select at least one CIF file.")
    missing = [str(path) for path in resolved_cifs if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing CIF file(s): " + "; ".join(missing))

    if d_min_A is not None or d_max_A is not None:
        settings = build_beginner_gui_settings_from_d_range(d_min_A, d_max_A, energy_keV, xray_preset)
    else:
        settings = build_beginner_gui_settings(two_theta_min, two_theta_max, energy_keV, xray_preset)
    service = Cif2PeaksService()
    phases = service.load_phases(resolved_cifs)
    _apply_display_names_to_phases(phases, display_names)
    _apply_elastic_constants_to_phases(phases, elastic_constants)
    service.simulate_phases(phases, settings)

    output = normalize_xlsx_output_path(output_path)
    peak_output, pattern_output = export_output_paths(output, export_peaks=export_peaks, export_patterns=export_patterns)
    payload = Cif2PeaksExportPayload(phases, settings)
    if peak_output is not None:
        peak_output.parent.mkdir(parents=True, exist_ok=True)
        export_cif2peaks_workbook(payload, peak_output)
    if pattern_output is not None:
        pattern_output.parent.mkdir(parents=True, exist_ok=True)
        export_cif2peaks_pattern_workbook(payload, pattern_output, axis_mode=pattern_axis)
    primary_output = peak_output or pattern_output
    if primary_output is None:
        raise ValueError("At least one export type must be enabled.")
    publication_figure_paths: list[Path] = []
    if export_publication_svg:
        for index, phase in enumerate(phases, start=1):
            if phase.result is None:
                continue
            svg_path = _publication_figure_path(primary_output, phase.phase_name, index, ".svg")
            pdf_path = _publication_figure_path(primary_output, phase.phase_name, index, ".pdf")
            eps_path = _publication_figure_path(primary_output, phase.phase_name, index, ".eps")
            png_path = _publication_figure_path(primary_output, phase.phase_name, index, ".png")
            tiff_path = _publication_figure_path(primary_output, phase.phase_name, index, ".tif")
            export_xrd_pattern_svg(phase.result, svg_path, title=phase.phase_name, preset_name=publication_preset)
            export_xrd_pattern_pdf(phase.result, pdf_path, title=phase.phase_name, preset_name=publication_preset)
            export_xrd_pattern_eps(phase.result, eps_path, title=phase.phase_name, preset_name=publication_preset)
            export_xrd_pattern_png(phase.result, png_path, title=phase.phase_name, preset_name=publication_preset)
            export_xrd_pattern_tiff(phase.result, tiff_path, title=phase.phase_name, preset_name=publication_preset)
            publication_figure_paths.extend([svg_path, pdf_path, eps_path, png_path, tiff_path])

    phase_rows: list[tuple[str, str, str, int, str, str]] = []
    phase_error_flags: list[bool] = []
    for phase in phases:
        peak_count = 0 if phase.result is None else len(phase.result.peaks)
        phase_rows.append(
            (
                phase.phase_name,
                phase.display_formula,
                phase.display_space_group,
                peak_count,
                friendly_cif_issue_message(phase.error, phase.warning_messages),
                _phase_elastic_status_text(phase),
            )
        )
        phase_error_flags.append(bool(phase.error))
    return SimpleGuiExportResult(
        output_path=primary_output,
        total_peaks=sum(row[3] for row in phase_rows),
        phase_rows=phase_rows,
        phase_error_flags=phase_error_flags,
        peak_output_path=peak_output,
        pattern_output_path=pattern_output,
        publication_figure_paths=publication_figure_paths,
    )


def _phase_row_is_failed(row: tuple[str, str, str, int, str, str]) -> bool:
    _phase_name, formula, space_group, peak_count, warning, _elastic = row
    return peak_count == 0 and bool(str(warning).strip()) and str(formula).strip() == "-" and str(space_group).strip() == "-"


def summarize_gui_export_result(result: SimpleGuiExportResult) -> GuiExportDiagnostics:
    failed_count = 0
    warning_count = 0
    zero_peak_count = 0
    explicit_error_flags = result.phase_error_flags if len(result.phase_error_flags) == len(result.phase_rows) else None
    for index, row in enumerate(result.phase_rows):
        _phase_name, _formula, _space_group, peak_count, warning, _elastic = row
        failed = explicit_error_flags[index] if explicit_error_flags is not None else _phase_row_is_failed(row)
        if failed:
            failed_count += 1
        elif str(warning).strip():
            warning_count += 1
        if peak_count == 0 and not failed:
            zero_peak_count += 1
    total_phases = len(result.phase_rows)
    return GuiExportDiagnostics(
        total_phases=total_phases,
        ready_count=total_phases - failed_count,
        failed_count=failed_count,
        warning_count=warning_count,
        zero_peak_count=zero_peak_count,
    )


def _diagnostic_status_line(summary: GuiExportDiagnostics, language: str) -> str:
    if language == "en":
        return (
            f"Phase status: {summary.ready_count} usable/reviewable, "
            f"{summary.failed_count} failed, {summary.warning_count} with warnings, "
            f"{summary.zero_peak_count} with zero peaks."
        )
    return (
        f"相状态：可用/待检查 {summary.ready_count} 个，失败 {summary.failed_count} 个，"
        f"含警告 {summary.warning_count} 个，零峰 {summary.zero_peak_count} 个。"
    )


def simple_export_message_lines(result: SimpleGuiExportResult, language: str = "zh") -> list[str]:
    summary = summarize_gui_export_result(result)
    if result.total_peaks:
        if language == "en":
            summary_lines = [
                f"Exported {result.total_peaks} peak record(s).",
                _diagnostic_status_line(summary, language),
                _gui_text(language, "result_next_step"),
            ]
        else:
            summary_lines = [
                f"已导出 {result.total_peaks} 条峰记录。",
                _diagnostic_status_line(summary, language),
                _gui_text(language, "result_next_step"),
            ]
    elif language == "en":
        summary_lines = [
            "No usable peak records were produced, but a diagnostic Excel workbook was generated.",
            _diagnostic_status_line(summary, language),
            "Open Summary and User Guide to inspect CIF issues.",
        ]
    else:
        summary_lines = [
            "未得到可用峰记录，但已生成诊断 Excel。",
            _diagnostic_status_line(summary, language),
            "请先打开 Summary 和 使用说明 查看 CIF 问题。",
        ]
    output_lines = [*summary_lines, "", str(result.output_path)]
    if result.pattern_output_path is not None and result.pattern_output_path != result.output_path:
        output_lines.append(str(result.pattern_output_path))
    if result.publication_figure_paths:
        output_lines.append("")
        output_lines.append("Publication figure(s):" if language == "en" else "论文级图：")
        output_lines.extend(str(path) for path in result.publication_figure_paths)
    return output_lines


def gui_export_completion_text(result: SimpleGuiExportResult, language: str = "zh") -> tuple[str, str]:
    summary = summarize_gui_export_result(result)
    if result.total_peaks:
        status_text = (
            f"Done: exported {result.total_peaks} peak record(s); {summary.failed_count} failed, {summary.warning_count} warning(s)."
            if language == "en"
            else f"完成：已导出 {result.total_peaks} 条峰记录；失败 {summary.failed_count} 个，警告 {summary.warning_count} 个。"
        )
    elif language == "en":
        status_text = f"Done: generated a diagnostic Excel workbook; {summary.failed_count} failed, no usable peak records."
    else:
        status_text = f"完成：已生成诊断 Excel；失败 {summary.failed_count} 个，未得到可用峰记录。"
    return status_text, "\n".join(simple_export_message_lines(result, language))


def open_export_result(output_path: str | Path, opener: Callable[[str], object] | None = None) -> Path:
    path = Path(output_path)
    open_target = os.startfile if opener is None else opener  # type: ignore[attr-defined]
    try:
        open_target(str(path))
        return path
    except OSError:
        open_target(str(path.parent))
        return path.parent


class _GuiTooltip:
    def __init__(self, widget: object, text_factory: Callable[[], str], tk_module: object, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text_factory = text_factory
        self.tk = tk_module
        self.delay_ms = delay_ms
        self._after_id: object | None = None
        self._tip: object | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event: object | None = None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id is None:
            return
        self.widget.after_cancel(self._after_id)
        self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self._tip is not None:
            return
        text = self.text_factory()
        if not text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip = self.tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        label = self.tk.Label(
            tip,
            text=text,
            justify="left",
            background="#fffff4",
            foreground=GUI_THEME["text"],
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=5,
            wraplength=320,
        )
        label.pack()
        self._tip = tip

    def _hide(self, _event: object | None = None) -> None:
        self._cancel()
        if self._tip is None:
            return
        self._tip.destroy()
        self._tip = None


def _launch_tk_app(initial_paths: Sequence[str | Path] = ()) -> None:
    import threading

    _configure_tcl_tk_environment()
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD

        root = TkinterDnD.Tk()
        dnd_available = True
    except Exception:
        DND_FILES = ""
        root = tk.Tk()
        dnd_available = False
    if os.environ.get("CIF2PEAKS_SMOKE_TEST") == "1":
        root.after(300, root.destroy)
    root.geometry(GUI_WORKBENCH_LAYOUT["geometry"])
    root.minsize(*GUI_WORKBENCH_LAYOUT["minsize"])

    style = ttk.Style(root)
    _configure_workbench_theme(root, style)

    selected_paths: list[Path] = initial_gui_cif_paths(initial_paths)
    display_names: dict[Path, str] = {path: path.name for path in selected_paths}
    elastic_constants: dict[Path, ElasticConstants] = {}
    last_output_path: Path | None = None
    preview_generation = 0
    output_path_user_customized = False
    export_is_busy = False
    language_var = tk.StringVar(value="zh")
    display_name_var = tk.StringVar(value="")
    elastic_cubic_var = tk.StringVar(value="")
    elastic_source_var = tk.StringVar(value="")
    elastic_status_var = tk.StringVar(value="")
    xray_preset_var = tk.StringVar(value=GUI_XRAY_PRESET_LABELS[0])
    energy_var = tk.StringVar(value="")
    min_var = tk.StringVar(value="")
    max_var = tk.StringVar(value="")
    export_peaks_var = tk.BooleanVar(value=True)
    export_patterns_var = tk.BooleanVar(value=False)
    pattern_axis_var = tk.StringVar(value="two_theta")
    publication_svg_var = tk.BooleanVar(value=False)
    publication_preset_var = tk.StringVar(value="publication")
    output_var = tk.StringVar(value=str(suggest_output_path(selected_paths)))
    lang = language_var.get
    status_var = tk.StringVar(
        value=_gui_text(lang(), "ready_to_export")
        if selected_paths
        else _gui_text(lang(), "ready_to_add")
    )
    input_summary_var = tk.StringVar(
        value=_gui_text(lang(), "no_cif")
        if not selected_paths
        else _gui_text(lang(), "cif_count", count=len(selected_paths))
    )
    drop_hint_var = tk.StringVar(
        value=_gui_text(lang(), "drop_hint_available")
        if dnd_available
        else _gui_text(lang(), "drop_hint_unavailable")
    )
    settings_summary_var = tk.StringVar()
    activity_log_lines: list[str] = []
    tooltips: list[_GuiTooltip] = []

    def attach_tooltip(widget: object, role: str) -> None:
        tooltip_key = GUI_TOOLTIP_KEYS[role]
        tooltips.append(_GuiTooltip(widget, lambda key=tooltip_key: _gui_text(lang(), key), tk))

    def append_activity(message: str) -> None:
        if not message:
            return
        activity_log_lines.append(message)
        if len(activity_log_lines) > 100:
            del activity_log_lines[:-100]
        activity_listbox.delete(0, tk.END)
        for line in activity_log_lines:
            activity_listbox.insert(tk.END, line)
        activity_listbox.yview_moveto(1.0)

    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)

    header = ttk.Frame(root, padding=(24, 18, 24, 10), style="Header.TFrame")
    header.grid(row=0, column=0, sticky="ew")
    header.columnconfigure(0, weight=1)
    workspace_label = ttk.Label(header, style="Credit.TLabel")
    workspace_label.grid(row=0, column=0, sticky="w")
    title_label = ttk.Label(header, style="Title.TLabel")
    title_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
    language_button = ttk.Button(header, style="Language.TButton")
    language_button.grid(row=1, column=1, sticky="e")
    subtitle_label = ttk.Label(header, style="Subtitle.TLabel")
    subtitle_label.grid(
        row=2,
        column=0,
        sticky="w",
        pady=(4, 0),
    )
    credit_label = ttk.Label(header, style="Credit.TLabel")
    credit_label.grid(row=3, column=0, sticky="w", pady=(6, 0))

    main_container = ttk.Frame(root, style="Workbench.TFrame")
    main_container.grid(row=1, column=0, sticky="nsew")
    main_container.columnconfigure(0, weight=1)
    main_container.rowconfigure(0, weight=1)
    main_canvas = tk.Canvas(
        main_container,
        bd=0,
        highlightthickness=0,
        background=GUI_THEME["surface"],
    )
    main_canvas.grid(row=0, column=0, sticky="nsew")
    main_scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=main_canvas.yview)
    main_scrollbar.grid(row=0, column=1, sticky="ns")
    main_canvas.configure(yscrollcommand=main_scrollbar.set)
    main = ttk.Frame(main_canvas, padding=(24, 10, 24, 12), style="Workbench.TFrame")
    main_window = main_canvas.create_window((0, 0), window=main, anchor="nw")

    def sync_main_scroll_region(_event: object | None = None) -> None:
        main_canvas.configure(scrollregion=main_canvas.bbox("all"))

    def sync_main_width(event: object) -> None:
        main_canvas.itemconfigure(main_window, width=getattr(event, "width", 0))

    def scroll_main(event: object) -> None:
        delta = getattr(event, "delta", 0)
        if not delta:
            return
        main_canvas.yview_scroll(int(-1 * (delta / 120)), "units")

    main.bind("<Configure>", sync_main_scroll_region)
    main_canvas.bind("<Configure>", sync_main_width)
    main_canvas.bind_all("<MouseWheel>", scroll_main, add="+")
    main.columnconfigure(0, weight=0, minsize=GUI_WORKBENCH_LAYOUT["sidebar_width"])
    main.columnconfigure(1, weight=1)
    main.rowconfigure(0, weight=0)
    main.rowconfigure(1, weight=1)

    def make_section_header(parent: object, accent_style: str) -> tuple[object, object]:
        header = ttk.Frame(parent, style="SectionHeader.TFrame", padding=(10, 6, 10, 6))
        header.columnconfigure(1, weight=1)
        accent_strip = ttk.Frame(header, width=5, style=accent_style)
        accent_strip.grid(row=0, column=0, sticky="ns", padx=(0, 10), pady=(2, 2))
        accent_strip.grid_propagate(False)
        title = ttk.Label(header, style="SectionTitle.TLabel")
        title.grid(row=0, column=1, sticky="w")
        return header, title

    files_panel = ttk.Frame(main, padding=16, style="Card.TFrame")
    files_panel.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 14))
    files_panel.columnconfigure(0, weight=1)
    files_panel.rowconfigure(6, weight=1)

    files_panel_header, files_panel_title = make_section_header(files_panel, "DataAccent.TFrame")
    files_panel_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

    file_buttons = ttk.Frame(files_panel, style="Toolbar.TFrame")
    file_buttons.grid(row=1, column=0, sticky="ew", pady=(0, 10))
    file_buttons.columnconfigure(3, weight=1)

    ttk.Label(files_panel, textvariable=input_summary_var, style="Card.TLabel").grid(row=2, column=0, sticky="w")
    ttk.Label(files_panel, textvariable=drop_hint_var, style="CardSubtitle.TLabel").grid(row=3, column=0, sticky="w", pady=(2, 10))

    display_name_frame = ttk.Frame(files_panel, style="CardBody.TFrame")
    display_name_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    display_name_frame.columnconfigure(1, weight=1)
    display_name_label = ttk.Label(display_name_frame, style="Card.TLabel")
    display_name_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
    display_name_entry = ttk.Entry(display_name_frame, textvariable=display_name_var)
    display_name_entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))
    apply_name_button = ttk.Button(display_name_frame, style="Action.TButton")
    apply_name_button.grid(row=0, column=2, padx=(0, 6))
    reset_name_button = ttk.Button(display_name_frame, style="Action.TButton")
    reset_name_button.grid(row=0, column=3)

    elastic_frame = ttk.Frame(files_panel, style="CardBody.TFrame")
    elastic_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    elastic_frame.columnconfigure(0, weight=1)
    elastic_label = ttk.Label(elastic_frame, style="Card.TLabel")
    elastic_label.grid(row=0, column=0, sticky="w")
    elastic_cubic_label = ttk.Label(elastic_frame, style="CardSubtitle.TLabel")
    elastic_cubic_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
    elastic_quick_frame = ttk.Frame(elastic_frame, style="CardBody.TFrame")
    elastic_quick_frame.grid(row=2, column=0, sticky="ew", pady=(4, 0))
    elastic_quick_frame.columnconfigure(0, weight=1)
    elastic_entry = ttk.Entry(elastic_quick_frame, textvariable=elastic_cubic_var)
    elastic_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    fill_cubic_button = ttk.Button(elastic_quick_frame, style="Action.TButton")
    fill_cubic_button.grid(row=0, column=1)
    elastic_matrix_label = ttk.Label(elastic_frame, style="Card.TLabel")
    elastic_matrix_label.grid(row=3, column=0, sticky="w", pady=(6, 0))
    elastic_cell_vars = [[tk.StringVar(value="") for _column in range(CIJ_TABLE_SIZE)] for _row in range(CIJ_TABLE_SIZE)]
    elastic_cell_entries: list[list[object]] = []
    elastic_grid_frame = ttk.Frame(elastic_frame, style="CardBody.TFrame")
    elastic_grid_frame.grid(row=4, column=0, sticky="ew", pady=(4, 0))
    for column in range(CIJ_TABLE_SIZE + 1):
        elastic_grid_frame.columnconfigure(column, weight=0)
    ttk.Label(elastic_grid_frame, text="", style="CardSubtitle.TLabel", width=3).grid(row=0, column=0)
    for column in range(CIJ_TABLE_SIZE):
        ttk.Label(elastic_grid_frame, text=str(column + 1), style="CardSubtitle.TLabel", width=5, anchor="center").grid(
            row=0,
            column=column + 1,
            padx=1,
            pady=(0, 2),
        )
    for row in range(CIJ_TABLE_SIZE):
        ttk.Label(elastic_grid_frame, text=str(row + 1), style="CardSubtitle.TLabel", width=3, anchor="center").grid(
            row=row + 1,
            column=0,
            padx=(0, 2),
        )
        entry_row: list[object] = []
        for column in range(CIJ_TABLE_SIZE):
            cell_entry = ttk.Entry(
                elastic_grid_frame,
                textvariable=elastic_cell_vars[row][column],
                width=5,
                justify="center",
            )
            cell_entry.grid(row=row + 1, column=column + 1, padx=1, pady=1)
            entry_row.append(cell_entry)
        elastic_cell_entries.append(entry_row)
    elastic_matrix_buttons = ttk.Frame(elastic_frame, style="CardBody.TFrame")
    elastic_matrix_buttons.grid(row=5, column=0, sticky="ew", pady=(6, 0))
    paste_elastic_button = ttk.Button(elastic_matrix_buttons, style="Action.TButton")
    paste_elastic_button.grid(row=0, column=0, padx=(0, 6))
    copy_elastic_button = ttk.Button(elastic_matrix_buttons, style="Action.TButton")
    copy_elastic_button.grid(row=0, column=1)
    elastic_source_frame = ttk.Frame(elastic_frame, style="CardBody.TFrame")
    elastic_source_frame.grid(row=6, column=0, sticky="ew", pady=(6, 0))
    elastic_source_frame.columnconfigure(1, weight=1)
    elastic_source_label = ttk.Label(elastic_source_frame, style="Card.TLabel")
    elastic_source_label.grid(row=0, column=0, sticky="w", padx=(0, 6))
    elastic_source_entry = ttk.Entry(elastic_source_frame, textvariable=elastic_source_var)
    elastic_source_entry.grid(row=0, column=1, sticky="ew")
    elastic_status_label = ttk.Label(elastic_frame, textvariable=elastic_status_var, style="ElasticMuted.TLabel", wraplength=300)
    elastic_status_label.grid(row=7, column=0, sticky="ew", pady=(6, 0))
    elastic_action_frame = ttk.Frame(elastic_frame, style="CardBody.TFrame")
    elastic_action_frame.grid(row=8, column=0, sticky="ew", pady=(6, 0))
    apply_elastic_button = ttk.Button(elastic_action_frame, style="Action.TButton")
    apply_elastic_button.grid(row=0, column=0, padx=(0, 6))
    clear_elastic_button = ttk.Button(elastic_action_frame, style="Action.TButton")
    clear_elastic_button.grid(row=0, column=1)

    listbox = tk.Listbox(
        files_panel,
        height=16,
        selectmode=tk.EXTENDED,
        bd=0,
        highlightthickness=1,
        highlightbackground=GUI_THEME["border"],
        highlightcolor=GUI_THEME["focus"],
        bg=GUI_THEME["panel_muted"],
        fg=GUI_THEME["text"],
        selectbackground=GUI_THEME["primary"],
        selectforeground="#ffffff",
        activestyle="none",
    )
    listbox.grid(row=6, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(files_panel, orient="vertical", command=listbox.yview)
    scrollbar.grid(row=6, column=1, sticky="ns")
    listbox.configure(yscrollcommand=scrollbar.set)

    def set_file_action_states() -> None:
        has_files = bool(selected_paths)
        has_selection = bool(listbox.curselection())
        selection_state = tk.NORMAL if has_selection else tk.DISABLED
        remove_button.configure(state=selection_state)
        apply_name_button.configure(state=selection_state)
        reset_name_button.configure(state=selection_state)
        display_name_entry.configure(state=selection_state)
        elastic_entry.configure(state=selection_state)
        for entry_row in elastic_cell_entries:
            for cell_entry in entry_row:
                cell_entry.configure(state=selection_state)
        elastic_source_entry.configure(state=selection_state)
        fill_cubic_button.configure(state=selection_state)
        paste_elastic_button.configure(state=selection_state)
        copy_elastic_button.configure(state=selection_state)
        apply_elastic_button.configure(state=selection_state)
        clear_elastic_button.configure(state=selection_state)
        clear_button.configure(state=tk.NORMAL if has_files else tk.DISABLED)

    def refresh_list() -> None:
        listbox.delete(0, tk.END)
        for path in selected_paths:
            display_name = display_names.get(path, path.name).strip() or path.name
            elastic_suffix = " [Cij]" if path in elastic_constants else ""
            label = display_name if display_name == path.name else f"{display_name}  ({path.name})"
            label = f"{label}{elastic_suffix}"
            listbox.insert(tk.END, label)
        count = len(selected_paths)
        input_summary_var.set(_gui_text(lang(), "no_cif") if count == 0 else _gui_text(lang(), "cif_count", count=count))
        output_var.set(str(next_gui_output_path(output_var.get(), selected_paths, output_path_user_customized)))
        status_var.set(_gui_text(lang(), "ready_to_export") if selected_paths else _gui_text(lang(), "ready_to_add"))
        refresh_export_control_states(update_status=True)
        sync_display_name_entry()
        set_file_action_states()
        schedule_preview()

    def add_inputs(inputs: Sequence[str | Path], source_label: str) -> GuiCifInputUpdate:
        before = set(selected_paths)
        update = add_gui_cif_inputs(selected_paths, inputs)
        auto_elastic_n = 0
        for path in selected_paths:
            display_names.setdefault(path, path.name)
            # Auto-load PhaseScout sidecars for newly added CIFs only; do not override manual Cij.
            if path not in before and path not in elastic_constants:
                elastic = load_elastic_for_cif(path)
                if elastic is not None:
                    elastic_constants[path] = elastic
                    auto_elastic_n += 1
        refresh_list()
        if update.added_count:
            suffix = _gui_text(lang(), "ignored_suffix", ignored=update.ignored_count) if update.ignored_count else ""
            status_var.set(_gui_text(lang(), "add_source", source=source_label, added=update.added_count, suffix=suffix))
            append_activity(_gui_text(lang(), "log_added", source=source_label, added=update.added_count, suffix=suffix))
            if auto_elastic_n:
                msg = _gui_text(lang(), "elastic_auto_loaded", count=auto_elastic_n)
                append_activity(msg)
                status_var.set(msg)
        elif update.ignored_count:
            status_var.set(_gui_text(lang(), "add_source_none", source=source_label, ignored=update.ignored_count))
            append_activity(_gui_text(lang(), "log_add_none", source=source_label, ignored=update.ignored_count))
        return update

    def add_files() -> None:
        paths = filedialog.askopenfilenames(title=_gui_text(lang(), "choose_cif_title"), filetypes=[("CIF files", "*.cif")])
        if paths:
            add_inputs(paths, _gui_text(lang(), "source_add_files"))

    def add_folder() -> None:
        folder = filedialog.askdirectory(title=_gui_text(lang(), "choose_folder_title"))
        if not folder:
            return
        add_inputs([folder], _gui_text(lang(), "source_add_folder"))

    def clear_files() -> None:
        if not should_clear_gui_files(
            len(selected_paths),
            lambda: messagebox.askyesno(_gui_text(lang(), "confirm_clear_title"), _gui_text(lang(), "confirm_clear_message")),
        ):
            return
        selected_paths.clear()
        display_names.clear()
        elastic_constants.clear()
        display_name_var.set("")
        elastic_cubic_var.set("")
        elastic_source_var.set("")
        clear_cij_table_values()
        set_elastic_status_feedback(None)
        tree.delete(*tree.get_children())
        refresh_list()
        append_activity(_gui_text(lang(), "log_cleared"))

    def remove_selected() -> None:
        selected = set(listbox.curselection())
        if not selected:
            return
        for index, path in enumerate(selected_paths):
            if index in selected:
                display_names.pop(path, None)
                elastic_constants.pop(path, None)
        selected_paths[:] = [path for index, path in enumerate(selected_paths) if index not in selected]
        refresh_list()

    def selected_display_path() -> Path | None:
        selection = listbox.curselection()
        if not selection:
            return None
        index = int(selection[0])
        if index < 0 or index >= len(selected_paths):
            return None
        return selected_paths[index]

    def current_cij_table_values() -> list[list[str]]:
        return [[elastic_cell_vars[row][column].get() for column in range(CIJ_TABLE_SIZE)] for row in range(CIJ_TABLE_SIZE)]

    def set_cij_table_values(values: Sequence[Sequence[object]]) -> None:
        rows = [list(row) for row in values]
        for row in range(CIJ_TABLE_SIZE):
            for column in range(CIJ_TABLE_SIZE):
                value = "" if row >= len(rows) or column >= len(rows[row]) else str(rows[row][column])
                elastic_cell_vars[row][column].set(value)

    def clear_cij_table_values() -> None:
        set_cij_table_values(_blank_cij_table_values())

    def cij_table_has_any_value() -> bool:
        return any(cell.strip() for row in current_cij_table_values() for cell in row)

    def set_elastic_status_message(message: str, style_name: str = "ElasticMuted.TLabel") -> None:
        elastic_status_var.set(message)
        elastic_status_label.configure(style=style_name)

    def set_elastic_status_feedback(elastic: ElasticConstants | None) -> None:
        set_elastic_status_message(_elastic_status_feedback(elastic, lang()), _elastic_status_style_name(elastic))

    def mark_cij_table_dirty(_event: object | None = None) -> None:
        if selected_display_path() is not None:
            set_elastic_status_message(_gui_text(lang(), "elastic_status_ready_to_apply"), "ElasticWarning.TLabel")

    def sync_display_name_entry() -> None:
        path = selected_display_path()
        display_name_var.set("" if path is None else display_names.get(path, path.name))
        elastic = None if path is None else elastic_constants.get(path)
        cubic_summary = _elastic_cubic_summary(elastic)
        elastic_cubic_var.set(cubic_summary)
        set_cij_table_values(_format_cij_table_values(elastic))
        elastic_source_var.set("" if elastic is None else elastic.source)
        set_elastic_status_feedback(elastic)
        set_file_action_states()

    def apply_display_name() -> None:
        path = selected_display_path()
        if path is None:
            return
        display_names[path] = display_name_var.get().strip() or path.name
        refresh_list()

    def reset_display_name() -> None:
        path = selected_display_path()
        if path is None:
            return
        display_names[path] = path.name
        refresh_list()

    def fill_cubic_cij_table() -> str | None:
        try:
            set_cij_table_values(_cubic_cij_table_values(elastic_cubic_var.get()))
        except Exception as exc:
            set_elastic_status_message(
                _gui_text(lang(), "elastic_status_input_error", warning=str(exc)),
                "ElasticError.TLabel",
            )
            messagebox.showerror(_gui_text(lang(), "elastic_apply_failed_title"), str(exc))
            return "break"
        set_elastic_status_message(_gui_text(lang(), "elastic_status_ready_to_apply"), "ElasticWarning.TLabel")
        return "break"

    def paste_elastic_matrix() -> str | None:
        try:
            clipboard_text = root.clipboard_get()
            values = _parse_cij_paste_matrix(str(clipboard_text))
        except Exception as exc:
            set_elastic_status_message(
                _gui_text(lang(), "elastic_status_input_error", warning=str(exc)),
                "ElasticError.TLabel",
            )
            messagebox.showerror(_gui_text(lang(), "elastic_paste_failed_title"), str(exc))
            return "break"
        set_cij_table_values(values)
        set_elastic_status_message(_gui_text(lang(), "elastic_status_ready_to_apply"), "ElasticWarning.TLabel")
        return "break"

    def paste_elastic_matrix_from_cell(_event: object | None = None) -> str | None:
        try:
            clipboard_text = root.clipboard_get()
            values = _parse_cij_paste_matrix(str(clipboard_text))
        except Exception:
            return None
        set_cij_table_values(values)
        set_elastic_status_message(_gui_text(lang(), "elastic_status_ready_to_apply"), "ElasticWarning.TLabel")
        return "break"

    def copy_elastic_matrix() -> None:
        text = "\n".join("\t".join(row) for row in current_cij_table_values())
        root.clipboard_clear()
        root.clipboard_append(text)
        set_elastic_status_message(_gui_text(lang(), "elastic_copied"), "ElasticMuted.TLabel")

    def apply_elastic_constants() -> None:
        path = selected_display_path()
        if path is None:
            return
        try:
            if not cij_table_has_any_value() and elastic_cubic_var.get().strip():
                set_cij_table_values(_cubic_cij_table_values(elastic_cubic_var.get()))
            elastic = _parse_cij_table_values(current_cij_table_values(), elastic_source_var.get())
            elastic_constants[path] = elastic
            set_elastic_status_feedback(elastic)
        except Exception as exc:
            set_elastic_status_message(
                _gui_text(lang(), "elastic_status_input_error", warning=str(exc)),
                "ElasticError.TLabel",
            )
            messagebox.showerror(_gui_text(lang(), "elastic_apply_failed_title"), str(exc))
            return
        refresh_list()

    def clear_elastic_constants() -> None:
        path = selected_display_path()
        if path is None:
            return
        elastic_constants.pop(path, None)
        elastic_cubic_var.set("")
        clear_cij_table_values()
        elastic_source_var.set("")
        set_elastic_status_feedback(None)
        refresh_list()

    listbox.bind("<<ListboxSelect>>", lambda _event: sync_display_name_entry())
    listbox.bind("<Double-Button-1>", lambda _event: display_name_entry.focus_set())
    display_name_entry.bind("<Return>", lambda _event: apply_display_name())
    elastic_entry.bind("<Return>", lambda _event: fill_cubic_cij_table())
    for entry_row in elastic_cell_entries:
        for cell_entry in entry_row:
            cell_entry.bind("<<Paste>>", paste_elastic_matrix_from_cell)
            cell_entry.bind("<KeyRelease>", mark_cij_table_dirty, add="+")

    add_files_button = ttk.Button(file_buttons, command=add_files, style="Action.TButton")
    add_files_button.grid(row=0, column=0, padx=(0, 6))
    add_folder_button = ttk.Button(file_buttons, command=add_folder, style="Action.TButton")
    add_folder_button.grid(row=0, column=1, padx=(0, 6))
    remove_button = ttk.Button(file_buttons, command=remove_selected, style="Action.TButton")
    remove_button.grid(row=0, column=2, padx=(0, 6))
    clear_button = ttk.Button(file_buttons, command=clear_files, style="Action.TButton")
    clear_button.grid(row=0, column=3, sticky="w")
    apply_name_button.configure(command=apply_display_name)
    reset_name_button.configure(command=reset_display_name)
    fill_cubic_button.configure(command=fill_cubic_cij_table)
    paste_elastic_button.configure(command=paste_elastic_matrix)
    copy_elastic_button.configure(command=copy_elastic_matrix)
    apply_elastic_button.configure(command=apply_elastic_constants)
    clear_elastic_button.configure(command=clear_elastic_constants)

    settings_panel = ttk.Frame(main, padding=16, style="Card.TFrame")
    settings_panel.grid(row=0, column=1, sticky="nsew")
    settings_panel.columnconfigure(1, weight=1)

    settings_panel_header, settings_panel_title = make_section_header(settings_panel, "SettingsAccent.TFrame")
    settings_panel_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    ttk.Label(settings_panel, textvariable=settings_summary_var, style="CardSubtitle.TLabel").grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(0, 12)
    )
    required_parameters_label = ttk.Label(settings_panel, style="Card.TLabel")
    required_parameters_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 4))
    output_label = ttk.Label(settings_panel, style="Card.TLabel")
    output_label.grid(row=3, column=0, sticky="w", pady=5)

    output_frame = ttk.Frame(settings_panel, style="CardBody.TFrame")
    output_frame.grid(row=3, column=1, sticky="ew", pady=5)
    output_frame.columnconfigure(0, weight=1)
    output_entry = ttk.Entry(output_frame, textvariable=output_var)
    output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

    def mark_output_customized(_event: object | None = None) -> None:
        nonlocal output_path_user_customized
        output_path_user_customized = True

    def choose_output() -> None:
        nonlocal output_path_user_customized
        path = filedialog.asksaveasfilename(
            title=_gui_text(lang(), "save_output_title"),
            defaultextension=".xlsx",
            filetypes=[(_gui_text(lang(), "excel_filetype"), "*.xlsx")],
            initialfile=Path(output_var.get()).name or _gui_text(lang(), "default_output_name"),
        )
        if path:
            output_path_user_customized = True
            output_var.set(path)

    choose_output_button = ttk.Button(output_frame, command=choose_output, style="Action.TButton")
    choose_output_button.grid(row=0, column=1)
    output_entry.bind("<KeyRelease>", mark_output_customized)

    def update_settings_summary() -> None:
        energy_text = energy_var.get().strip()
        preset_text = xray_preset_var.get()
        d_min_text = min_var.get().strip()
        d_max_text = max_var.get().strip()
        if energy_text:
            source_text = _gui_text(lang(), "energy_manual", energy=energy_text)
        else:
            source_text = _gui_text(lang(), "energy_preset", preset=preset_text)
        if d_min_text or d_max_text:
            lower = d_min_text or _gui_text(lang(), "unrestricted")
            upper = d_max_text or _gui_text(lang(), "unrestricted")
            range_text = _gui_text(lang(), "d_range_summary", lower=lower, upper=upper)
        else:
            range_text = _gui_text(lang(), "d_unrestricted_summary")
        settings_summary_var.set(_gui_text(lang(), "settings_summary", source=source_text, range=range_text))

    xray_preset_label = ttk.Label(settings_panel, style="Card.TLabel")
    xray_preset_label.grid(row=4, column=0, sticky="w", pady=5)
    preset_box = ttk.Combobox(settings_panel, textvariable=xray_preset_var, values=GUI_XRAY_PRESET_LABELS, state="readonly", width=12)
    preset_box.grid(row=4, column=1, sticky="w", pady=5)
    manual_energy_label = ttk.Label(settings_panel, style="Card.TLabel")
    manual_energy_label.grid(row=5, column=0, sticky="w", pady=5)
    manual_energy_entry = ttk.Entry(settings_panel, textvariable=energy_var, width=12)
    manual_energy_entry.grid(row=5, column=1, sticky="w", pady=5)

    range_frame = ttk.Frame(settings_panel, style="CardBody.TFrame")
    range_frame.grid(row=6, column=1, sticky="w", pady=5)
    d_range_label = ttk.Label(settings_panel, style="Card.TLabel")
    d_range_label.grid(row=6, column=0, sticky="w", pady=5)
    d_min_entry = ttk.Entry(range_frame, textvariable=min_var, width=8)
    d_min_entry.grid(row=0, column=0, sticky="w")
    d_range_to_label = ttk.Label(range_frame, style="Card.TLabel")
    d_range_to_label.grid(row=0, column=1)
    d_max_entry = ttk.Entry(range_frame, textvariable=max_var, width=8)
    d_max_entry.grid(row=0, column=2, sticky="w")
    d_range_unit_label = ttk.Label(range_frame, style="Card.TLabel")
    d_range_unit_label.grid(row=0, column=3, sticky="w")
    output_content_label = ttk.Label(settings_panel, style="Card.TLabel")
    output_content_label.grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 4))
    export_peaks_check = ttk.Checkbutton(settings_panel, variable=export_peaks_var)
    export_peaks_check.grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, 0))
    export_patterns_check = ttk.Checkbutton(settings_panel, variable=export_patterns_var)
    export_patterns_check.grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 0))
    pattern_axis_label = ttk.Label(settings_panel, style="Card.TLabel")
    pattern_axis_label.grid(row=10, column=0, sticky="w", pady=5)
    pattern_axis_box = ttk.Combobox(
        settings_panel,
        textvariable=pattern_axis_var,
        values=("two_theta", "d_spacing", "q", "g"),
        state="readonly",
        width=12,
    )
    pattern_axis_box.grid(row=10, column=1, sticky="w", pady=5)
    optional_outputs_label = ttk.Label(settings_panel, style="Card.TLabel")
    optional_outputs_label.grid(row=11, column=0, columnspan=2, sticky="w", pady=(8, 4))
    publication_svg_check = ttk.Checkbutton(settings_panel, variable=publication_svg_var)
    publication_svg_check.grid(row=12, column=0, columnspan=2, sticky="w", pady=(0, 0))
    figure_preset_label = ttk.Label(settings_panel, style="Card.TLabel")
    figure_preset_label.grid(row=13, column=0, sticky="w", pady=5)
    figure_preset_box = ttk.Combobox(
        settings_panel,
        textvariable=publication_preset_var,
        values=GUI_PUBLICATION_PRESET_LABELS,
        state="readonly",
        width=18,
    )
    figure_preset_box.grid(row=13, column=1, sticky="w", pady=5)
    settings_hint_label = ttk.Label(settings_panel, style="CardSubtitle.TLabel")
    settings_hint_label.grid(row=14, column=0, columnspan=2, sticky="w", pady=(8, 0))
    xray_preset_var.trace_add("write", lambda *_: update_settings_summary())
    energy_var.trace_add("write", lambda *_: update_settings_summary())
    min_var.trace_add("write", lambda *_: update_settings_summary())
    max_var.trace_add("write", lambda *_: update_settings_summary())
    export_peaks_var.trace_add("write", lambda *_: refresh_export_control_states(update_status=True))
    export_patterns_var.trace_add("write", lambda *_: refresh_export_control_states(update_status=True))
    publication_svg_var.trace_add("write", lambda *_: refresh_export_control_states(update_status=True))

    preview_panel = ttk.Frame(main, padding=16, style="Card.TFrame")
    preview_panel.grid(row=1, column=1, sticky="nsew", pady=(14, 0))
    preview_panel.columnconfigure(0, weight=1)
    preview_panel.rowconfigure(1, weight=1)
    preview_panel.rowconfigure(4, weight=0)

    preview_panel_header, preview_panel_title = make_section_header(preview_panel, "PreviewAccent.TFrame")
    preview_panel_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

    columns = ("display_name", "formula", "space_group", "peaks", "warning", "elastic")
    tree = ttk.Treeview(preview_panel, columns=columns, show="headings", height=10, style="Workbench.Treeview")
    for column, width in (
        ("display_name", 190),
        ("formula", 90),
        ("space_group", 90),
        ("peaks", 90),
        ("warning", 240),
        ("elastic", 140),
    ):
        tree.heading(column, text="")
        tree.column(column, width=width, anchor="w")
    tree.grid(row=1, column=0, sticky="nsew")
    tree_scroll = ttk.Scrollbar(preview_panel, orient="vertical", command=tree.yview)
    tree_scroll.grid(row=1, column=1, sticky="ns")
    tree_x_scroll = ttk.Scrollbar(preview_panel, orient="horizontal", command=tree.xview)
    tree_x_scroll.grid(row=2, column=0, sticky="ew")
    tree.configure(yscrollcommand=tree_scroll.set, xscrollcommand=tree_x_scroll.set)
    tree.tag_configure("ok", foreground=GUI_THEME["text"])
    tree.tag_configure("warning", foreground=GUI_THEME["warning"])
    tree.tag_configure("failed", foreground=GUI_THEME["danger"])

    def tree_tags_for_phase_row(row: Sequence[object]) -> tuple[str, ...]:
        warning_text = str(row[4]).strip() if len(row) > 4 else ""
        status_text = str(row[3]).strip().casefold() if len(row) > 3 else ""
        if warning_text and ("无法" in status_text or "cannot" in status_text or status_text == "0"):
            return ("failed",)
        if warning_text:
            return ("warning",)
        return ("ok",)

    activity_log_label = ttk.Label(preview_panel, style="Card.TLabel")
    activity_log_label.grid(row=3, column=0, sticky="w", pady=(10, 4))
    activity_listbox = tk.Listbox(
        preview_panel,
        height=5,
        bd=0,
        highlightthickness=1,
        highlightbackground=GUI_THEME["border"],
        highlightcolor=GUI_THEME["focus"],
        bg=GUI_THEME["panel_muted"],
        fg=GUI_THEME["muted"],
        activestyle="none",
    )
    activity_listbox.grid(row=4, column=0, sticky="ew")
    activity_scroll = ttk.Scrollbar(preview_panel, orient="vertical", command=activity_listbox.yview)
    activity_scroll.grid(row=4, column=1, sticky="ns")
    activity_listbox.configure(yscrollcommand=activity_scroll.set)
    append_activity(_gui_text(lang(), "log_ready"))

    footer = ttk.Frame(root, padding=(24, 8, 24, 18), style="Footer.TFrame")
    footer.grid(row=2, column=0, sticky="ew")
    footer.columnconfigure(1, weight=1)

    export_button = ttk.Button(footer, style="Primary.TButton")
    export_button.grid(row=0, column=0, sticky="w", padx=(0, 12))
    status_frame = ttk.Frame(footer, padding=(12, 8), style="Status.TFrame")
    status_frame.grid(row=0, column=1, sticky="ew", padx=(0, 12))
    status_frame.columnconfigure(0, weight=1)
    status_label = ttk.Label(status_frame, textvariable=status_var, style="Status.TLabel")
    status_label.grid(row=0, column=0, sticky="ew")
    open_button = ttk.Button(footer, state=tk.DISABLED)
    open_button.grid(row=0, column=2, sticky="e")

    def refresh_export_control_states(*, update_status: bool = False) -> None:
        states = gui_export_control_states(
            has_files=bool(selected_paths),
            export_peaks=export_peaks_var.get(),
            export_patterns=export_patterns_var.get(),
            export_publication_figures=publication_svg_var.get(),
            is_busy=export_is_busy,
        )
        export_button.configure(state=states["export_button"])
        pattern_axis_box.configure(state=states["pattern_axis"])
        pattern_axis_label.configure(state=states["pattern_axis"])
        figure_preset_box.configure(state=states["figure_preset"])
        figure_preset_label.configure(state=states["figure_preset"])
        if update_status and selected_paths and not (export_peaks_var.get() or export_patterns_var.get()):
            status_var.set(_gui_text(lang(), "select_export_type"))

    def set_busy(is_busy: bool) -> None:
        nonlocal export_is_busy
        export_is_busy = is_busy
        refresh_export_control_states()

    def schedule_preview() -> None:
        nonlocal preview_generation
        preview_generation += 1
        generation = preview_generation
        tree.delete(*tree.get_children())
        if not selected_paths:
            return

        paths_snapshot = list(selected_paths)
        display_names_snapshot = {path: display_names.get(path, path.name) for path in paths_snapshot}
        elastic_constants_snapshot = {path: elastic_constants[path] for path in paths_snapshot if path in elastic_constants}
        language_snapshot = lang()
        status_var.set(_gui_text(language_snapshot, "reading_cif"))
        append_activity(_gui_text(language_snapshot, "log_preview_reading"))

        def worker() -> None:
            result = preview_simple_gui_inputs(
                paths_snapshot,
                display_names_snapshot,
                language_snapshot,
                elastic_constants=elastic_constants_snapshot,
            )

            def finish() -> None:
                if generation != preview_generation:
                    return
                tree.delete(*tree.get_children())
                for row in result.phase_rows:
                    tree.insert("", tk.END, values=row, tags=tree_tags_for_phase_row(row))
                if result.failed_count:
                    status_var.set(
                        _gui_text(
                            lang(),
                            "recognized_with_failures",
                            ready=result.ready_count,
                            failed=result.failed_count,
                        )
                    )
                    append_activity(
                        _gui_text(
                            lang(),
                            "log_preview_with_failures",
                            ready=result.ready_count,
                            failed=result.failed_count,
                        )
                    )
                else:
                    status_var.set(_gui_text(lang(), "recognized_ready", ready=result.ready_count))
                    append_activity(_gui_text(lang(), "log_preview_ready", ready=result.ready_count))

            root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def export_now() -> None:
        nonlocal last_output_path
        export_peaks_snapshot = export_peaks_var.get()
        export_patterns_snapshot = export_patterns_var.get()
        export_publication_snapshot = publication_svg_var.get()
        output_snapshot = output_var.get()
        energy_snapshot = energy_var.get()
        xray_preset_snapshot = xray_preset_var.get()
        d_min_snapshot = min_var.get()
        d_max_snapshot = max_var.get()
        pattern_axis_snapshot = pattern_axis_var.get()
        publication_preset_snapshot = publication_preset_var.get()
        paths_snapshot = list(selected_paths)
        display_names_snapshot = {path: display_names.get(path, path.name) for path in paths_snapshot}
        elastic_constants_snapshot = {path: elastic_constants[path] for path in paths_snapshot if path in elastic_constants}
        if not (export_peaks_snapshot or export_patterns_snapshot):
            status_var.set(_gui_text(lang(), "select_export_type"))
            return
        try:
            planned_outputs = planned_gui_output_paths(
                output_snapshot,
                paths_snapshot,
                display_names=display_names_snapshot,
                export_peaks=export_peaks_snapshot,
                export_patterns=export_patterns_snapshot,
                export_publication_figures=export_publication_snapshot,
            )
            allow_overwrite = should_overwrite_gui_outputs(
                planned_outputs,
                lambda path: messagebox.askyesno(
                    _gui_text(lang(), "confirm_overwrite_title"),
                    _gui_text(lang(), "confirm_overwrite_message", path=path),
                ),
            )
        except Exception as exc:
            status_var.set(_gui_text(lang(), "export_failed_status"))
            append_activity(_gui_text(lang(), "log_export_failed"))
            messagebox.showerror(_gui_text(lang(), "export_failed_title"), friendly_error_message(exc, lang()))
            return
        if not allow_overwrite:
            status_var.set(_gui_text(lang(), "export_cancelled_overwrite"))
            append_activity(_gui_text(lang(), "log_export_cancelled"))
            return
        set_busy(True)
        open_button.configure(state=tk.DISABLED)
        status_var.set(_gui_text(lang(), "exporting"))
        append_activity(_gui_text(lang(), "log_exporting"))
        tree.delete(*tree.get_children())

        def worker() -> None:
            try:
                result = run_simple_gui_export(
                    paths_snapshot,
                    output_snapshot,
                    energy_keV=energy_snapshot,
                    xray_preset=xray_preset_snapshot,
                    d_min_A=d_min_snapshot,
                    d_max_A=d_max_snapshot,
                    display_names=display_names_snapshot,
                    elastic_constants=elastic_constants_snapshot,
                    export_peaks=export_peaks_snapshot,
                    export_patterns=export_patterns_snapshot,
                    pattern_axis=pattern_axis_snapshot,  # type: ignore[arg-type]
                    export_publication_svg=export_publication_snapshot,
                    publication_preset=publication_preset_snapshot,
                )
            except Exception as exc:
                def finish_failure(exc: Exception = exc) -> None:
                    set_busy(False)
                    status_var.set(_gui_text(lang(), "export_failed_status"))
                    append_activity(_gui_text(lang(), "log_export_failed"))
                    messagebox.showerror(_gui_text(lang(), "export_failed_title"), friendly_error_message(exc, lang()))

                root.after(
                    0,
                    finish_failure,
                )
                return

            def finish() -> None:
                nonlocal last_output_path
                for row in result.phase_rows:
                    tree.insert("", tk.END, values=row, tags=tree_tags_for_phase_row(row))
                last_output_path = result.output_path
                set_busy(False)
                open_button.configure(state=tk.NORMAL)
                status_text, dialog_text = gui_export_completion_text(result, lang())
                status_var.set(status_text)
                summary = summarize_gui_export_result(result)
                append_activity(
                    _gui_text(
                        lang(),
                        "log_export_done",
                        peaks=result.total_peaks,
                        failed=summary.failed_count,
                        warnings=summary.warning_count,
                        zero_peaks=summary.zero_peak_count,
                    )
                )
                messagebox.showinfo(_gui_text(lang(), "export_done_title"), dialog_text)

            root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def open_output_folder() -> None:
        if last_output_path is not None:
            open_export_result(last_output_path)

    def handle_drop(event: object) -> str:
        data = getattr(event, "data", "")
        dropped_paths = split_drop_event_paths(str(data), root.tk.splitlist)
        add_inputs(dropped_paths, _gui_text(lang(), "source_drop"))
        return "break"

    def register_drop_target(widget: object) -> None:
        if not dnd_available:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", handle_drop)
        except Exception:
            drop_hint_var.set(_gui_text(lang(), "drop_unavailable_short"))

    def apply_language(refresh_preview: bool = False) -> None:
        root.title(_gui_text(lang(), "window_title"))
        workspace_label.configure(text=_gui_text(lang(), "workspace_section"))
        title_label.configure(text=_gui_text(lang(), "app_title"))
        subtitle_label.configure(text=_gui_text(lang(), "app_subtitle"))
        credit_label.configure(text=_gui_text(lang(), "developer_credit"))
        language_button.configure(text=_gui_text(lang(), "toggle_language"))
        files_panel_title.configure(text=_gui_text(lang(), "data_source_title"))
        display_name_label.configure(text=_gui_text(lang(), "display_name_label"))
        apply_name_button.configure(text=_gui_text(lang(), "apply_display_name"))
        reset_name_button.configure(text=_gui_text(lang(), "reset_display_name"))
        elastic_label.configure(text=_gui_text(lang(), "advanced_elastic_group"))
        elastic_cubic_label.configure(text=_gui_text(lang(), "elastic_cubic_label"))
        elastic_matrix_label.configure(text=_gui_text(lang(), "elastic_matrix_label"))
        elastic_source_label.configure(text=_gui_text(lang(), "elastic_source_label"))
        fill_cubic_button.configure(text=_gui_text(lang(), "fill_cubic_elastic"))
        paste_elastic_button.configure(text=_gui_text(lang(), "paste_elastic"))
        copy_elastic_button.configure(text=_gui_text(lang(), "copy_elastic"))
        apply_elastic_button.configure(text=_gui_text(lang(), "apply_elastic"))
        clear_elastic_button.configure(text=_gui_text(lang(), "clear_elastic"))
        add_files_button.configure(text=_gui_text(lang(), "add_files"))
        add_folder_button.configure(text=_gui_text(lang(), "add_folder"))
        remove_button.configure(text=_gui_text(lang(), "remove_selected"))
        clear_button.configure(text=_gui_text(lang(), "clear_files"))
        settings_panel_title.configure(text=_gui_text(lang(), "parameters_title"))
        required_parameters_label.configure(text=_gui_text(lang(), "required_parameters_group"))
        output_content_label.configure(text=_gui_text(lang(), "output_content_group"))
        optional_outputs_label.configure(text=_gui_text(lang(), "optional_outputs_group"))
        output_label.configure(text=_gui_text(lang(), "output_file"))
        choose_output_button.configure(text=_gui_text(lang(), "choose_output"))
        xray_preset_label.configure(text=_gui_text(lang(), "xray_preset"))
        manual_energy_label.configure(text=_gui_text(lang(), "manual_energy"))
        d_range_label.configure(text=_gui_text(lang(), "d_range"))
        export_peaks_check.configure(text=_gui_text(lang(), "export_peaks"))
        export_patterns_check.configure(text=_gui_text(lang(), "export_patterns"))
        pattern_axis_label.configure(text=_gui_text(lang(), "pattern_axis"))
        publication_svg_check.configure(text=_gui_text(lang(), "publication_export"))
        figure_preset_label.configure(text=_gui_text(lang(), "figure_preset"))
        d_range_to_label.configure(text=_gui_text(lang(), "to_text"))
        d_range_unit_label.configure(text=_gui_text(lang(), "angstrom"))
        settings_hint_label.configure(text=_gui_text(lang(), "settings_hint"))
        preview_panel_title.configure(text=_gui_text(lang(), "preview_title"))
        activity_log_label.configure(text=_gui_text(lang(), "activity_log_title"))
        tree.heading("display_name", text=_gui_text(lang(), "tree_display_name"))
        tree.heading("formula", text=_gui_text(lang(), "tree_formula"))
        tree.heading("space_group", text=_gui_text(lang(), "tree_space_group"))
        tree.heading("peaks", text=_gui_text(lang(), "tree_status"))
        tree.heading("warning", text=_gui_text(lang(), "tree_warning"))
        tree.heading("elastic", text=_gui_text(lang(), "tree_elastic"))
        export_button.configure(text=_gui_text(lang(), "export_excel"))
        open_button.configure(text=_gui_text(lang(), "open_excel"))
        input_summary_var.set(
            _gui_text(lang(), "no_cif")
            if not selected_paths
            else _gui_text(lang(), "cif_count", count=len(selected_paths))
        )
        drop_hint_var.set(
            _gui_text(lang(), "drop_hint_available")
            if dnd_available
            else _gui_text(lang(), "drop_hint_unavailable")
        )
        update_settings_summary()
        if selected_paths:
            status_var.set(_gui_text(lang(), "ready_to_export"))
        else:
            status_var.set(_gui_text(lang(), "ready_to_add"))
        refresh_export_control_states(update_status=True)
        if refresh_preview:
            schedule_preview()
        path = selected_display_path()
        set_elastic_status_feedback(None if path is None else elastic_constants.get(path))

    def toggle_language() -> None:
        language_var.set("en" if lang() == "zh" else "zh")
        apply_language(refresh_preview=True)

    for drop_widget in (root, files_panel, listbox, preview_panel, tree):
        register_drop_target(drop_widget)

    language_button.configure(command=toggle_language)
    export_button.configure(command=export_now)
    refresh_export_control_states(update_status=True)
    open_button.configure(command=open_output_folder)
    for widget, role in (
        (add_files_button, "add_files"),
        (add_folder_button, "add_folder"),
        (remove_button, "remove_selected"),
        (clear_button, "clear_files"),
        (display_name_entry, "display_name"),
        (elastic_entry, "elastic_cubic"),
        (fill_cubic_button, "fill_cubic_elastic"),
        (elastic_grid_frame, "elastic_matrix"),
        (elastic_source_entry, "elastic_source"),
        (paste_elastic_button, "paste_elastic"),
        (copy_elastic_button, "copy_elastic"),
        (apply_elastic_button, "apply_elastic"),
        (clear_elastic_button, "clear_elastic"),
        (output_entry, "output_file"),
        (choose_output_button, "choose_output"),
        (preset_box, "xray_preset"),
        (manual_energy_entry, "manual_energy"),
        (d_range_label, "d_range"),
        (d_min_entry, "d_range"),
        (d_max_entry, "d_range"),
        (export_peaks_check, "export_peaks"),
        (export_patterns_check, "export_patterns"),
        (pattern_axis_box, "pattern_axis"),
        (publication_svg_check, "publication_export"),
        (figure_preset_box, "figure_preset"),
        (export_button, "export_excel"),
        (open_button, "open_excel"),
    ):
        attach_tooltip(widget, role)
    apply_language()
    refresh_list()
    root.mainloop()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        _launch_tk_app(sys.argv[1:] if argv is None else argv)
    except Exception as exc:
        if exc.__class__.__name__ == "TclError" and "init.tcl" in str(exc):
            print(
                "CIF2Peaks 无法启动图形界面：当前 Python 的 Tcl/Tk 组件不可用。\n"
                "请优先双击 start_cif2peaks.bat；如果仍失败，请修复 Python 安装中的 Tcl/Tk，"
                "或使用 dist\\CIF2Peaks\\CIF2Peaks.exe。"
            )
            return 1
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
