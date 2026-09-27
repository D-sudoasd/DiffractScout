"""Reproducible publication graphics; no experimental measurements are synthesized."""

import argparse
import json
import tempfile
import pandas as pd
from pathlib import Path
import sys
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

INK = "#142C3D"
MUTED = "#516570"
RULE = "#CCD7DC"
ACCENT = "#087F8C"
LIGHT = "#EFF7F8"
WARM = "#B86B20"


def style():
    matplotlib.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans"],
            "font.size": 10,
            "axes.labelsize": 10,
            "axes.titlesize": 11,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "text.color": INK,
            "axes.labelcolor": INK,
            "axes.edgecolor": RULE,
            "axes.linewidth": 0.7,
            "lines.linewidth": 1.5,
            "svg.fonttype": "none",
            "svg.hashsalt": "publication-20260927",
            "pdf.fonttype": 42,
            "savefig.facecolor": "white",
        }
    )


def canvas(height=4.6):
    fig = plt.figure(figsize=(7.2, height), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1], xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    return fig, ax


def label(ax, x, y, text, size=10, weight="normal", color=INK, ha="left", va="center"):
    return ax.text(
        x, y, text, fontsize=size, fontweight=weight, color=color, ha=ha, va=va, linespacing=1.45
    )


def panel(ax, x, y, letter, title):
    label(ax, x, y, letter, 12, "bold", ACCENT)
    label(ax, x + 0.038, y, title, 11, "bold")


def box(ax, x, y, w, h, title, body="", accent=None, face=None, size=9.5):
    accent = ACCENT if accent is None else accent
    face = LIGHT if face is None else face
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0,rounding_size=0.012",
            linewidth=0.7,
            edgecolor=RULE,
            facecolor=face,
        )
    )
    ax.plot(
        [x + 0.015, x + 0.015],
        [y + 0.02, y + h - 0.02],
        color=accent,
        lw=2.1,
        solid_capstyle="round",
    )
    label(ax, x + 0.034, y + h - 0.037, title, 10, "bold", accent, va="top")
    if body:
        label(ax, x + 0.034, y + h - 0.099, body, size, va="top")


def arrow(ax, a, b, color=MUTED, style="-"):
    ax.add_patch(
        FancyArrowPatch(
            a,
            b,
            arrowstyle="-|>",
            mutation_scale=10,
            linewidth=1,
            color=color,
            linestyle=style,
            shrinkA=2,
            shrinkB=2,
        )
    )


def save(fig, folder, stem, formats=("png", "svg", "pdf")):
    folder.mkdir(parents=True, exist_ok=True)
    for ext in formats:
        meta = (
            {"Date": None}
            if ext == "svg"
            else ({"CreationDate": None, "ModDate": None} if ext == "pdf" else {})
        )
        fig.savefig(folder / f"{stem}.{ext}", dpi=450, metadata=meta)
    plt.close(fig)


