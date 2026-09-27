from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
import html
from typing import Sequence

import numpy as np

from .models import XRDResult


@dataclass(frozen=True)
class FigureExportPreset:
    width_in: float
    height_in: float
    dpi: int
    font_family: str
    label_font_pt: float
    tick_font_pt: float
    title_font_pt: float
    legend_font_pt: float
    line_width_pt: float
    marker_size_pt: float
    axis_width_pt: float
    color_cycle: tuple[str, ...]
    scientific_colormap: str
    constrained_layout: bool = True


PUBLICATION_FONT_STACK = "Arial, Helvetica, DejaVu Sans, sans-serif"
COLORBLIND_SAFE_COLORS = ("#2f5d8c", "#b24c3f", "#4f7f52", "#6f5b9a", "#8a6f3d")
PUBLICATION_EXPORT_FORMATS = ("svg", "pdf", "eps", "png", "tif")

_BITMAP_FONT_5X7 = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    ",": ("00000", "00000", "00000", "00000", "00110", "00100", "01000"),
    ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10011", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00001", "00001", "00001", "00001", "10001", "10001", "01110"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}

FIGURE_EXPORT_PRESETS: dict[str, FigureExportPreset] = {
    "single_column": FigureExportPreset(
        width_in=3.35,
        height_in=2.35,
        dpi=600,
        font_family=PUBLICATION_FONT_STACK,
        label_font_pt=8.0,
        tick_font_pt=7.0,
        title_font_pt=8.5,
        legend_font_pt=7.0,
        line_width_pt=0.9,
        marker_size_pt=3.0,
        axis_width_pt=0.75,
        color_cycle=COLORBLIND_SAFE_COLORS,
        scientific_colormap="viridis",
    ),
    "double_column": FigureExportPreset(
        width_in=7.0,
        height_in=4.2,
        dpi=600,
        font_family=PUBLICATION_FONT_STACK,
        label_font_pt=9.0,
        tick_font_pt=8.0,
        title_font_pt=10.0,
        legend_font_pt=8.0,
        line_width_pt=1.0,
        marker_size_pt=3.5,
        axis_width_pt=0.8,
        color_cycle=COLORBLIND_SAFE_COLORS,
        scientific_colormap="viridis",
    ),
    "presentation": FigureExportPreset(
        width_in=10.0,
        height_in=5.6,
        dpi=300,
        font_family=PUBLICATION_FONT_STACK,
        label_font_pt=18.0,
        tick_font_pt=14.0,
        title_font_pt=20.0,
        legend_font_pt=14.0,
        line_width_pt=2.0,
        marker_size_pt=5.0,
        axis_width_pt=1.2,
        color_cycle=COLORBLIND_SAFE_COLORS,
        scientific_colormap="cividis",
    ),
    "raw_inspection": FigureExportPreset(
        width_in=6.0,
        height_in=3.5,
        dpi=300,
        font_family=PUBLICATION_FONT_STACK,
        label_font_pt=10.0,
        tick_font_pt=9.0,
        title_font_pt=11.0,
        legend_font_pt=9.0,
        line_width_pt=1.2,
        marker_size_pt=4.0,
        axis_width_pt=0.9,
        color_cycle=COLORBLIND_SAFE_COLORS,
        scientific_colormap="gray",
    ),
    "publication": FigureExportPreset(
        width_in=3.5,
        height_in=2.55,
        dpi=600,
        font_family=PUBLICATION_FONT_STACK,
        label_font_pt=8.0,
        tick_font_pt=7.0,
        title_font_pt=8.5,
        legend_font_pt=7.0,
        line_width_pt=0.9,
        marker_size_pt=3.0,
        axis_width_pt=0.75,
        color_cycle=COLORBLIND_SAFE_COLORS,
        scientific_colormap="viridis",
    ),
}


def _preset(name: str) -> FigureExportPreset:
    try:
        return FIGURE_EXPORT_PRESETS[name]
    except KeyError as exc:
        valid = ", ".join(sorted(FIGURE_EXPORT_PRESETS))
        raise ValueError(f"Unknown figure export preset: {name}. Valid presets: {valid}") from exc


def _nice_ticks(lower: float, upper: float, count: int = 5) -> list[float]:
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        return [lower]
    raw_step = (upper - lower) / max(count - 1, 1)
    exponent = np.floor(np.log10(raw_step))
    base = raw_step / (10**exponent)
    if base <= 1.5:
        nice_base = 1.0
    elif base <= 3.0:
        nice_base = 2.0
    elif base <= 7.0:
        nice_base = 5.0
    else:
        nice_base = 10.0
    step = nice_base * (10**exponent)
    first = np.ceil(lower / step) * step
    ticks: list[float] = []
    value = first
    while value <= upper + step * 0.25:
        ticks.append(float(value))
        value += step
    return ticks or [lower, upper]


