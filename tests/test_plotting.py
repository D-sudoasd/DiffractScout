"""Publication figure export tests."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from diffractscout.models import AnalysisSettings
from diffractscout.pipeline import analyze_cifs
from diffractscout.plotting import (
    FIGURE_EXPORT_PRESETS,
    export_phase_figures,
    export_xrd_pattern_svg,
)


def test_export_svg_from_synthetic_arrays(tmp_path: Path) -> None:
    two_theta = np.linspace(10.0, 90.0, 401)
    intensity = np.exp(-0.5 * ((two_theta - 38.5) / 0.4) ** 2) * 100.0
    path = tmp_path / "pattern.svg"
    written = export_xrd_pattern_svg(
        path,
        two_theta_grid=two_theta,
        intensity_profile=intensity,
        title="Synthetic FCC Al",
        preset_name="publication",
    )
    assert written == path
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<?xml")
    assert "polyline" in text
    assert "Synthetic FCC Al" in text


def test_export_phase_figures_from_analysis(demo_inputs: Path, tmp_path: Path) -> None:
    result = analyze_cifs(
        [demo_inputs],
        tmp_path / "bundle",
        settings=AnalysisSettings(include_elasticity=False, include_figures=False),
        include_excel=False,
    )
    analysis = result.analyses[0]
    out = tmp_path / "figs"
    paths = export_phase_figures(
        analysis,
        out,
        preset="publication",
        formats=("svg", "png"),
    )
    assert len(paths) == 2
    assert all(path.is_file() for path in paths)
    assert any(path.suffix == ".svg" for path in paths)
    assert any(path.suffix == ".png" for path in paths)
    svg_text = next(path for path in paths if path.suffix == ".svg").read_text(encoding="utf-8")
    assert "polyline" in svg_text
    assert analysis.phase_name in svg_text or "svg" in svg_text.lower()


def test_include_figures_writes_bundle_figures_and_manifest(
    demo_inputs: Path, tmp_path: Path
) -> None:
    output = tmp_path / "with-figures"
    result = analyze_cifs(
        [demo_inputs],
        output,
        settings=AnalysisSettings(include_elasticity=False, include_figures=True),
        include_excel=False,
    )
    assert len(result.analyses) == 1
    figures = list((output / "figures").glob("*.svg"))
    assert figures, "expected figures/*.svg in the result bundle"
    assert all(path.is_file() for path in figures)
    assert list((output / "figures").glob("*.png")), "expected figures/*.png alongside SVG"

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    figure_entries = [row for row in manifest["files"] if row["path"].startswith("figures/")]
    assert figure_entries
    assert all(row["role"] == "figure" for row in figure_entries)


def test_unknown_preset_and_format_raise(demo_inputs: Path, tmp_path: Path) -> None:
    result = analyze_cifs(
        [demo_inputs],
        tmp_path / "bundle",
        settings=AnalysisSettings(include_elasticity=False),
        include_excel=False,
    )
    analysis = result.analyses[0]
    with pytest.raises(ValueError, match="Unknown figure export preset"):
        export_phase_figures(analysis, tmp_path / "bad-preset", preset="not-a-preset")
    with pytest.raises(ValueError, match="Unknown figure format"):
        export_phase_figures(analysis, tmp_path / "bad-fmt", formats=("webp",))


def test_all_named_presets_are_registered() -> None:
    expected = {"publication", "single_column", "double_column", "presentation", "raw_inspection"}
    assert expected.issubset(FIGURE_EXPORT_PRESETS)