def clean_axes(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(length=3, width=0.6, color=RULE)
    ax.grid(axis="y", color=RULE, linewidth=0.5, alpha=0.6)
    ax.set_axisbelow(True)


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
sys.path.insert(0, str(ROOT / "src"))
ACCENT = "#245AA5"
LIGHT = "#F0F5FC"


def make_workflow():
    fig, ax = canvas(4.1)
    panel(ax, 0.04, 0.94, "a", "From source structures to a reproducible reference")
    stages = [
        ("01  Define inputs", "Chemical system / IDs\nor local CIF files"),
        ("02  Resolve sources", "Normalize candidates\nRecord exact CIF identity"),
        ("03  Calculate", "Validate structure\nCompute indexed reflections"),
        ("04  Verify + export", "CSV / XLSX / JSON\nChecksummed result bundle"),
    ]
    for i, (title, body) in enumerate(stages):
        row, col = divmod(i, 2)
        x = 0.04 + col * 0.49
        y = 0.59 - row * 0.31
        box(ax, x, y, 0.43, 0.235, title, body, size=10)
    arrow(ax, (0.47, 0.705), (0.53, 0.705))
    arrow(ax, (0.745, 0.59), (0.745, 0.565))
    ax.plot([0.745, 0.255], [0.565, 0.565], color=MUTED, lw=1)
    arrow(ax, (0.255, 0.565), (0.255, 0.515))
    arrow(ax, (0.47, 0.395), (0.53, 0.395))
    ax.plot([0.04, 0.96], [0.205, 0.205], color=RULE, lw=0.8)
    label(ax, 0.04, 0.145, "Recorded throughout", 10, "bold", ACCENT)
    label(ax, 0.36, 0.145, "Source IDs · settings · diagnostics · missing-data states", 9.2)
    label(
        ax,
        0.04,
        0.055,
        "Kinematic theoretical references; no measured-pattern phase identification or refinement.",
        9,
        color=MUTED,
    )
    save(fig, PAPER, "fig_workflow")


def make_validation(demo):
    from diffractscout.validation import verify_bundle

    result = verify_bundle(demo)
    assert result["ok"], result
    profile = pd.read_csv(demo / "pattern_profiles.csv")
    peaks = pd.read_csv(demo / "peak_reference.csv")
    phase = pd.read_csv(demo / "phase_summary.csv").iloc[0]
    manifest = json.loads((demo / "manifest.json").read_text())
    modulus = peaks["young_modulus_hkl_normal_GPa"].astype(float)
    assert ((modulus - 110.0).abs() < 1e-6).all(), "Expected isotropic synthetic fixture"
    fig = plt.figure(figsize=(7.2, 4.6))
    ax = fig.add_axes([0.10, 0.39, 0.85, 0.45])
    x = profile["two_theta_deg"]
    y = profile["relative_intensity"]
    ax.fill_between(x, 0, y, color=ACCENT, alpha=0.08)
    ax.plot(x, y, color=ACCENT, lw=1.4, label="Display profile")
    ax.vlines(
        peaks["two_theta_deg"],
        0,
        peaks["normalized_intensity"],
        color=WARM,
        lw=0.85,
        label="Reflections",
    )
    for i, row in peaks.reset_index(drop=True).iterrows():
        ax.annotate(
            str(row["hkl"]),
            xy=(row["two_theta_deg"], row["normalized_intensity"]),
            xytext=(row["two_theta_deg"], 107 if i % 2 == 0 else 95),
            ha="center",
            fontsize=8.7,
            arrowprops={"arrowstyle": "-", "color": RULE, "lw": 0.7},
        )
    ax.set(
        xlim=(32, 122),
        ylim=(0, 119),
        xlabel=r"$2\theta$ (degrees)",
        ylabel="Relative intensity (%)",
    )
    ax.set_title("a   Synthetic FCC diffraction reference", loc="left", fontweight="bold", pad=20)
    ax.text(
        0,
        1.035,
        r"$Fm\overline{3}m$ · $a=4.000$ Å · Cu Kα, $\lambda=1.5406$ Å",
        transform=ax.transAxes,
        fontsize=9,
        color=MUTED,
    )
    clean_axes(ax)
    board = fig.add_axes([0, 0, 1, 1], xlim=(0, 1), ylim=(0, 1))
    board.axis("off")
    panel(board, 0.10, 0.265, "b", "Reproducible checks")
    values = [
        (f"{int(phase['reflection_count'])}", "allowed hkl families"),
        ("110.0 GPa", "isotropic E(hkl)"),
        (str(len(manifest["files"])), "hashed artifacts"),
    ]
    for i, (value, caption) in enumerate(values):
        xx = 0.10 + i * 0.30
        label(board, xx, 0.175, value, 17, "bold", ACCENT)
        label(board, xx, 0.115, caption, 9, color=MUTED)
        if i < 2:
            board.plot([xx + 0.265, xx + 0.265], [0.10, 0.21], color=RULE, lw=0.6)
    label(
        board,
        0.10,
        0.035,
        "Constructed verification fixture, not experimental material properties.",
        9,
        color=MUTED,
    )
    save(fig, PAPER, "fig_validation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-dir", type=Path)
    args = parser.parse_args()
    style()
    make_workflow()
    if args.demo_dir:
        make_validation(args.demo_dir.resolve())
    else:
        from diffractscout.demo import write_demo_inputs
        from diffractscout.pipeline import analyze_cifs

        with tempfile.TemporaryDirectory(prefix="diffractscout_figure_") as temp:
            inputs = write_demo_inputs(Path(temp) / "inputs")
            dest = Path(temp) / "results"
            analyze_cifs([inputs], dest, include_excel=True)
            make_validation(dest)


if __name__ == "__main__":
    main()