def _format_tick(value: float) -> str:
    if abs(value) >= 100 or float(value).is_integer():
        return f"{value:.0f}"
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _polyline(points: Sequence[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _rgb01(hex_color: str) -> tuple[float, float, float]:
    color = hex_color.lstrip("#")
    if len(color) != 6:
        return 0.0, 0.0, 0.0
    return tuple(int(color[index : index + 2], 16) / 255.0 for index in (0, 2, 4))


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _ps_escape(text: str) -> str:
    return _pdf_escape(text)


def _ascii_plot_title(title: str) -> str:
    return title.encode("ascii", errors="replace").decode("ascii")


def _matplotlib_font_family(preset: FigureExportPreset) -> list[str]:
    return [font.strip() for font in preset.font_family.split(",") if font.strip()]


def _profile_plot_geometry(result: XRDResult, preset: FigureExportPreset, units_per_inch: float) -> dict[str, object]:
    x_values = np.asarray(result.two_theta_grid, dtype=float)
    y_values = np.asarray(result.intensity_profile, dtype=float)
    if x_values.size == 0 or y_values.size == 0:
        raise ValueError("XRD result contains no profile points to plot.")
    if x_values.size != y_values.size:
        raise ValueError("XRD result x/y profile arrays have different lengths.")

    width = preset.width_in * units_per_inch
    height = preset.height_in * units_per_inch
    margin_left = max(0.48 * units_per_inch, preset.label_font_pt * 4.5)
    margin_right = max(0.16 * units_per_inch, preset.tick_font_pt * 1.4)
    margin_top = max(0.28 * units_per_inch, preset.title_font_pt * 2.2)
    margin_bottom = max(0.42 * units_per_inch, preset.label_font_pt * 4.0)
    plot_left = margin_left
    plot_bottom = margin_bottom
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    x_min = float(np.nanmin(x_values))
    x_max = float(np.nanmax(x_values))
    y_max = float(np.nanmax(y_values))
    if y_max <= 0 or not np.isfinite(y_max):
        y_max = 1.0
    y_upper = max(100.0, y_max) * 1.04

    def sx(value: float) -> float:
        return plot_left + (value - x_min) / (x_max - x_min) * plot_width if x_max > x_min else plot_left

    def sy(value: float) -> float:
        return plot_bottom + (value / y_upper) * plot_height

    points = [(sx(float(x)), sy(float(y))) for x, y in zip(x_values, y_values, strict=True)]
    return {
        "width": width,
        "height": height,
        "plot_left": plot_left,
        "plot_bottom": plot_bottom,
        "plot_width": plot_width,
        "plot_height": plot_height,
        "points": points,
        "x_ticks": _nice_ticks(x_min, x_max, 6),
        "y_ticks": _nice_ticks(0.0, y_upper, 5),
        "sx": sx,
        "sy": sy,
    }


def _draw_pixel(buffer: bytearray, width: int, height: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    offset = (y * width + x) * 3
    buffer[offset : offset + 3] = bytes(color)


def _draw_dot(buffer: bytearray, width: int, height: int, x: int, y: int, radius: int, color: tuple[int, int, int]) -> None:
    radius = max(0, radius)
    for yy in range(y - radius, y + radius + 1):
        for xx in range(x - radius, x + radius + 1):
            if (xx - x) ** 2 + (yy - y) ** 2 <= radius**2:
                _draw_pixel(buffer, width, height, xx, yy, color)


def _draw_line(
    buffer: bytearray,
    width: int,
    height: int,
    start: tuple[float, float],
    end: tuple[float, float],
    color: tuple[int, int, int],
    line_width_px: int = 1,
) -> None:
    x1, y1 = start
    x2, y2 = end
    steps = max(int(abs(x2 - x1)), int(abs(y2 - y1)), 1)
    radius = max(0, line_width_px // 2)
    for index in range(steps + 1):
        t = index / steps
        x = int(round(x1 + (x2 - x1) * t))
        y = int(round(y1 + (y2 - y1) * t))
        _draw_dot(buffer, width, height, x, y, radius, color)


def _font_scale(font_pt: float, dpi: int) -> int:
    return max(1, int(round((font_pt * dpi / 72.0) / 7.0)))


def _text_mask(text: str, scale: int) -> list[list[bool]]:
    rows = [[] for _ in range(7 * scale)]
    normalized = text.upper()
    for character in normalized:
        glyph = _BITMAP_FONT_5X7.get(character, _BITMAP_FONT_5X7["?"])
        for glyph_row, pattern in enumerate(glyph):
            for _ in range(scale):
                target = rows[glyph_row * scale + _]
                for bit in pattern:
                    target.extend([bit == "1"] * scale)
                target.extend([False] * scale)
    return rows


def _rotate_mask(mask: list[list[bool]], rotation: int) -> list[list[bool]]:
    if rotation == 0:
        return mask
    if not mask or not mask[0]:
        return mask
    if rotation == -90:
        return [[mask[row][col] for row in range(len(mask))] for col in range(len(mask[0]) - 1, -1, -1)]
    if rotation == 90:
        return [[mask[row][col] for row in range(len(mask) - 1, -1, -1)] for col in range(len(mask[0]))]
    raise ValueError("Only 0, 90 and -90 degree bitmap text rotations are supported.")


def _draw_text(
    buffer: bytearray,
    width: int,
    height: int,
    text: str,
    x: float,
    y: float,
    scale: int,
    color: tuple[int, int, int],
    *,
    anchor: str = "mm",
    rotation: int = 0,
) -> None:
    mask = _rotate_mask(_text_mask(text, scale), rotation)
    if not mask or not mask[0]:
        return
    text_height = len(mask)
    text_width = len(mask[0])
    if anchor[0] == "m":
        top = int(round(y - text_height / 2))
    elif anchor[0] == "s":
        top = int(round(y - text_height))
    else:
        top = int(round(y))
    if anchor[1] == "m":
        left = int(round(x - text_width / 2))
    elif anchor[1] == "e":
        left = int(round(x - text_width))
    else:
        left = int(round(x))
    for row_index, row in enumerate(mask):
        for col_index, enabled in enumerate(row):
            if enabled:
                _draw_pixel(buffer, width, height, left + col_index, top + row_index, color)


def _point_color(hex_color: str) -> tuple[int, int, int]:
    red, green, blue = _rgb01(hex_color)
    return int(round(red * 255)), int(round(green * 255)), int(round(blue * 255))


def _raster_xrd_pattern(
    result: XRDResult,
    *,
    title: str,
    preset_name: str,
) -> tuple[int, int, int, bytearray, str]:
    preset = _preset(preset_name)
    geometry = _profile_plot_geometry(result, preset, float(preset.dpi))
    width = int(round(float(geometry["width"])))
    height = int(round(float(geometry["height"])))
    plot_left = float(geometry["plot_left"])
    plot_bottom = float(geometry["plot_bottom"])
    plot_width = float(geometry["plot_width"])
    plot_height = float(geometry["plot_height"])
    points = geometry["points"]
    sx = geometry["sx"]
    sy = geometry["sy"]
    x_ticks = geometry["x_ticks"]
    y_ticks = geometry["y_ticks"]

    buffer = bytearray([255] * (width * height * 3))
    axis_color = (34, 34, 34)
    line_color = _point_color(preset.color_cycle[0])
    axis_width_px = max(1, int(round(preset.axis_width_pt * preset.dpi / 72.0)))
    line_width_px = max(1, int(round(preset.line_width_pt * preset.dpi / 72.0)))

    def to_raster(point: tuple[float, float]) -> tuple[float, float]:
        return point[0], height - point[1]

    x_axis_y = height - plot_bottom
    plot_top_y = height - (plot_bottom + plot_height)
    _draw_line(buffer, width, height, (plot_left, x_axis_y), (plot_left, plot_top_y), axis_color, axis_width_px)
    _draw_line(buffer, width, height, (plot_left, x_axis_y), (plot_left + plot_width, x_axis_y), axis_color, axis_width_px)

    tick_scale = _font_scale(preset.tick_font_pt, preset.dpi)
    label_scale = _font_scale(preset.label_font_pt, preset.dpi)
    title_scale = _font_scale(preset.title_font_pt, preset.dpi)
    for tick in x_ticks:
        x = float(sx(float(tick)))
        _draw_line(buffer, width, height, (x, x_axis_y), (x, x_axis_y + 6 * tick_scale), axis_color, axis_width_px)
        _draw_text(buffer, width, height, _format_tick(float(tick)), x, x_axis_y + 9 * tick_scale, tick_scale, axis_color, anchor="nm")
    for tick in y_ticks:
        y = height - float(sy(float(tick)))
        _draw_line(buffer, width, height, (plot_left - 6 * tick_scale, y), (plot_left, y), axis_color, axis_width_px)
        _draw_text(buffer, width, height, _format_tick(float(tick)), plot_left - 9 * tick_scale, y, tick_scale, axis_color, anchor="me")

    _draw_text(buffer, width, height, "2theta (deg)", plot_left + plot_width / 2, height - 1.4 * label_scale, label_scale, axis_color, anchor="sm")
    _draw_text(
        buffer,
        width,
        height,
        "Intensity (a.u.)",
        max(plot_left * 0.25, 6.0 * label_scale, 48),
        plot_top_y + plot_height / 2,
        label_scale,
        axis_color,
        anchor="mm",
        rotation=-90,
    )
    safe_title = _ascii_plot_title(title)
    _draw_text(buffer, width, height, safe_title, width / 2, 4.2 * title_scale, title_scale, axis_color, anchor="mm")

    raster_points = [to_raster((float(x), float(y))) for x, y in points]
    for start, end in zip(raster_points, raster_points[1:], strict=False):
        _draw_line(buffer, width, height, start, end, line_color, line_width_px)

    description = (
        f"Publication-style theoretical powder XRD profile exported by CIF2Peaks. "
        f"Preset: {preset_name}; dpi: {preset.dpi}; XLabel: 2theta (deg); YLabel: Intensity (a.u.)."
    )
    return width, height, preset.dpi, buffer, description


def _matplotlib_xrd_pattern(
    result: XRDResult,
    *,
    title: str,
    preset_name: str,
) -> tuple[int, int, int, bytearray, str] | None:
    figure_data = _matplotlib_xrd_figure(result, title=title, preset_name=preset_name)
    if figure_data is None:
        return None
    figure, canvas, preset = figure_data
    try:
        canvas.draw()
        width, height = canvas.get_width_height()
        rgba = np.asarray(canvas.buffer_rgba(), dtype=np.uint8)
        rgb = np.ascontiguousarray(rgba[:, :, :3])
        description = (
            f"Publication-style theoretical powder XRD profile exported by CIF2Peaks. "
            f"Renderer: matplotlib Agg; Preset: {preset_name}; dpi: {preset.dpi}; "
            "XLabel: 2theta (deg); YLabel: Intensity (a.u.)."
        )
        figure.clear()
        return int(width), int(height), preset.dpi, bytearray(rgb.tobytes()), description
    except Exception:
        figure.clear()
        return None


def _matplotlib_xrd_figure(
    result: XRDResult,
    *,
    title: str,
    preset_name: str,
):
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except Exception:
        return None

    try:
        preset = _preset(preset_name)
        x_values = np.asarray(result.two_theta_grid, dtype=float)
        y_values = np.asarray(result.intensity_profile, dtype=float)
        if x_values.size == 0 or y_values.size == 0:
            raise ValueError("XRD result contains no profile points to plot.")
        if x_values.size != y_values.size:
            raise ValueError("XRD result x/y profile arrays have different lengths.")

        figure = Figure(figsize=(preset.width_in, preset.height_in), dpi=preset.dpi, constrained_layout=preset.constrained_layout)
        canvas = FigureCanvasAgg(figure)
        axis = figure.add_subplot(111)
        font_family = _matplotlib_font_family(preset)
        axis.plot(
            x_values,
            y_values,
            color=preset.color_cycle[0],
            linewidth=preset.line_width_pt,
            solid_joinstyle="round",
            solid_capstyle="round",
            antialiased=True,
        )
        axis.set_xlabel("2θ (°)", fontsize=preset.label_font_pt, fontfamily=font_family)
        axis.set_ylabel("Intensity (a.u.)", fontsize=preset.label_font_pt, fontfamily=font_family)
        axis.set_title(title, fontsize=preset.title_font_pt, fontfamily=font_family, pad=max(2.0, preset.title_font_pt * 0.45))
        axis.set_xlim(float(np.nanmin(x_values)), float(np.nanmax(x_values)))
        y_max = float(np.nanmax(y_values))
        if y_max <= 0 or not np.isfinite(y_max):
            y_max = 1.0
        axis.set_ylim(0.0, max(100.0, y_max) * 1.04)
        axis.tick_params(
            axis="both",
            which="major",
            labelsize=preset.tick_font_pt,
            width=preset.axis_width_pt,
            length=max(2.0, preset.axis_width_pt * 4.0),
            direction="out",
        )
        for label in [*axis.get_xticklabels(), *axis.get_yticklabels()]:
            label.set_fontfamily(font_family)
        for spine in axis.spines.values():
            spine.set_linewidth(preset.axis_width_pt)
            spine.set_color("#222222")
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.grid(False)
        figure.patch.set_facecolor("white")
        axis.set_facecolor("white")
        return figure, canvas, preset
    except Exception:
        return None


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _write_png(
    output_path: str | Path,
    *,
    width: int,
    height: int,
    dpi: int,
    buffer: bytearray,
    title: str,
    description: str,
) -> Path:
    scanlines = bytearray()
    row_bytes = width * 3
    for row in range(height):
        scanlines.append(0)
        start = row * row_bytes
        scanlines.extend(buffer[start : start + row_bytes])
    pixels_per_meter = int(round(dpi / 0.0254))
    content = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            _png_chunk(b"pHYs", struct.pack(">IIB", pixels_per_meter, pixels_per_meter, 1)),
            _png_chunk(b"tEXt", b"Title\x00" + _ascii_plot_title(title).encode("latin-1", errors="replace")),
            _png_chunk(b"tEXt", b"Description\x00" + description.encode("latin-1", errors="replace")),
            _png_chunk(b"tEXt", b"XLabel\x002theta (deg)"),
            _png_chunk(b"tEXt", b"YLabel\x00Intensity (a.u.)"),
            _png_chunk(b"IDAT", zlib.compress(bytes(scanlines), level=9)),
            _png_chunk(b"IEND", b""),
        ]
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_tiff(
    output_path: str | Path,
    *,
    width: int,
    height: int,
    dpi: int,
    buffer: bytearray,
    title: str,
    description: str,
) -> Path:
    image_description = f"{description} Title: {_ascii_plot_title(title)}\x00".encode("ascii", errors="replace")
    software = b"CIF2Peaks\x00"
    entries: list[tuple[int, int, int, int | bytes]] = [
        (256, 4, 1, width),
        (257, 4, 1, height),
        (258, 3, 3, b"\x08\x00\x08\x00\x08\x00"),
        (259, 3, 1, 1),
        (262, 3, 1, 2),
        (270, 2, len(image_description), image_description),
        (273, 4, 1, 0),
        (277, 3, 1, 3),
        (278, 4, 1, height),
        (279, 4, 1, len(buffer)),
        (282, 5, 1, struct.pack("<II", dpi, 1)),
        (283, 5, 1, struct.pack("<II", dpi, 1)),
        (296, 3, 1, 2),
        (305, 2, len(software), software),
    ]
    entries.sort(key=lambda item: item[0])
    ifd_size = 2 + len(entries) * 12 + 4
    extra_offset = 8 + ifd_size
    extra = bytearray()
    packed_entries: list[bytes] = []
    strip_offset_entry_index = next(index for index, entry in enumerate(entries) if entry[0] == 273)
    for index, (tag, field_type, count, value) in enumerate(entries):
        if isinstance(value, bytes):
            value_offset = extra_offset + len(extra)
            extra.extend(value)
            if len(extra) % 2:
                extra.append(0)
            packed_entries.append(struct.pack("<HHI", tag, field_type, count) + struct.pack("<I", value_offset))
        elif field_type == 3 and count == 1:
            packed_entries.append(struct.pack("<HHI", tag, field_type, count) + struct.pack("<H", value) + b"\x00\x00")
        else:
            packed_entries.append(struct.pack("<HHII", tag, field_type, count, value))
        if index == strip_offset_entry_index:
            packed_entries[-1] = b""
    pixel_offset = extra_offset + len(extra)
    packed_entries[strip_offset_entry_index] = struct.pack("<HHII", 273, 4, 1, pixel_offset)
    content = bytearray(b"II*\x00")
    content.extend(struct.pack("<I", 8))
    content.extend(struct.pack("<H", len(entries)))
    content.extend(b"".join(packed_entries))
    content.extend(struct.pack("<I", 0))
    content.extend(extra)
    content.extend(buffer)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(content))
    return path


def export_xrd_pattern_png(
    result: XRDResult,
    output_path: str | Path,
    *,
    title: str = "Theoretical XRD pattern",
    preset_name: str = "publication",
) -> Path:
    width, height, dpi, buffer, description = _matplotlib_xrd_pattern(result, title=title, preset_name=preset_name) or _raster_xrd_pattern(
        result,
        title=title,
        preset_name=preset_name,
    )
    return _write_png(output_path, width=width, height=height, dpi=dpi, buffer=buffer, title=title, description=description)


def export_xrd_pattern_tiff(
    result: XRDResult,
    output_path: str | Path,
    *,
    title: str = "Theoretical XRD pattern",
    preset_name: str = "publication",
) -> Path:
    width, height, dpi, buffer, description = _matplotlib_xrd_pattern(result, title=title, preset_name=preset_name) or _raster_xrd_pattern(
        result,
        title=title,
        preset_name=preset_name,
    )
    return _write_tiff(output_path, width=width, height=height, dpi=dpi, buffer=buffer, title=title, description=description)


def export_xrd_pattern_svg(
    result: XRDResult,
    output_path: str | Path,
    *,
    title: str = "Theoretical XRD pattern",
    preset_name: str = "publication",
) -> Path:
    preset = _preset(preset_name)
    x_values = np.asarray(result.two_theta_grid, dtype=float)
    y_values = np.asarray(result.intensity_profile, dtype=float)
    if x_values.size == 0 or y_values.size == 0:
        raise ValueError("XRD result contains no profile points to plot.")
    if x_values.size != y_values.size:
        raise ValueError("XRD result x/y profile arrays have different lengths.")

    width_px = int(round(preset.width_in * preset.dpi))
    height_px = int(round(preset.height_in * preset.dpi))
    margin_left = max(58.0, preset.label_font_pt * 6.0)
    margin_right = max(18.0, preset.tick_font_pt * 2.0)
    margin_top = max(30.0, preset.title_font_pt * 3.0)
    margin_bottom = max(50.0, preset.label_font_pt * 5.0)
    plot_left = margin_left
    plot_top = margin_top
    plot_width = width_px - margin_left - margin_right
    plot_height = height_px - margin_top - margin_bottom

    x_min = float(np.nanmin(x_values))
    x_max = float(np.nanmax(x_values))
    y_max = float(np.nanmax(y_values))
    if y_max <= 0 or not np.isfinite(y_max):
        y_max = 1.0
    y_upper = max(100.0, y_max) * 1.04

    def sx(value: float) -> float:
        return plot_left + (value - x_min) / (x_max - x_min) * plot_width if x_max > x_min else plot_left

    def sy(value: float) -> float:
        return plot_top + plot_height - (value / y_upper) * plot_height

    profile_points = [(sx(float(x)), sy(float(y))) for x, y in zip(x_values, y_values, strict=True)]
    x_ticks = _nice_ticks(x_min, x_max, 6)
    y_ticks = _nice_ticks(0.0, y_upper, 5)
    axis_color = "#222222"
    line_color = preset.color_cycle[0]
    escaped_title = html.escape(title)

    tick_markup: list[str] = []
    for tick in x_ticks:
        x = sx(tick)
        tick_markup.append(
            f'<line x1="{x:.2f}" y1="{plot_top + plot_height:.2f}" x2="{x:.2f}" y2="{plot_top + plot_height + 5:.2f}" '
            f'stroke="{axis_color}" stroke-width="{preset.axis_width_pt:.2f}"/>'
        )
        tick_markup.append(
            f'<text x="{x:.2f}" y="{plot_top + plot_height + 22:.2f}" text-anchor="middle" '
            f'font-size="{preset.tick_font_pt:.1f}pt">{_format_tick(tick)}</text>'
        )
    for tick in y_ticks:
        y = sy(tick)
        tick_markup.append(
            f'<line x1="{plot_left - 5:.2f}" y1="{y:.2f}" x2="{plot_left:.2f}" y2="{y:.2f}" '
            f'stroke="{axis_color}" stroke-width="{preset.axis_width_pt:.2f}"/>'
        )
        tick_markup.append(
            f'<text x="{plot_left - 10:.2f}" y="{y + 3:.2f}" text-anchor="end" '
            f'font-size="{preset.tick_font_pt:.1f}pt">{_format_tick(tick)}</text>'
        )

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{preset.width_in:.3f}in" height="{preset.height_in:.3f}in" viewBox="0 0 {width_px} {height_px}" role="img" aria-label="{escaped_title}">
  <title>{escaped_title}</title>
  <desc>Publication-style theoretical powder XRD profile exported by CIF2Peaks. Preset: {html.escape(preset_name)}; dpi: {preset.dpi}.</desc>
  <rect width="100%" height="100%" fill="#ffffff"/>
  <g font-family="{html.escape(preset.font_family)}" fill="{axis_color}">
    <text x="{width_px / 2:.2f}" y="{preset.title_font_pt * 2.0:.2f}" text-anchor="middle" font-size="{preset.title_font_pt:.1f}pt">{escaped_title}</text>
    <line x1="{plot_left:.2f}" y1="{plot_top:.2f}" x2="{plot_left:.2f}" y2="{plot_top + plot_height:.2f}" stroke="{axis_color}" stroke-width="{preset.axis_width_pt:.2f}"/>
    <line x1="{plot_left:.2f}" y1="{plot_top + plot_height:.2f}" x2="{plot_left + plot_width:.2f}" y2="{plot_top + plot_height:.2f}" stroke="{axis_color}" stroke-width="{preset.axis_width_pt:.2f}"/>
    {"".join(tick_markup)}
    <text x="{plot_left + plot_width / 2:.2f}" y="{height_px - 12:.2f}" text-anchor="middle" font-size="{preset.label_font_pt:.1f}pt">2θ (°)</text>
    <text x="16" y="{plot_top + plot_height / 2:.2f}" transform="rotate(-90 16 {plot_top + plot_height / 2:.2f})" text-anchor="middle" font-size="{preset.label_font_pt:.1f}pt">Intensity (a.u.)</text>
    <polyline points="{_polyline(profile_points)}" fill="none" stroke="{line_color}" stroke-width="{preset.line_width_pt:.2f}" stroke-linecap="round" stroke-linejoin="round"/>
  </g>
</svg>
'''
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return path


def _path_chunks(points: Sequence[tuple[float, float]], move_command: str, line_command: str) -> list[str]:
    if not points:
        return []
    chunks = [f"{points[0][0]:.2f} {points[0][1]:.2f} {move_command}"]
    chunks.extend(f"{x:.2f} {y:.2f} {line_command}" for x, y in points[1:])
    return chunks


def export_xrd_pattern_eps(
    result: XRDResult,
    output_path: str | Path,
    *,
    title: str = "Theoretical XRD pattern",
    preset_name: str = "publication",
) -> Path:
    preset = _preset(preset_name)
    geometry = _profile_plot_geometry(result, preset, 72.0)
    width = float(geometry["width"])
    height = float(geometry["height"])
    plot_left = float(geometry["plot_left"])
    plot_bottom = float(geometry["plot_bottom"])
    plot_width = float(geometry["plot_width"])
    plot_height = float(geometry["plot_height"])
    points = geometry["points"]
    sx = geometry["sx"]
    sy = geometry["sy"]
    x_ticks = geometry["x_ticks"]
    y_ticks = geometry["y_ticks"]
    red, green, blue = _rgb01(preset.color_cycle[0])
    safe_title = _ascii_plot_title(title)

    lines = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%BoundingBox: 0 0 {int(np.ceil(width))} {int(np.ceil(height))}",
        "%%Creator: CIF2Peaks",
        f"%%Title: {_ps_escape(safe_title)}",
        "%%XLabel: 2theta (deg)",
        "%%YLabel: Intensity (a.u.)",
        "%%EndComments",
        "/Helvetica findfont 8 scalefont setfont",
        "1 1 1 setrgbcolor",
        f"0 0 {width:.2f} {height:.2f} rectfill",
        "0.133 0.133 0.133 setrgbcolor",
        f"/Helvetica findfont {preset.title_font_pt:.2f} scalefont setfont",
        f"{width / 2:.2f} {height - preset.title_font_pt * 1.8:.2f} moveto ({_ps_escape(safe_title)}) dup stringwidth pop 2 div neg 0 rmoveto show",
        f"{preset.axis_width_pt:.2f} setlinewidth",
        f"{plot_left:.2f} {plot_bottom:.2f} moveto {plot_left:.2f} {plot_bottom + plot_height:.2f} lineto stroke",
        f"{plot_left:.2f} {plot_bottom:.2f} moveto {plot_left + plot_width:.2f} {plot_bottom:.2f} lineto stroke",
        f"/Helvetica findfont {preset.tick_font_pt:.2f} scalefont setfont",
    ]
    for tick in x_ticks:
        x = sx(float(tick))
        label = _format_tick(float(tick))
        lines.extend(
            [
                f"{x:.2f} {plot_bottom:.2f} moveto {x:.2f} {plot_bottom - 4:.2f} lineto stroke",
                f"{x:.2f} {plot_bottom - 15:.2f} moveto ({_ps_escape(label)}) dup stringwidth pop 2 div neg 0 rmoveto show",
            ]
        )
    for tick in y_ticks:
        y = sy(float(tick))
        label = _format_tick(float(tick))
        lines.extend(
            [
                f"{plot_left:.2f} {y:.2f} moveto {plot_left - 4:.2f} {y:.2f} lineto stroke",
                f"{plot_left - 8:.2f} {y - 2:.2f} moveto ({_ps_escape(label)}) dup stringwidth pop neg 0 rmoveto show",
            ]
        )
    lines.extend(
        [
            f"/Helvetica findfont {preset.label_font_pt:.2f} scalefont setfont",
            f"{plot_left + plot_width / 2:.2f} 10 moveto (2theta \\(deg\\)) dup stringwidth pop 2 div neg 0 rmoveto show",
            "gsave",
            f"12 {plot_bottom + plot_height / 2:.2f} translate 90 rotate",
            "(Intensity \\(a.u.\\)) dup stringwidth pop 2 div neg 0 rmoveto show",
            "grestore",
            f"{red:.4f} {green:.4f} {blue:.4f} setrgbcolor",
            f"{preset.line_width_pt:.2f} setlinewidth",
            "newpath",
            *_path_chunks(points, "moveto", "lineto"),
            "stroke",
            "showpage",
            "%%EOF",
        ]
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def export_xrd_pattern_pdf(
    result: XRDResult,
    output_path: str | Path,
    *,
    title: str = "Theoretical XRD pattern",
    preset_name: str = "publication",
) -> Path:
    preset = _preset(preset_name)
    geometry = _profile_plot_geometry(result, preset, 72.0)
    width = float(geometry["width"])
    height = float(geometry["height"])
    plot_left = float(geometry["plot_left"])
    plot_bottom = float(geometry["plot_bottom"])
    plot_width = float(geometry["plot_width"])
    plot_height = float(geometry["plot_height"])
    points = geometry["points"]
    sx = geometry["sx"]
    sy = geometry["sy"]
    x_ticks = geometry["x_ticks"]
    y_ticks = geometry["y_ticks"]
    red, green, blue = _rgb01(preset.color_cycle[0])
    safe_title = _ascii_plot_title(title)

    stream_lines = [
        "% XLabel: 2theta (deg)",
        "% YLabel: Intensity (a.u.)",
        f"% Title: {_pdf_escape(safe_title)}",
        "1 1 1 rg",
        f"0 0 {width:.2f} {height:.2f} re f",
        "0.133 0.133 0.133 RG",
        "0.133 0.133 0.133 rg",
        f"BT /F1 {preset.title_font_pt:.2f} Tf {width / 2 - len(safe_title) * preset.title_font_pt * 0.25:.2f} {height - preset.title_font_pt * 1.8:.2f} Td ({_pdf_escape(safe_title)}) Tj ET",
        f"{preset.axis_width_pt:.2f} w",
        f"{plot_left:.2f} {plot_bottom:.2f} m {plot_left:.2f} {plot_bottom + plot_height:.2f} l S",
        f"{plot_left:.2f} {plot_bottom:.2f} m {plot_left + plot_width:.2f} {plot_bottom:.2f} l S",
        f"BT /F1 {preset.tick_font_pt:.2f} Tf",
    ]
    for tick in x_ticks:
        x = sx(float(tick))
        label = _format_tick(float(tick))
        stream_lines.append(f"ET {x:.2f} {plot_bottom:.2f} m {x:.2f} {plot_bottom - 4:.2f} l S BT /F1 {preset.tick_font_pt:.2f} Tf {x - len(label) * 2:.2f} {plot_bottom - 15:.2f} Td ({_pdf_escape(label)}) Tj")
    for tick in y_ticks:
        y = sy(float(tick))
        label = _format_tick(float(tick))
        stream_lines.append(f"ET {plot_left:.2f} {y:.2f} m {plot_left - 4:.2f} {y:.2f} l S BT /F1 {preset.tick_font_pt:.2f} Tf {plot_left - 12 - len(label) * 4:.2f} {y - 2:.2f} Td ({_pdf_escape(label)}) Tj")
    stream_lines.extend(
        [
            "ET",
            f"BT /F1 {preset.label_font_pt:.2f} Tf {plot_left + plot_width / 2 - 25:.2f} 10 Td (2theta \\(deg\\)) Tj ET",
            f"BT /F1 {preset.label_font_pt:.2f} Tf 12 {plot_bottom + plot_height / 2 - 30:.2f} Td (Intensity \\(a.u.\\)) Tj ET",
            f"{red:.4f} {green:.4f} {blue:.4f} RG",
            f"{preset.line_width_pt:.2f} w",
            *_path_chunks(points, "m", "l"),
            "S",
        ]
    )
    stream = "\n".join(stream_lines).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>".encode("ascii"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode("ascii"))
        content.extend(obj)
        content.extend(b"\nendobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(content))
    return path
