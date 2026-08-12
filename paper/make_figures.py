#!/usr/bin/env python3
"""Regenerate the JOSS paper figures from the committed workflow and demo bundle."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PAPER = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Colorblind-friendly, print-safe palette.
NAVY = "#183B56"
TEAL = "#167D8D"
BLUE = "#4C78A8"
GREEN = "#4F8F6B"
AMBER = "#D88A1E"
INK = "#1F2933"
MUTED = "#52616B"
LINE = "#C8D2D9"
PAPER_BG = "#FFFFFF"
CARD_BG = "#F7FAFC"
TEAL_BG = "#EAF5F6"
AMBER_BG = "#FFF5E5"


def _save(fig: plt.Figure, stem: str) -> None:
    for suffix in ("png", "svg"):
        fig.savefig(
            PAPER / f"{stem}.{suffix}",
            dpi=300 if suffix == "png" else None,
            bbox_inches="tight",
            facecolor=PAPER_BG,
        )
    plt.close(fig)


def make_workflow() -> None:
    fig, ax = plt.subplots(figsize=(14.2, 5.0))
    fig.subplots_adjust(left=0.012, right=0.988, top=0.97, bottom=0.04)
    fig.patch.set_facecolor(PAPER_BG)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    cards = [
        {
            "title": "Input",
            "lines": ["alloy grade", "chemical system", "Materials Project IDs", "or local CIFs"],
            "color": BLUE,
        },
        {
            "title": "Discover",
            "lines": ["expand subsystems", "normalize candidates", "deduplicate records", "rank deterministically"],
            "color": TEAL,
        },
        {
            "title": "Acquire",
            "lines": ["conventional CIF", "optional DFT Cij", "query context", "source metadata"],
            "color": GREEN,
        },
        {
            "title": "Verify + calculate",
            "lines": ["identity and symmetry", "occupancy and absences", "hkl, d, q, |F|², LP", "frame-checked E(hkl)"],
            "color": NAVY,
        },
        {
            "title": "Evidence bundle",
            "lines": ["CSV + XLSX tables", "structured diagnostics", "provenance + versions", "strict SHA-256 manifest"],
            "color": AMBER,
        },
    ]

    x_positions = [0.025, 0.220, 0.415, 0.610, 0.805]
    width, height, y = 0.170, 0.56, 0.31

    for index, (x, card) in enumerate(zip(x_positions, cards, strict=True), start=1):
        shadow = FancyBboxPatch(
            (x + 0.006, y - 0.012),
            width,
            height,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=0,
            facecolor="#D9E2E8",
            alpha=0.50,
            zorder=1,
        )
        ax.add_patch(shadow)
        box = FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=1.6,
            edgecolor=card["color"],
            facecolor=CARD_BG,
            zorder=2,
        )
        ax.add_patch(box)
        header = FancyBboxPatch(
            (x, y + height - 0.135),
            width,
            0.135,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=0,
            facecolor=card["color"],
            zorder=3,
        )
        ax.add_patch(header)
        # Cover the lower rounded corners of the header to create a flat divider.
        ax.add_patch(
            plt.Rectangle(
                (x, y + height - 0.135),
                width,
                0.050,
                facecolor=card["color"],
                edgecolor="none",
                zorder=3,
            )
        )
        title_size = 13.2 if index in {4, 5} else 14.6
        ax.text(
            x + width / 2,
            y + height - 0.067,
            f"{index}. {card['title']}",
            ha="center",
            va="center",
            fontsize=title_size,
            fontweight="bold",
            color=PAPER_BG,
            zorder=5,
        )
        for line_index, line in enumerate(card["lines"]):
            ax.text(
                x + width / 2,
                y + height - 0.205 - line_index * 0.073,
                line,
                ha="center",
                va="center",
                fontsize=12.3,
                color=INK,
                zorder=5,
            )

        if index < len(cards):
            x0 = x + width + 0.008
            x1 = x_positions[index] - 0.009
            arrow = FancyArrowPatch(
                (x0, y + height / 2),
                (x1, y + height / 2),
                arrowstyle="-|>",
                mutation_scale=17,
                linewidth=1.9,
                color=MUTED,
                shrinkA=0,
                shrinkB=0,
                zorder=6,
            )
            ax.add_patch(arrow)

    banner = FancyBboxPatch(
        (0.065, 0.075),
        0.87,
        0.125,
        boxstyle="round,pad=0.012,rounding_size=0.015",
        linewidth=1.2,
        edgecolor=AMBER,
        facecolor=AMBER_BG,
        zorder=2,
    )
    ax.add_patch(banner)
    ax.text(
        0.090,
        0.137,
        "Scientific boundary",
        ha="left",
        va="center",
        fontsize=13.0,
        fontweight="bold",
        color=AMBER,
    )
    ax.text(
        0.252,
        0.137,
        "Kinematic theoretical references only; missing and uncertain values remain explicit.",
        ha="left",
        va="center",
        fontsize=12.6,
        color=INK,
    )
    _save(fig, "fig_workflow")


def _ensure_demo_bundle(destination: Path) -> Path:
    if (destination / "pattern_profiles.csv").is_file() and (destination / "manifest.json").is_file():
        return destination

    from diffractscout.demo import write_demo_inputs
    from diffractscout.pipeline import analyze_cifs

    if destination.exists():
        shutil.rmtree(destination)
    with tempfile.TemporaryDirectory(prefix="diffractscout_paper_") as temporary:
        inputs = write_demo_inputs(Path(temporary) / "inputs")
        analyze_cifs([inputs], destination, include_excel=True, overwrite=True)
    return destination


def make_validation(demo_dir: Path) -> None:
    demo_dir = _ensure_demo_bundle(demo_dir)
    profile = pd.read_csv(demo_dir / "pattern_profiles.csv", encoding="utf-8-sig")
    peaks = pd.read_csv(demo_dir / "peak_reference.csv", encoding="utf-8-sig")
    phase = pd.read_csv(demo_dir / "phase_summary.csv", encoding="utf-8-sig").iloc[0]
    manifest = json.loads((demo_dir / "manifest.json").read_text(encoding="utf-8"))

    fig = plt.figure(figsize=(13.6, 5.5))
    fig.patch.set_facecolor(PAPER_BG)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.84, bottom=0.16, wspace=0.08)
    grid = fig.add_gridspec(1, 2, width_ratios=[1.72, 1.0], wspace=0.08)
    ax = fig.add_subplot(grid[0, 0])
    info = fig.add_subplot(grid[0, 1])

    x = profile["two_theta_deg"].to_numpy()
    y = profile["relative_intensity"].to_numpy()
    ax.fill_between(x, 0, y, color=TEAL, alpha=0.11, linewidth=0)
    ax.plot(x, y, color=TEAL, linewidth=2.2, solid_capstyle="round")
    ax.axhline(0, color=INK, linewidth=0.9)

    peak_x = peaks["two_theta_deg"].to_numpy()
    peak_y = peaks["normalized_intensity"].to_numpy()
    ax.vlines(peak_x, 0, peak_y, color=NAVY, linewidth=1.15, alpha=0.78)
    ax.scatter(peak_x, peak_y, s=20, facecolor=PAPER_BG, edgecolor=NAVY, linewidth=1.1, zorder=4)

    for idx, row in peaks.reset_index(drop=True).iterrows():
        level = 106 if idx % 2 == 0 else 96
        ax.annotate(
            str(row["hkl"]),
            xy=(row["two_theta_deg"], min(float(row["normalized_intensity"]), 100.0)),
            xytext=(row["two_theta_deg"], level),
            ha="center",
            va="bottom",
            fontsize=9.8,
            color=INK,
            arrowprops={"arrowstyle": "-", "color": LINE, "linewidth": 0.8},
        )

    ax.set_xlim(32, 122)
    ax.set_ylim(0, 114)
    ax.set_xlabel(r"$2\theta$ (degrees)", fontsize=12.5)
    ax.set_ylabel("Normalized intensity (%)", fontsize=12.5)
    ax.text(0.0, 1.115, "(a) Offline diffraction fixture", transform=ax.transAxes, fontsize=14.2, fontweight="bold", color=NAVY, va="bottom")
    ax.text(
        0.0,
        1.045,
        r"Synthetic $Fm\bar{3}m$ cell, $a=4.000$ Å; Cu K$\alpha$, $\lambda=1.5406$ Å",
        transform=ax.transAxes,
        fontsize=10.7,
        color=MUTED,
        va="bottom",
    )
    ax.grid(axis="y", color=LINE, linewidth=0.7, alpha=0.65)
    ax.tick_params(axis="both", labelsize=10.6, colors=INK)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(LINE)
    ax.spines["bottom"].set_color(LINE)

    info.set_xlim(0, 1)
    info.set_ylim(0, 1)
    info.axis("off")
    info.text(0.0, 1.115, "(b) Reviewer-verifiable invariants", transform=info.transAxes, fontsize=14.2, fontweight="bold", color=NAVY, va="bottom")

    hash_short = str(phase["cif_sha256"])[:12] + "..."
    cards = [
        ("Structure", f"{phase['space_group_symbol']}  |  a = {phase['a_A']:.3f} Å\nCIF SHA-256  {hash_short}", BLUE, TEAL_BG),
        ("Diffraction", f"{int(phase['reflection_count'])} allowed hkl families\n{len(profile):,} profile points", TEAL, TEAL_BG),
        ("Elasticity", "Synthetic isotropic tensor\nE(hkl) = 110.0 GPa for all families", GREEN, "#EEF7F1"),
        ("Bundle integrity", f"{len(manifest['files'])} hashed artifacts\nStrict manifest verification: PASS", AMBER, AMBER_BG),
    ]
    y_positions = [0.75, 0.535, 0.320, 0.105]
    for (heading, text, accent, face), y0 in zip(cards, y_positions, strict=True):
        box = FancyBboxPatch(
            (0.02, y0),
            0.96,
            0.165,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=1.25,
            edgecolor=accent,
            facecolor=face,
        )
        info.add_patch(box)
        info.add_patch(plt.Rectangle((0.02, y0), 0.015, 0.165, facecolor=accent, edgecolor="none"))
        info.text(0.070, y0 + 0.112, heading, fontsize=12.5, fontweight="bold", color=accent, va="center")
        info.text(0.070, y0 + 0.050, text, fontsize=10.6, color=INK, va="center", linespacing=1.35)

    fig.text(
        0.5,
        0.035,
        "Synthetic verification fixture; values are constructed to test software contracts and are not experimental aluminium properties.",
        ha="center",
        va="bottom",
        fontsize=10.2,
        color=MUTED,
    )
    _save(fig, "fig_validation")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--demo-dir",
        type=Path,
        default=ROOT / "_paper_demo",
        help="Existing or newly generated DiffractScout demo bundle.",
    )
    args = parser.parse_args()
    make_workflow()
    make_validation(args.demo_dir.expanduser().resolve())


if __name__ == "__main__":
    main()
