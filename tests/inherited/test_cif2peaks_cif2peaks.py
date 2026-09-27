from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import textwrap

import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest

pytest.importorskip("pymatgen.core")

from diffractscout.compat.cif2peaks.batch import batch_export_peak_reference, export_output_paths
from diffractscout.compat.cif2peaks.exporters import (
    combined_peak_rows,
    export_peak_reference_csv,
    export_cif2peaks_json,
    export_cif2peaks_pattern_workbook,
    export_cif2peaks_workbook,
    pattern_profile_rows,
)
from diffractscout.compat.cif2peaks.elastic import ElasticConstants
from diffractscout.compat.cif2peaks.models import Cif2PeaksExportPayload, Cif2PeaksSettings
from diffractscout.compat.cif2peaks.service import Cif2PeaksService


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_CIF_DIR = ROOT / "examples" / "inherited_cif2peaks"
TI_BETA_CIF = EXAMPLES_CIF_DIR / "ti_beta_bcc_im3m.cif"
TI_NB_HCP_CIF = EXAMPLES_CIF_DIR / "ti_nb_hcp_p63mmc.cif"
TI_NB_ORTHO_CIF = EXAMPLES_CIF_DIR / "ti_nb_orthorhombic_cmcm_partial_occupancy.cif"

NI_OCCUPANCY_CIF = """
#======================================================================
# CRYSTAL DATA
#----------------------------------------------------------------------
data_VESTA_phase_1

_chemical_name_common                  'Ni                                   '
_cell_length_a                         3.598240
_cell_length_b                         3.598240
_cell_length_c                         3.598240
_cell_angle_alpha                      90.000000
_cell_angle_beta                       90.000000
_cell_angle_gamma                      90.000000
_cell_volume                           46.587601
_space_group_name_H-M_alt              'P 2 3'
_space_group_IT_number                 195

loop_
_space_group_symop_operation_xyz
   'x, y, z'
   '-x, -y, z'
   '-x, y, -z'
   'x, -y, -z'
   'z, x, y'
   'z, -x, -y'
   '-z, -x, y'
   '-z, x, -y'
   'y, z, x'
   '-y, z, -x'
   'y, -z, -x'
   '-y, -z, x'

loop_
   _atom_site_label
   _atom_site_occupancy
   _atom_site_fract_x
   _atom_site_fract_y
   _atom_site_fract_z
   _atom_site_adp_type
   _atom_site_U_iso_or_equiv
   _atom_site_type_symbol
   Ni1        1.0     0.000000     0.000000     -0.000000    Uiso  ? Ni
   Ni2        1.0     0.500000     0.500000     0.000000    Uiso  ? Ni
   Ni3        1.0     -0.000000     0.500000     0.500000    Uiso  ? Ni
   Ni4        1.0     0.500000     -0.000000     0.500000    Uiso  ? Ni
"""

MULTI_BLOCK_STANDARDIZED_CIF = """
data_sm_global
_audit_creation_method 'metadata only'

data_probe-standardized_unitcell
_cell_length_a 3.0
_cell_length_b 3.0
_cell_length_c 3.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'
_symmetry_Int_Tables_number 1
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0 0 0 1

data_probe-published_cell
_cell_length_a 4.0
_cell_length_b 4.0
_cell_length_c 4.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 2 3'
_symmetry_Int_Tables_number 195
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0 0 0 1

data_probe-niggli_reduced_cell
_cell_length_a 2.0
_cell_length_b 2.0
_cell_length_c 2.0
_cell_angle_alpha 60
_cell_angle_beta 60
_cell_angle_gamma 60
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
? ? ? ? ? ?
"""

MULTI_BLOCK_PUBLISHED_BEFORE_STANDARDIZED_CIF = """
data_sm_global
_audit_creation_method 'metadata only'

data_probe-published_cell
_cell_length_a 4.0
_cell_length_b 4.0
_cell_length_c 4.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 2 3'
_symmetry_Int_Tables_number 195
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0 0 0 1

data_probe-standardized_unitcell
_cell_length_a 3.0
_cell_length_b 3.0
_cell_length_c 3.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'
_symmetry_Int_Tables_number 1
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Si1 Si 0 0 0 1
"""


def _write_ni_occupancy_cif(path: Path) -> Path:
    path.write_text(textwrap.dedent(NI_OCCUPANCY_CIF).strip() + "\n", encoding="utf-8")
    return path


def _write_multi_block_standardized_cif(path: Path) -> Path:
    path.write_text(textwrap.dedent(MULTI_BLOCK_STANDARDIZED_CIF).strip() + "\n", encoding="utf-8")
    return path


def _write_multi_block_published_before_standardized_cif(path: Path) -> Path:
    path.write_text(textwrap.dedent(MULTI_BLOCK_PUBLISHED_BEFORE_STANDARDIZED_CIF).strip() + "\n", encoding="utf-8")
    return path


def _nb_hea_cif_paths() -> list[Path]:
    root = ROOT / "tests" / "private_fixtures" / "nb_hea"
    names = ["AlNi.cif", "Cr2Nb.cif", "FeCr.cif", "Ni.cif", "Ni3Al.cif"]
    found = {path.name: path for path in root.rglob("*.cif")} if root.exists() else {}
    paths = [found.get(name) for name in names]
    if any(path is None for path in paths):
        pytest.skip("Nb_HEA_peak_separation CIF fixtures are not available on this machine.")
    return [path for path in paths if path is not None]


def _zr_hydride_cif_paths() -> list[Path]:
    root = ROOT / "tests" / "private_fixtures" / "zr_hydride"
    names = [
        "\N{GREEK SMALL LETTER ALPHA}-Zr.cif",
        "\N{GREEK SMALL LETTER BETA}-Zr.cif",
        "\N{GREEK SMALL LETTER GAMMA}-ZrH.cif",
        "\N{GREEK SMALL LETTER DELTA}-ZrH1.66.cif",
    ]
    paths = [root / name for name in names]
    if any(not path.exists() for path in paths):
        pytest.skip("Zr/ZrH CIF fixtures are not available on this machine.")
    return paths


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = str(ROOT / "src")
    if env.get("PYTHONPATH"):
        pythonpath = pythonpath + os.pathsep + env["PYTHONPATH"]
    env["PYTHONPATH"] = pythonpath
    return env


def _worksheet_rows(workbook_path: Path, sheet_index: int) -> list[list[str]]:
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(workbook_path) as archive:
        xml = archive.read(f"xl/worksheets/sheet{sheet_index}.xml")
    root = ET.fromstring(xml)
    rows: list[list[str]] = []
    for row in root.findall(".//main:row", namespace):
        values: list[str] = []
        for cell in row.findall("main:c", namespace):
            inline = cell.find("main:is/main:t", namespace)
            numeric = cell.find("main:v", namespace)
            values.append("" if inline is None and numeric is None else ((inline.text or "") if inline is not None else numeric.text or ""))
        rows.append(values)
    return rows


def _workbook_sheet_names(workbook_path: Path) -> list[str]:
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(workbook_path) as archive:
        xml = archive.read("xl/workbook.xml")
    root = ET.fromstring(xml)
    return [sheet.attrib["name"] for sheet in root.findall(".//main:sheet", namespace)]


def _worksheet_rows_by_name(workbook_path: Path, sheet_name: str) -> list[list[str]]:
    sheet_names = _workbook_sheet_names(workbook_path)
    return _worksheet_rows(workbook_path, sheet_names.index(sheet_name) + 1)


def _worksheet_cell_styles(workbook_path: Path, sheet_index: int) -> list[list[str]]:
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(workbook_path) as archive:
        xml = archive.read(f"xl/worksheets/sheet{sheet_index}.xml")
    root = ET.fromstring(xml)
    styles: list[list[str]] = []
    for row in root.findall(".//main:row", namespace):
        styles.append([cell.attrib.get("s", "0") for cell in row.findall("main:c", namespace)])
    return styles


def _worksheet_column_widths(workbook_path: Path, sheet_index: int) -> dict[int, str]:
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(workbook_path) as archive:
        xml = archive.read(f"xl/worksheets/sheet{sheet_index}.xml")
    root = ET.fromstring(xml)
    widths: dict[int, str] = {}
    for column in root.findall(".//main:col", namespace):
        min_index = int(column.attrib["min"])
        max_index = int(column.attrib["max"])
        for index in range(min_index, max_index + 1):
            widths[index] = column.attrib["width"]
    return widths


















def test_cif2peaks_single_cif_peak_table_and_energy_shift() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    settings = Cif2PeaksSettings(input_mode="energy", energy_keV=8.0478, wavelength_A=1.5406)
    service.simulate_phase(phase, settings)
    assert phase.result is not None
    rows = combined_peak_rows([phase])
    assert rows
    first = rows[0]
    for key in ("d_A", "two_theta_current_deg", "q_1_over_A", "g_1_over_A", "multiplicity"):
        assert key in first

    high_energy_phase = service.load_phase(TI_BETA_CIF)
    service.simulate_phase(
        high_energy_phase,
        Cif2PeaksSettings(input_mode="energy", energy_keV=20.0, wavelength_A=1.5406),
    )
    assert high_energy_phase.result is not None
    assert high_energy_phase.result.peaks[0].two_theta_deg < phase.result.peaks[0].two_theta_deg
    assert np.isclose(high_energy_phase.result.peaks[0].d_spacing_A, phase.result.peaks[0].d_spacing_A)


def test_cif2peaks_rejects_invalid_scan_range() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)

    with pytest.raises(ValueError, match="2theta range"):
        service.simulate_phase(phase, Cif2PeaksSettings(two_theta_min_deg=80.0, two_theta_max_deg=20.0))


@pytest.mark.parametrize("step_deg", [0.0, -0.1, float("nan")])
def test_cif2peaks_rejects_invalid_scan_step(step_deg: float) -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)

    with pytest.raises(ValueError, match="step_deg"):
        service.simulate_phase(phase, Cif2PeaksSettings(step_deg=step_deg))


def test_combined_peak_rows_export_material_scattering_factor_r_hkl() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    settings = Cif2PeaksSettings()
    service.simulate_phase(phase, settings)

    rows = combined_peak_rows([phase])
    first = rows[0]
    r_hkl_headers = {
        "material_scattering_factor_R_hkl",
        "material_scattering_factor_R_hkl_no_lp",
        "inverse_material_scattering_factor_1_over_R_hkl_no_lp",
        "theoretical_intensity_unscaled",
        "cell_volume_A3",
        "lp_factor",
        "multiplicity_structure_factor_sq",
        "r_hkl_model_note",
    }

    assert r_hkl_headers <= set(first)
    assert np.isclose(max(row["relative_intensity"] for row in rows), 100.0)
    assert first["theoretical_intensity_unscaled"] > 0
    assert first["cell_volume_A3"] > 0
    assert first["lp_factor"] > 0
    assert np.isclose(
        first["material_scattering_factor_R_hkl"],
        first["theoretical_intensity_unscaled"] / first["cell_volume_A3"] ** 2,
    )
    assert np.isclose(
        first["multiplicity_structure_factor_sq"],
        first["theoretical_intensity_unscaled"] / first["lp_factor"],
    )
    assert np.isclose(
        first["material_scattering_factor_R_hkl_no_lp"],
        first["multiplicity_structure_factor_sq"] / first["cell_volume_A3"] ** 2,
    )
    assert np.isclose(
        first["inverse_material_scattering_factor_1_over_R_hkl_no_lp"],
        1.0 / first["material_scattering_factor_R_hkl_no_lp"],
    )
    assert np.isclose(
        first["material_scattering_factor_R_hkl"] / first["material_scattering_factor_R_hkl_no_lp"],
        first["lp_factor"],
    )
    assert "Debye-Waller" in first["r_hkl_model_note"]
    assert "not a Rietveld residual" in first["r_hkl_model_note"]
    assert "with LP" in first["r_hkl_model_note"]
    assert "no-LP" in first["r_hkl_model_note"]


def test_combined_peak_rows_export_quant_phase_analysis_metrics() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    settings = Cif2PeaksSettings()
    service.simulate_phase(phase, settings)

    rows = combined_peak_rows([phase])
    first = rows[0]
    quant_headers = {
        "inverse_material_scattering_factor_1_over_R_hkl",
        "phase_relative_R_hkl_pct",
        "phase_peak_rank_by_R_hkl",
        "phase_relative_R_hkl_no_lp_pct",
        "phase_peak_rank_by_R_hkl_no_lp",
        "phase_peak_rank_by_relative_intensity",
        "coincident_hkl_family_count",
        "is_multi_family_peak",
        "mean_structure_factor_sq_per_multiplicity",
        "mean_structure_factor_abs_per_multiplicity",
        "sin_theta",
        "cos_theta",
        "sin_theta_over_lambda_1_over_A",
        "sin2_theta_over_lambda2_1_over_A2",
        "phase_density_g_cm3",
        "phase_formula_weight_g_mol",
        "phase_cell_volume_A3",
    }

    assert quant_headers <= set(first)
    max_r_hkl = max(row["material_scattering_factor_R_hkl"] for row in rows)
    max_r_hkl_no_lp = max(row["material_scattering_factor_R_hkl_no_lp"] for row in rows)
    theta_rad = np.deg2rad(first["theta_deg"])
    wavelength_A = phase.result.metadata["wavelength_A"]
    ranked_by_r_hkl = sorted(rows, key=lambda row: row["material_scattering_factor_R_hkl"], reverse=True)
    ranked_by_r_hkl_no_lp = sorted(rows, key=lambda row: row["material_scattering_factor_R_hkl_no_lp"], reverse=True)
    ranked_by_intensity = sorted(rows, key=lambda row: row["relative_intensity"], reverse=True)

    assert np.isclose(
        first["inverse_material_scattering_factor_1_over_R_hkl"],
        1.0 / first["material_scattering_factor_R_hkl"],
    )
    assert np.isclose(
        first["phase_relative_R_hkl_pct"],
        100.0 * first["material_scattering_factor_R_hkl"] / max_r_hkl,
    )
    assert np.isclose(
        first["phase_relative_R_hkl_no_lp_pct"],
        100.0 * first["material_scattering_factor_R_hkl_no_lp"] / max_r_hkl_no_lp,
    )
    assert [row["phase_peak_rank_by_R_hkl"] for row in ranked_by_r_hkl] == list(range(1, len(rows) + 1))
    assert [row["phase_peak_rank_by_R_hkl_no_lp"] for row in ranked_by_r_hkl_no_lp] == list(range(1, len(rows) + 1))
    assert [row["phase_peak_rank_by_relative_intensity"] for row in ranked_by_intensity] == list(range(1, len(rows) + 1))
    assert first["coincident_hkl_family_count"] == len(first["family_hkls"])
    assert first["is_multi_family_peak"] is False
    assert np.isclose(
        first["mean_structure_factor_sq_per_multiplicity"],
        first["multiplicity_structure_factor_sq"] / first["multiplicity"],
    )
    assert np.isclose(
        first["mean_structure_factor_abs_per_multiplicity"],
        np.sqrt(first["mean_structure_factor_sq_per_multiplicity"]),
    )
    assert np.isclose(first["sin_theta"], np.sin(theta_rad))
    assert np.isclose(first["cos_theta"], np.cos(theta_rad))
    assert np.isclose(first["sin_theta_over_lambda_1_over_A"], np.sin(theta_rad) / wavelength_A)
    assert np.isclose(first["sin2_theta_over_lambda2_1_over_A2"], (np.sin(theta_rad) / wavelength_A) ** 2)
    assert np.isclose(first["phase_density_g_cm3"], phase.crystal.pymatgen_structure.density)
    assert np.isclose(first["phase_formula_weight_g_mol"], phase.crystal.pymatgen_structure.composition.weight)
    assert np.isclose(first["phase_cell_volume_A3"], first["cell_volume_A3"])


def test_combined_peak_rows_flag_multi_family_quant_peaks() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    settings = Cif2PeaksSettings()
    service.simulate_phase(phase, settings)
    assert phase.result is not None
    phase.result.peaks[0] = replace(phase.result.peaks[0], family_hkls=((1, 1, 0), (2, 0, 0)))

    row = combined_peak_rows([phase])[0]

    assert row["coincident_hkl_family_count"] == 2
    assert row["is_multi_family_peak"] is True


def test_r_hkl_columns_export_to_csv_json_excel_and_keep_pattern_scale(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    settings = Cif2PeaksSettings(two_theta_min_deg=0.0, two_theta_max_deg=80.0, step_deg=0.2)
    service.simulate_phase(phase, settings)
    payload = Cif2PeaksExportPayload([phase], settings)

    csv_output = tmp_path / "r_hkl.csv"
    export_peak_reference_csv(payload, csv_output)
    with csv_output.open("r", encoding="utf-8-sig", newline="") as handle:
        csv_row = next(csv.DictReader(handle))

    json_output = tmp_path / "r_hkl.json"
    export_cif2peaks_json(payload, json_output)
    json_row = json.loads(json_output.read_text(encoding="utf-8"))["phases"][0]["peaks"][0]

    workbook_output = tmp_path / "r_hkl.xlsx"
    export_cif2peaks_workbook(payload, workbook_output)
    combined_headers = _worksheet_rows_by_name(workbook_output, "Combined Peaks")[0]
    beginner_headers = _worksheet_rows_by_name(workbook_output, "推荐峰表")[0]
    summary_rows = _worksheet_rows_by_name(workbook_output, "Summary")
    guide_text = "\n".join("|".join(row) for row in _worksheet_rows_by_name(workbook_output, "使用说明"))
    pattern_rows = pattern_profile_rows(payload, axis_mode="two_theta")

    assert "material_scattering_factor_R_hkl" in csv_row
    assert float(csv_row["material_scattering_factor_R_hkl"]) > 0
    assert "material_scattering_factor_R_hkl_no_lp" in csv_row
    assert float(csv_row["material_scattering_factor_R_hkl_no_lp"]) > 0
    assert "material_scattering_factor_R_hkl" in json_row
    assert json_row["material_scattering_factor_R_hkl"] > 0
    assert "material_scattering_factor_R_hkl_no_lp" in json_row
    assert json_row["material_scattering_factor_R_hkl_no_lp"] > 0
    assert "material_scattering_factor_R_hkl" in combined_headers
    assert "material_scattering_factor_R_hkl_no_lp" in combined_headers
    assert "theoretical_intensity_unscaled" in combined_headers
    assert "R因子 R_hkl" in beginner_headers
    assert "R因子 R_hkl_no_LP" in beginner_headers
    assert "1/R_hkl_no_LP" in beginner_headers
    assert "未归一化理论强度" in beginner_headers
    assert "晶胞体积 (Å^3)" in beginner_headers
    assert "R因子说明" in beginner_headers
    assert ["R_hkl_definition", "R_hkl = I_unscaled / V_cell^2"] in summary_rows
    assert ["R_hkl_with_LP_definition", "R_hkl_with_LP = I_unscaled / V_cell^2"] in summary_rows
    assert ["R_hkl_no_LP_definition", "R_hkl_no_LP = (I_unscaled / LP) / V_cell^2"] in summary_rows
    assert "I_unscaled ≈ p_hkl |F_hkl|^2 LP" in guide_text
    assert "含 LP" in guide_text
    assert "去 LP" in guide_text
    assert "pyFAI" in guide_text
    assert "已校正积分强度推荐 no-LP" in guide_text
    assert "不是 Rietveld" in guide_text
    assert np.isclose(max(row["relative_intensity"] for row in pattern_rows), 100.0)


def test_quant_phase_analysis_columns_export_without_experimental_templates(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    settings = Cif2PeaksSettings(two_theta_min_deg=0.0, two_theta_max_deg=80.0, step_deg=0.2)
    service.simulate_phase(phase, settings)
    payload = Cif2PeaksExportPayload([phase], settings)

    csv_output = tmp_path / "quant.csv"
    export_peak_reference_csv(payload, csv_output)
    with csv_output.open("r", encoding="utf-8-sig", newline="") as handle:
        csv_row = next(csv.DictReader(handle))

    json_output = tmp_path / "quant.json"
    export_cif2peaks_json(payload, json_output)
    json_row = json.loads(json_output.read_text(encoding="utf-8"))["phases"][0]["peaks"][0]

    workbook_output = tmp_path / "quant.xlsx"
    export_cif2peaks_workbook(payload, workbook_output)
    combined_headers = _worksheet_rows_by_name(workbook_output, "Combined Peaks")[0]
    beginner_headers = _worksheet_rows_by_name(workbook_output, "推荐峰表")[0]
    guide_text = "\n".join("|".join(row) for row in _worksheet_rows_by_name(workbook_output, "使用说明"))
    exported_header_text = "|".join([*csv_row.keys(), *json_row.keys(), *combined_headers, *beginner_headers])
    quant_headers = {
        "inverse_material_scattering_factor_1_over_R_hkl",
        "inverse_material_scattering_factor_1_over_R_hkl_no_lp",
        "phase_relative_R_hkl_pct",
        "phase_peak_rank_by_R_hkl",
        "phase_relative_R_hkl_no_lp_pct",
        "phase_peak_rank_by_R_hkl_no_lp",
        "phase_peak_rank_by_relative_intensity",
        "coincident_hkl_family_count",
        "is_multi_family_peak",
        "mean_structure_factor_sq_per_multiplicity",
        "mean_structure_factor_abs_per_multiplicity",
        "sin_theta",
        "cos_theta",
        "sin_theta_over_lambda_1_over_A",
        "sin2_theta_over_lambda2_1_over_A2",
        "phase_density_g_cm3",
        "phase_formula_weight_g_mol",
        "phase_cell_volume_A3",
    }

    assert quant_headers <= set(csv_row)
    assert quant_headers <= set(json_row)
    assert quant_headers <= set(combined_headers)
    assert "1/R_hkl" in beginner_headers
    assert "1/R_hkl_no_LP" in beginner_headers
    assert "相内 R_hkl (%)" in beginner_headers
    assert "相内 R_hkl_no_LP (%)" in beginner_headers
    assert "密度 (g/cm³)" in beginner_headers
    assert "多族峰" in beginner_headers
    assert "实验峰积分误差" in guide_text
    assert "Rietveld 残差" in guide_text
    assert "experimental_integrated_intensity" not in exported_header_text
    assert "corrected_intensity" not in exported_header_text
    assert "overlap" not in exported_header_text.lower()


def test_hexagonal_hkl_labels_preserve_four_index_notation(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_NB_HCP_CIF)
    settings = Cif2PeaksSettings()
    service.simulate_phase(phase, settings)

    rows = combined_peak_rows([phase])

    assert rows[0]["hkl"] == "(1 0 -1 0)"
    assert rows[0]["family_label"] == "{1 0 -1 0}"
    assert rows[0]["h"] == 1
    assert rows[0]["k"] == 0
    assert rows[0]["i"] == -1
    assert rows[0]["l"] == 0
    assert "(0 0 0)" not in {row["hkl"] for row in rows}
    assert "(0 0 0 2)" in {row["hkl"] for row in rows}
    assert "(1 0 -1 1)" in {row["hkl"] for row in rows}

    csv_output = tmp_path / "hcp_hkl.csv"
    export_peak_reference_csv(Cif2PeaksExportPayload([phase], settings), csv_output)

    with csv_output.open("r", encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert csv_rows[0]["hkl"] == "(1 0 -1 0)"

    workbook_output = tmp_path / "hcp_hkl.xlsx"
    export_cif2peaks_workbook(Cif2PeaksExportPayload([phase], settings), workbook_output)

    combined_sheet = _worksheet_rows_by_name(workbook_output, "Combined Peaks")
    headers = combined_sheet[0]
    assert "i" in headers
    assert combined_sheet[1][headers.index("hkl")] == "(1 0 -1 0)"
    assert combined_sheet[1][headers.index("i")] == "-1"
    assert combined_sheet[1][headers.index("l")] == "0"


def test_hkl_plane_indices_convert_valid_miller_bravais_only() -> None:
    from diffractscout.compat.cif2peaks.hkl import plane_hkl_for_normal

    assert plane_hkl_for_normal((1, 2, 3)) == (1, 2, 3)
    assert plane_hkl_for_normal((1, 0, -1, 0)) == (1, 0, 0)
    with pytest.raises(ValueError, match="Miller-Bravais"):
        plane_hkl_for_normal((1, 0, 0, 0))


def test_cubic_hkl_labels_remain_three_index_notation() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    service.simulate_phase(phase, Cif2PeaksSettings())

    rows = combined_peak_rows([phase])
    first = rows[0]

    assert first["hkl"] == "(1 1 0)"
    assert first["family_label"] == "{1 1 0}"
    assert first["h"] == 1
    assert first["k"] == 1
    assert first["i"] is None
    assert first["l"] == 0
    assert not any("CIF reports" in warning for warning in phase.warning_messages)


def test_cubic_elastic_constants_compute_hkl_normal_young_moduli() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    assert phase.crystal is not None
    elastic = ElasticConstants.from_cubic(c11_GPa=250.0, c12_GPa=150.0, c44_GPa=100.0, source="test cubic")

    e100 = elastic.young_modulus_hkl_normal_GPa(phase.crystal.pymatgen_structure.lattice, (1, 0, 0))
    e110 = elastic.young_modulus_hkl_normal_GPa(phase.crystal.pymatgen_structure.lattice, (1, 1, 0))
    e111 = elastic.young_modulus_hkl_normal_GPa(phase.crystal.pymatgen_structure.lattice, (1, 1, 1))

    assert elastic.status == "valid"
    assert elastic.warnings == []
    assert e100 == pytest.approx(137.5, rel=1e-4)
    assert e110 > e100
    assert e111 > e110


def test_combined_peak_rows_include_elastic_modulus_when_cij_is_available() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    phase.elastic_constants = ElasticConstants.from_cubic(c11_GPa=250.0, c12_GPa=150.0, c44_GPa=100.0)
    service.simulate_phase(phase, Cif2PeaksSettings())

    rows = combined_peak_rows([phase])

    assert rows
    first = rows[0]
    assert first["hkl"] == "(1 1 0)"
    assert first["young_modulus_hkl_normal_GPa"] == pytest.approx(209.5238095, rel=1e-4)
    assert first["elastic_status"] == "valid"
    assert first["elastic_warning"] == ""


def test_four_index_hkil_rows_can_receive_hkl_normal_modulus() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_NB_HCP_CIF)
    phase.elastic_constants = ElasticConstants.from_cubic(c11_GPa=250.0, c12_GPa=150.0, c44_GPa=100.0)
    service.simulate_phase(phase, Cif2PeaksSettings())

    rows = combined_peak_rows([phase])
    direct_modulus = phase.elastic_constants.young_modulus_hkl_normal_GPa(phase.crystal.pymatgen_structure.lattice, (1, 0, 0))

    assert rows[0]["hkl"] == "(1 0 -1 0)"
    assert rows[0]["elastic_hkl_used"] == "(1 0 0)"
    assert rows[0]["young_modulus_hkl_normal_GPa"] == pytest.approx(direct_modulus)
    assert rows[0]["elastic_status"] == "valid"


def test_invalid_miller_bravais_hkil_leaves_modulus_blank_with_warning() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_NB_HCP_CIF)
    phase.elastic_constants = ElasticConstants.from_cubic(c11_GPa=250.0, c12_GPa=150.0, c44_GPa=100.0)
    service.simulate_phase(phase, Cif2PeaksSettings())
    assert phase.result is not None
    phase.result.peaks[0] = replace(phase.result.peaks[0], hkl=(1, 0, 0, 0))

    rows = combined_peak_rows([phase])

    assert rows[0]["young_modulus_hkl_normal_GPa"] == ""
    assert rows[0]["elastic_hkl_used"] == ""
    assert "Miller-Bravais" in rows[0]["elastic_warning"]


def test_multiple_hkl_families_export_primary_and_family_moduli() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    phase.elastic_constants = ElasticConstants.from_cubic(c11_GPa=250.0, c12_GPa=150.0, c44_GPa=100.0)
    service.simulate_phase(phase, Cif2PeaksSettings())
    assert phase.result is not None
    phase.result.peaks[0] = replace(phase.result.peaks[0], hkl=(1, 1, 0), family_hkls=((1, 1, 0), (2, 0, 0)))

    row = combined_peak_rows([phase])[0]

    assert row["elastic_hkl_used"] == "(1 1 0)"
    assert row["elastic_family_count"] == 2
    assert "(1 1 0)=" in row["elastic_family_moduli_GPa"]
    assert "(2 0 0)=" in row["elastic_family_moduli_GPa"]
    assert "multiple_hkl_families" in row["elastic_modulus_note"]


def test_invalid_elastic_constants_warn_without_blocking_peak_export() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    phase.elastic_constants = ElasticConstants.from_matrix(np.zeros((6, 6)), source="invalid singular")
    service.simulate_phase(phase, Cif2PeaksSettings())

    rows = combined_peak_rows([phase])

    assert rows
    assert rows[0]["young_modulus_hkl_normal_GPa"] == ""
    assert rows[0]["elastic_status"] == "invalid_elastic_constants"
    assert "singular" in rows[0]["elastic_warning"].lower() or "positive definite" in rows[0]["elastic_warning"].lower()


def test_workbook_exports_elastic_columns_and_constants_sheet(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = [service.load_phase(TI_BETA_CIF), service.load_phase(TI_NB_HCP_CIF)]
    phases[0].elastic_constants = ElasticConstants.from_cubic(
        c11_GPa=250.0,
        c12_GPa=150.0,
        c44_GPa=100.0,
        source="literature demo",
    )
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "elastic_export.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, settings), output)

    sheet_names = _workbook_sheet_names(output)
    assert "Elastic Constants" in sheet_names
    combined_rows = _worksheet_rows_by_name(output, "Combined Peaks")
    headers = combined_rows[0]
    assert "young_modulus_hkl_normal_GPa" in headers
    assert "elastic_status" in headers
    assert "elastic_warning" in headers
    assert "elastic_hkl_used" in headers
    assert "elastic_family_count" in headers
    assert "elastic_family_moduli_GPa" in headers
    assert "elastic_modulus_note" in headers
    modulus_index = headers.index("young_modulus_hkl_normal_GPa")
    status_index = headers.index("elastic_status")
    by_phase = {row[headers.index("phase_name")]: row for row in combined_rows[1:] if row}
    assert float(by_phase["ti_beta_bcc_im3m"][modulus_index]) > 0.0
    assert by_phase["ti_beta_bcc_im3m"][status_index] == "valid"
    assert by_phase["ti_nb_hcp_p63mmc"][modulus_index] == ""
    assert by_phase["ti_nb_hcp_p63mmc"][status_index] == "no_elastic_constants"

    beginner_rows = _worksheet_rows_by_name(output, "推荐峰表")
    assert "晶面法向杨氏模量 (GPa)" in beginner_rows[0]
    assert "弹性常数状态" in beginner_rows[0]

    elastic_sheet_index = sheet_names.index("Elastic Constants") + 1
    elastic_rows = _worksheet_rows(output, elastic_sheet_index)
    elastic_headers = elastic_rows[0]
    assert elastic_headers[:6] == ["phase_name", "cif_name", "elastic_status", "elastic_warning", "unit", "source"]
    assert "coordinate_frame" in elastic_headers
    assert elastic_rows[1][elastic_headers.index("elastic_status")] == "valid"
    assert elastic_rows[1][elastic_headers.index("C11")] == "250"
    assert elastic_rows[1][elastic_headers.index("source")] == "literature demo"
    assert elastic_rows[1][elastic_headers.index("coordinate_frame")] == "crystal_cartesian_from_cif_lattice"
    assert elastic_rows[2][elastic_headers.index("elastic_status")] == "no_elastic_constants"

    summary_rows = _worksheet_rows(output, 1)
    summary_header_index = next(index for index, row in enumerate(summary_rows) if row and row[0] == "phase_name")
    summary_header = summary_rows[summary_header_index]
    assert "elastic_status" in summary_header
    assert summary_rows[summary_header_index + 1][summary_header.index("elastic_status")] == "valid"
    assert summary_rows[summary_header_index + 2][summary_header.index("elastic_status")] == "no_elastic_constants"


def test_simple_gui_export_accepts_elastic_constants_for_selected_cifs(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import run_simple_gui_export

    cif_path = tmp_path / TI_BETA_CIF.name
    cif_path.write_bytes(TI_BETA_CIF.read_bytes())
    output = tmp_path / "gui_elastic.xlsx"

    result = run_simple_gui_export(
        [cif_path],
        output,
        elastic_constants={
            cif_path: ElasticConstants.from_cubic(c11_GPa=250.0, c12_GPa=150.0, c44_GPa=100.0, source="GUI input"),
        },
    )

    assert result.output_path == output
    combined_rows = _worksheet_rows_by_name(output, "Combined Peaks")
    headers = combined_rows[0]
    assert combined_rows[1][headers.index("elastic_status")] == "valid"
    assert float(combined_rows[1][headers.index("young_modulus_hkl_normal_GPa")]) > 0.0
    sheet_names = _workbook_sheet_names(output)
    elastic_rows = _worksheet_rows(output, sheet_names.index("Elastic Constants") + 1)
    assert elastic_rows[1][elastic_rows[0].index("source")] == "GUI input"


def test_gui_full_cij_matrix_parser_accepts_six_by_six_paste() -> None:
    from diffractscout.compat.cif2peaks.gui import _parse_full_cij_matrix

    pasted = """
    250 150 150 0 0 0
    150 250 150 0 0 0
    150 150 250 0 0 0
    0 0 0 100 0 0
    0 0 0 0 100 0
    0 0 0 0 0 100
    """

    elastic = _parse_full_cij_matrix(pasted, source="pasted matrix")

    assert elastic.status == "valid"
    assert elastic.source == "pasted matrix"
    assert elastic.stiffness_matrix_GPa[0, 0] == 250
    assert elastic.stiffness_matrix_GPa[5, 5] == 100


def test_gui_cij_table_values_parse_to_elastic_constants() -> None:
    from diffractscout.compat.cif2peaks.gui import _parse_cij_table_values

    values = [
        ["250", "150", "150", "0", "0", "0"],
        ["150", "250", "150", "0", "0", "0"],
        ["150", "150", "250", "0", "0", "0"],
        ["0", "0", "0", "100", "0", "0"],
        ["0", "0", "0", "0", "100", "0"],
        ["0", "0", "0", "0", "0", "100"],
    ]

    elastic = _parse_cij_table_values(values, source="table input")

    assert elastic.status == "valid"
    assert elastic.source == "table input"
    assert elastic.stiffness_matrix_GPa[0, 0] == 250
    assert elastic.stiffness_matrix_GPa[5, 5] == 100


@pytest.mark.parametrize(
    "pasted",
    [
        "250\t150\t150\t0\t0\t0\n150\t250\t150\t0\t0\t0\n150\t150\t250\t0\t0\t0\n0\t0\t0\t100\t0\t0\n0\t0\t0\t0\t100\t0\n0\t0\t0\t0\t0\t100",
        "250 150 150 0 0 0\n150 250 150 0 0 0\n150 150 250 0 0 0\n0 0 0 100 0 0\n0 0 0 0 100 0\n0 0 0 0 0 100",
        "250,150,150,0,0,0,150,250,150,0,0,0,150,150,250,0,0,0,0,0,0,100,0,0,0,0,0,0,100,0,0,0,0,0,0,100",
    ],
)
def test_gui_cij_paste_parser_accepts_common_matrix_formats(pasted: str) -> None:
    from diffractscout.compat.cif2peaks.gui import _parse_cij_paste_matrix

    values = _parse_cij_paste_matrix(pasted)

    assert values[0] == ["250", "150", "150", "0", "0", "0"]
    assert values[5] == ["0", "0", "0", "0", "0", "100"]


def test_gui_cij_table_rejects_incomplete_and_non_numeric_values() -> None:
    from diffractscout.compat.cif2peaks.gui import _parse_cij_paste_matrix, _parse_cij_table_values

    with pytest.raises(ValueError, match="6x6"):
        _parse_cij_paste_matrix("250 150 150")

    values = [["0" for _column in range(6)] for _row in range(6)]
    values[1][2] = "bad"
    with pytest.raises(ValueError, match="C23 must be a number"):
        _parse_cij_table_values(values)


def test_gui_cij_table_rejects_non_finite_values() -> None:
    from diffractscout.compat.cif2peaks.gui import _parse_cij_table_values

    values = [["1" for _column in range(6)] for _row in range(6)]
    values[0][0] = "inf"
    with pytest.raises(ValueError, match="C11 must be a finite number"):
        _parse_cij_table_values(values)

    values[0][0] = "1"
    values[5][5] = "nan"
    with pytest.raises(ValueError, match="C66 must be a finite number"):
        _parse_cij_table_values(values)


def test_gui_cubic_cij_rejects_non_finite_values() -> None:
    from diffractscout.compat.cif2peaks.gui import _parse_cubic_cij

    with pytest.raises(ValueError, match="C11 must be a finite number"):
        _parse_cubic_cij("nan 150 100")

    with pytest.raises(ValueError, match="C44 must be a finite number"):
        _parse_cubic_cij("250 150 -inf")


def test_gui_cubic_cij_fill_builds_full_table_values() -> None:
    from diffractscout.compat.cif2peaks.gui import _cubic_cij_table_values

    values = _cubic_cij_table_values("250, 150, 100")

    assert values == [
        ["250", "150", "150", "0", "0", "0"],
        ["150", "250", "150", "0", "0", "0"],
        ["150", "150", "250", "0", "0", "0"],
        ["0", "0", "0", "100", "0", "0"],
        ["0", "0", "0", "0", "100", "0"],
        ["0", "0", "0", "0", "0", "100"],
    ]


def test_gui_format_cij_table_values_round_trips_full_matrix() -> None:
    from diffractscout.compat.cif2peaks.gui import _format_cij_table_values

    elastic = ElasticConstants.from_matrix(
        [
            [250, 120, 110, 1, 2, 3],
            [120, 245, 115, 4, 5, 6],
            [110, 115, 240, 7, 8, 9],
            [1, 4, 7, 90, 10, 11],
            [2, 5, 8, 10, 95, 12],
            [3, 6, 9, 11, 12, 100],
        ]
    )

    values = _format_cij_table_values(elastic)

    assert values[0] == ["250", "120", "110", "1", "2", "3"]
    assert values[5] == ["3", "6", "9", "11", "12", "100"]


def test_cif2peaks_loads_occupancy_conflict_cif_with_warning(tmp_path: Path) -> None:
    cif_path = _write_ni_occupancy_cif(tmp_path / "Ni.cif")
    service = Cif2PeaksService()

    phase = service.load_phase(cif_path)
    service.simulate_phase(phase, Cif2PeaksSettings())

    assert phase.error is None
    assert phase.result is not None
    assert len(phase.result.peaks) == 8
    assert any("occupancy" in warning.lower() for warning in phase.warning_messages)


def test_cif2peaks_loads_standardized_unitcell_from_multi_block_cif(tmp_path: Path) -> None:
    cif_path = _write_multi_block_standardized_cif(tmp_path / "multi_block.cif")
    service = Cif2PeaksService()

    phase = service.load_phase(cif_path)

    assert phase.error is None
    assert phase.crystal is not None
    assert phase.crystal.validation_report.space_group_from_cif == "P 1"
    assert phase.crystal.detected_space_group_symbol == "Pm-3m"
    assert phase.display_space_group == "Pm-3m"
    assert phase.crystal.cell_parameters[:3] == (3.0, 3.0, 3.0)
    assert any("CIF reports P 1" in warning and "spglib detected Pm-3m" in warning for warning in phase.warning_messages)


def test_cif2peaks_uses_selected_structure_block_for_pymatgen_structure(tmp_path: Path) -> None:
    cif_path = _write_multi_block_published_before_standardized_cif(tmp_path / "multi_block_reordered.cif")
    service = Cif2PeaksService()

    phase = service.load_phase(cif_path)

    assert phase.error is None
    assert phase.crystal is not None
    assert phase.crystal.validation_report.space_group_from_cif == "P 1"
    assert phase.crystal.cell_parameters[:3] == (3.0, 3.0, 3.0)


def test_cif2peaks_exports_detected_space_group_and_preserves_cif_space_group(tmp_path: Path) -> None:
    cif_path = _write_multi_block_standardized_cif(tmp_path / "multi_block.cif")
    service = Cif2PeaksService()
    phase = service.load_phase(cif_path)
    settings = Cif2PeaksSettings()
    service.simulate_phase(phase, settings)

    rows = combined_peak_rows([phase])

    assert rows
    assert rows[0]["space_group"] == "Pm-3m"
    assert rows[0]["space_group_from_cif"] == "P 1"
    assert rows[0]["space_group_detected"] == "Pm-3m"

    csv_output = tmp_path / "space_groups.csv"
    export_peak_reference_csv(Cif2PeaksExportPayload([phase], settings), csv_output)
    with csv_output.open("r", encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert csv_rows[0]["space_group"] == "Pm-3m"
    assert csv_rows[0]["space_group_from_cif"] == "P 1"
    assert csv_rows[0]["space_group_detected"] == "Pm-3m"

    workbook_output = tmp_path / "space_groups.xlsx"
    export_cif2peaks_workbook(Cif2PeaksExportPayload([phase], settings), workbook_output)
    combined_sheet = _worksheet_rows_by_name(workbook_output, "Combined Peaks")
    headers = combined_sheet[0]
    assert "space_group_from_cif" in headers
    assert "space_group_detected" in headers
    assert combined_sheet[1][headers.index("space_group")] == "Pm-3m"
    assert combined_sheet[1][headers.index("space_group_from_cif")] == "P 1"
    assert combined_sheet[1][headers.index("space_group_detected")] == "Pm-3m"

    structure_sheet = _worksheet_rows_by_name(workbook_output, "Structure")
    structure_headers = structure_sheet[0]
    assert structure_sheet[1][structure_headers.index("space_group_from_cif")] == "P 1"
    assert structure_sheet[1][structure_headers.index("space_group_detected")] == "Pm-3m"
    assert structure_sheet[1][structure_headers.index("space_group_status")] == "mismatch"

    summary_rows = _worksheet_rows(workbook_output, 1)
    summary_header_index = next(index for index, row in enumerate(summary_rows) if row and row[0] == "phase_name")
    summary_header = summary_rows[summary_header_index]
    summary_data = summary_rows[summary_header_index + 1]
    assert summary_data[summary_header.index("space_group")] == "Pm-3m"
    assert summary_data[summary_header.index("space_group_from_cif")] == "P 1"
    assert summary_data[summary_header.index("space_group_detected")] == "Pm-3m"

    json_output = tmp_path / "space_groups.json"
    export_cif2peaks_json(Cif2PeaksExportPayload([phase], settings), json_output)
    data = json.loads(json_output.read_text(encoding="utf-8"))
    crystal = data["phases"][0]["crystal"]
    assert crystal["space_group"] == "Pm-3m"
    assert crystal["space_group_from_cif"] == "P 1"
    assert crystal["space_group_detected"] == "Pm-3m"


def test_cif2peaks_batch_loads_real_cifs_and_keeps_occupancy_warning() -> None:
    service = Cif2PeaksService()
    phases = service.load_phases(_nb_hea_cif_paths())
    service.simulate_phases(phases, Cif2PeaksSettings())

    by_name = {phase.cif_path.name: phase for phase in phases}
    assert list(by_name) == ["AlNi.cif", "Cr2Nb.cif", "FeCr.cif", "Ni.cif", "Ni3Al.cif"]
    expected_peak_counts = {
        "AlNi.cif": 12,
        "Cr2Nb.cif": 22,
        "FeCr.cif": 7,
        "Ni.cif": 8,
        "Ni3Al.cif": 86,
    }
    for name, expected_count in expected_peak_counts.items():
        phase = by_name[name]
        assert phase.error is None
        assert phase.result is not None
        assert len(phase.result.peaks) == expected_count
    assert any("occupancy" in warning.lower() for warning in by_name["Ni.cif"].warning_messages)


def test_cif2peaks_exports_simple_phase_hkl_d_two_theta_csv(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = service.load_phases(_nb_hea_cif_paths())
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "phase_hkl_d_2theta.csv"

    export_peak_reference_csv(Cif2PeaksExportPayload(phases, settings), output)

    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert {"phase_name", "cif_name", "formula", "space_group", "hkl", "d_A", "two_theta_deg"}.issubset(rows[0])
    assert {row["cif_name"] for row in rows} == {"AlNi.cif", "Cr2Nb.cif", "FeCr.cif", "Ni.cif", "Ni3Al.cif"}
    assert any(row["cif_name"] == "Ni.cif" and row["hkl"] == "(1 1 1)" for row in rows)
    assert all(float(row["d_A"]) > 0 and float(row["two_theta_deg"]) > 0 for row in rows)


def test_cif2peaks_batch_export_defaults_to_excel_from_many_cifs(tmp_path: Path) -> None:
    output = tmp_path / "many_cif_reference.xlsx"

    phases = batch_export_peak_reference(_nb_hea_cif_paths(), output)

    assert len(phases) == 5
    assert output.exists()
    headers = _worksheet_rows_by_name(output, "Combined Peaks")[0]
    expected_front = [
        "phase_name",
        "cif_name",
        "formula",
        "space_group",
        "hkl",
        "d_A",
        "two_theta_current_deg",
        "relative_intensity",
        "multiplicity",
        "warnings",
    ]
    assert headers[: len(expected_front)] == expected_front
    data_rows = _worksheet_rows_by_name(output, "Combined Peaks")[1:]
    assert len(data_rows) == sum(len(phase.result.peaks) for phase in phases if phase.result is not None)
    assert all(float(row[5]) > 0 and float(row[6]) > 0 for row in data_rows)


def test_cif2peaks_batch_export_zr_hydride_multi_block_cifs(tmp_path: Path) -> None:
    output = tmp_path / "zr_hydride_reference.xlsx"

    phases = batch_export_peak_reference(_zr_hydride_cif_paths(), output)

    assert len(phases) == 4
    assert output.exists()
    assert all(phase.error is None for phase in phases)
    assert all(phase.result is not None and len(phase.result.peaks) > 0 for phase in phases)
    headers = _worksheet_rows_by_name(output, "Combined Peaks")[0]
    for header in ("hkl", "d_A", "two_theta_current_deg", "relative_intensity"):
        assert header in headers
    data_rows = _worksheet_rows_by_name(output, "Combined Peaks")[1:]
    assert len(data_rows) == sum(len(phase.result.peaks) for phase in phases if phase.result is not None)
    assert {row[1] for row in data_rows} == {path.name for path in _zr_hydride_cif_paths()}
    assert all(float(row[5]) > 0 and float(row[6]) > 0 for row in data_rows)


def test_cif2peaks_batch_export_can_still_write_csv(tmp_path: Path) -> None:
    output = tmp_path / "many_cif_reference.csv"

    phases = batch_export_peak_reference(_nb_hea_cif_paths(), output)

    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(phases) == 5
    assert output.exists()
    assert len(rows) == sum(len(phase.result.peaks) for phase in phases if phase.result is not None)
    assert {row["phase_name"] for row in rows} >= {"AlNi", "Cr2Nb", "FeCr", "Ni", "Ni3Al"}


def test_pattern_workbook_exports_each_cif_and_combined_profile_rows(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = service.load_phases([TI_BETA_CIF, TI_NB_HCP_CIF])
    settings = Cif2PeaksSettings(two_theta_min_deg=0.0, two_theta_max_deg=60.0, step_deg=1.0)
    service.simulate_phases(phases, settings)
    output = tmp_path / "patterns.xlsx"

    export_cif2peaks_pattern_workbook(Cif2PeaksExportPayload(phases, settings), output, axis_mode="two_theta")

    assert _workbook_sheet_names(output) == ["Summary", "Combined Patterns", "ti_beta_bcc_im3m", "ti_nb_hcp_p63mmc"]
    rows = _worksheet_rows(output, 2)
    assert rows[0] == [
        "phase_name",
        "cif_name",
        "x_axis_mode",
        "x",
        "relative_intensity",
        "two_theta_deg",
        "d_A",
        "q_1_over_A",
        "g_1_over_A",
    ]
    data_rows = rows[1:]
    assert len(data_rows) == sum(len(phase.result.two_theta_grid) for phase in phases if phase.result is not None)
    assert {row[1] for row in data_rows} == {TI_BETA_CIF.name, TI_NB_HCP_CIF.name}
    assert all(row[2] == "two_theta" for row in data_rows)
    assert [float(row[3]) for row in data_rows[:3]] == [0.0, 1.0, 2.0]
    pattern_widths = _worksheet_column_widths(output, 2)
    assert pattern_widths[1] == "22"
    assert pattern_widths[2] == "30"
    assert pattern_widths[3] == "15"
    assert pattern_widths[5] == "17"
    assert pattern_widths[9] == "14"


def test_pattern_profile_rows_convert_selected_axis_and_skip_nonfinite_values() -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    settings = Cif2PeaksSettings(two_theta_min_deg=0.0, two_theta_max_deg=60.0, step_deg=1.0)
    service.simulate_phase(phase, settings)
    payload = Cif2PeaksExportPayload([phase], settings)

    two_theta_rows = pattern_profile_rows(payload, axis_mode="two_theta")
    d_rows = pattern_profile_rows(payload, axis_mode="d_spacing")
    q_rows = pattern_profile_rows(payload, axis_mode="q")
    g_rows = pattern_profile_rows(payload, axis_mode="g")

    assert [row["x"] for row in two_theta_rows[:3]] == [0.0, 1.0, 2.0]
    assert len(d_rows) == len(two_theta_rows) - 1
    assert d_rows[0]["two_theta_deg"] == 1.0
    theta = np.deg2rad(1.0 / 2.0)
    expected_d = settings.wavelength_A / (2.0 * np.sin(theta))
    expected_q = 4.0 * np.pi * np.sin(theta) / settings.wavelength_A
    assert np.isclose(d_rows[0]["x"], expected_d)
    assert np.isclose(q_rows[1]["x"], expected_q)
    assert np.isclose(g_rows[1]["x"], 1.0 / expected_d)
    assert all(np.isfinite(row["x"]) for row in d_rows)


def test_batch_export_patterns_cli_writes_pattern_workbook_without_changing_default(tmp_path: Path) -> None:
    default_output = tmp_path / "cli_default.xlsx"
    pattern_base = tmp_path / "cli_patterns.xlsx"

    default_result = subprocess.run(
        [sys.executable, "-m", "diffractscout.compat.cif2peaks", str(TI_BETA_CIF), "-o", str(default_output)],
        cwd=ROOT,
        env=_subprocess_env(),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    pattern_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffractscout.compat.cif2peaks",
            str(TI_BETA_CIF),
            "-o",
            str(pattern_base),
            "--export-patterns",
            "--pattern-axis",
            "q",
        ],
        cwd=ROOT,
        env=_subprocess_env(),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert default_result.returncode == 0, default_result.stderr
    assert default_output.exists()
    assert not (tmp_path / "cli_default_谱线.xlsx").exists()
    assert pattern_result.returncode == 0, pattern_result.stderr
    assert (tmp_path / "cli_patterns_峰表.xlsx").exists()
    pattern_output = tmp_path / "cli_patterns_谱线.xlsx"
    assert pattern_output.exists()
    rows = _worksheet_rows(pattern_output, 2)
    assert rows[1][2] == "q"
    assert float(rows[1][3]) >= 0.0


def test_cif2peaks_batch_load_isolates_unrecoverable_bad_cif(tmp_path: Path) -> None:
    bad_cif = tmp_path / "bad.cif"
    bad_cif.write_text("data_bad\n_cell_length_a 3\n", encoding="utf-8")
    service = Cif2PeaksService()

    phases = service.load_phases([TI_BETA_CIF, bad_cif])
    service.simulate_phases(phases, Cif2PeaksSettings())
    output = tmp_path / "with_bad_cif.xlsx"
    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, Cif2PeaksSettings()), output)

    assert len(phases) == 2
    assert phases[0].result is not None
    assert phases[0].error is None
    assert phases[1].result is None
    assert phases[1].error
    assert not phases[1].enabled
    summary_text = "\n".join("|".join(row) for row in _worksheet_rows(output, 1))
    assert "bad.cif" in summary_text
    assert "CIF 格式不完整或无法解析" in summary_text
    assert "Traceback" not in summary_text
    assert "[Errno" not in summary_text


def test_cif2peaks_multi_phase_workbook_export(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = [service.load_phase(TI_BETA_CIF), service.load_phase(TI_NB_HCP_CIF)]
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "cif2peaks_export.xlsx"
    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, settings), output)
    with ZipFile(output) as archive:
        workbook = archive.read("xl/workbook.xml").decode("utf-8")
        combined_index = _workbook_sheet_names(output).index("Combined Peaks") + 1
        combined = archive.read(f"xl/worksheets/sheet{combined_index}.xml").decode("utf-8")
    assert "Summary" in workbook
    assert "Combined Peaks" in workbook
    assert "工作峰表" in workbook
    assert "Structure" in workbook
    assert "Overlap" in workbook
    assert "ti_beta_bcc_im3m" in workbook
    assert "ti_nb_hcp_p63mmc" in workbook
    assert combined.count("<row ") > 2


def test_cif2peaks_workbook_peak_sheets_are_excel_friendly(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = [service.load_phase(TI_BETA_CIF), service.load_phase(TI_NB_HCP_CIF)]
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "friendly.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, settings), output)

    sheet_names = _workbook_sheet_names(output)
    combined_index = sheet_names.index("Combined Peaks") + 1
    beginner_index = sheet_names.index("推荐峰表") + 1
    with ZipFile(output) as archive:
        combined = archive.read(f"xl/worksheets/sheet{combined_index}.xml").decode("utf-8")

    assert '<pane ySplit="1" topLeftCell="A2"' in combined
    assert '<autoFilter ref="A1:BA' in combined
    assert '<cols>' in combined
    combined_headers = _worksheet_rows(output, combined_index)[0]
    beginner_headers = _worksheet_rows(output, beginner_index)[0]
    combined_widths = _worksheet_column_widths(output, combined_index)
    beginner_widths = _worksheet_column_widths(output, beginner_index)
    combined_width_by_header = {header: combined_widths[index] for index, header in enumerate(combined_headers, start=1)}
    beginner_width_by_header = {header: beginner_widths[index] for index, header in enumerate(beginner_headers, start=1)}
    assert combined_width_by_header["phase_name"] == "22"
    assert combined_width_by_header["cif_name"] == "30"
    assert combined_width_by_header["multiplicity"] == "12"
    assert combined_width_by_header["warnings"] == "48"
    assert combined_width_by_header["elastic_modulus_note"] == "44"
    assert beginner_width_by_header["相名"] == "18"
    assert beginner_width_by_header["提示"] == "48"


def test_cif2peaks_workbook_opens_with_chinese_user_guide(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    settings = Cif2PeaksSettings()
    service.simulate_phase(phase, settings)
    output = tmp_path / "guide.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload([phase], settings), output)

    sheet_names = _workbook_sheet_names(output)
    with ZipFile(output) as archive:
        workbook = archive.read("xl/workbook.xml").decode("utf-8")
        guide_xml = archive.read(f"xl/worksheets/sheet{sheet_names.index('使用说明') + 1}.xml").decode("utf-8")

    assert 'name="使用说明"' in workbook
    assert 'name="工作峰表"' in workbook
    assert f'activeTab="{sheet_names.index("工作峰表")}"' in workbook
    assert "默认参数" in guide_xml
    assert "推荐峰表" in guide_xml
    assert "Combined Peaks" in guide_xml
    assert "two_theta_current_deg" in guide_xml


def test_cif2peaks_workbook_includes_beginner_chinese_peak_table(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = [service.load_phase(TI_BETA_CIF), service.load_phase(TI_NB_HCP_CIF)]
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "beginner_table.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, settings), output)

    with ZipFile(output) as archive:
        workbook = archive.read("xl/workbook.xml").decode("utf-8")
    rows = _worksheet_rows_by_name(output, "推荐峰表")

    assert 'name="推荐峰表"' in workbook
    assert rows[0] == [
        "相名",
        "CIF 文件",
        "化学式",
        "空间群",
        "晶面 hkl",
        "d 间距 (Å)",
        "2θ 当前设置 (°)",
        "2θ Cu Kα (°)",
        "相对强度",
        "多重性",
        "提示",
        "R因子 R_hkl",
        "1/R_hkl",
        "相内 R_hkl (%)",
        "R因子 R_hkl_no_LP",
        "1/R_hkl_no_LP",
        "相内 R_hkl_no_LP (%)",
        "未归一化理论强度",
        "晶胞体积 (Å^3)",
        "密度 (g/cm³)",
        "多族峰",
        "R因子说明",
        "晶面法向杨氏模量 (GPa)",
        "弹性常数状态",
    ]
    assert len(rows) > 2
    guide_text = "\n".join("|".join(row) for row in _worksheet_rows_by_name(output, "使用说明"))
    assert "推荐峰表" in guide_text
    assert "中文列名" in guide_text


def test_cif2peaks_workbook_registers_stylesheet_for_export_polish(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = [service.load_phase(TI_BETA_CIF), service.load_phase(TI_NB_HCP_CIF)]
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "styled.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, settings), output)

    with ZipFile(output) as archive:
        content_types = archive.read("[Content_Types].xml").decode("utf-8")
        workbook_rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        styles_xml = archive.read("xl/styles.xml").decode("utf-8")
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    styles_root = ET.fromstring(styles_xml)
    fonts = styles_root.findall("main:fonts/main:font", namespace)
    style_xfs = styles_root.findall("main:cellXfs/main:xf", namespace)

    assert 'PartName="/xl/styles.xml"' in content_types
    assert "spreadsheetml.styles+xml" in content_types
    assert "relationships/styles" in workbook_rels
    assert 'Target="styles.xml"' in workbook_rels
    assert "<cellXfs" in styles_xml
    assert "FFF2CC" in styles_xml
    assert [font.find("main:name", namespace).attrib["val"] for font in fonts] == ["Times New Roman", "Times New Roman"]
    assert "Calibri" not in styles_xml
    assert len(style_xfs) >= 3
    assert all(
        xf.find("main:alignment", namespace) is not None
        and xf.find("main:alignment", namespace).attrib["horizontal"] == "center"
        and xf.find("main:alignment", namespace).attrib["vertical"] == "center"
        for xf in style_xfs
    )


def test_cif2peaks_combined_peak_sheets_color_rows_by_phase(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = [service.load_phase(TI_BETA_CIF), service.load_phase(TI_NB_HCP_CIF)]
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "phase_colors.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, settings), output)

    combined_index = _workbook_sheet_names(output).index("Combined Peaks") + 1
    beginner_index = _workbook_sheet_names(output).index("推荐峰表") + 1
    combined_rows = _worksheet_rows(output, combined_index)
    combined_styles = _worksheet_cell_styles(output, combined_index)
    beginner_styles = _worksheet_cell_styles(output, beginner_index)
    first_phase = combined_rows[1][0]
    second_phase_row = next(index for index, row in enumerate(combined_rows[1:], start=1) if row[0] != first_phase)

    assert combined_styles[0][0] == "1"
    assert beginner_styles[0][0] == "2"
    assert beginner_styles[0][2] == "1"
    assert combined_styles[1][0] != "0"
    assert combined_styles[1][0] == beginner_styles[1][0]
    assert all(
        combined_styles[index][0] == combined_styles[1][0]
        for index, row in enumerate(combined_rows[1:], start=1)
        if row[0] == first_phase
    )
    assert combined_styles[second_phase_row][0] != combined_styles[1][0]


def test_cif2peaks_beginner_key_headers_follow_inserted_r_hkl_no_lp_columns(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = [service.load_phase(TI_BETA_CIF), service.load_phase(TI_NB_HCP_CIF)]
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "beginner_key_headers.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, settings), output)

    beginner_index = _workbook_sheet_names(output).index("推荐峰表") + 1
    headers = _worksheet_rows(output, beginner_index)[0]
    header_styles = dict(zip(headers, _worksheet_cell_styles(output, beginner_index)[0], strict=True))

    assert header_styles["R因子 R_hkl_no_LP"] == "2"
    assert header_styles["1/R_hkl_no_LP"] == "2"
    assert header_styles["相内 R_hkl_no_LP (%)"] == "2"
    assert header_styles["密度 (g/cm³)"] == "2"
    assert header_styles["多族峰"] == "2"
    assert header_styles["R因子说明"] == "1"


def test_cif2peaks_user_guide_explains_beginner_columns_and_limits(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = [service.load_phase(TI_BETA_CIF), service.load_phase(TI_NB_HCP_CIF)]
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "guide_detail.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, settings), output)

    guide_text = "\n".join("|".join(row) for row in _worksheet_rows_by_name(output, "使用说明"))

    assert "新手先看哪几列" in guide_text
    assert "two_theta_current_deg" in guide_text
    assert "d_A" in guide_text
    assert "相对强度" in guide_text
    assert "不是实验定量强度" in guide_text
    assert "warnings" in guide_text
    assert "晶面法向杨氏模量" in guide_text
    assert "Cij" in guide_text
    assert "Miller-Bravais" in guide_text
    assert "multiple_hkl_families" in guide_text
    assert "crystal_cartesian_from_cif_lattice" in guide_text


def test_cif2peaks_workbook_adds_result_reading_guidance_without_renaming_sheets(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = [service.load_phase(TI_BETA_CIF), service.load_phase(TI_NB_HCP_CIF)]
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "result_guidance.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, settings), output)

    sheet_names = _workbook_sheet_names(output)
    summary_text = "\n".join("|".join(row) for row in _worksheet_rows_by_name(output, "Summary"))
    guide_text = "\n".join("|".join(row) for row in _worksheet_rows_by_name(output, "使用说明"))

    assert "Combined Peaks" in sheet_names
    assert "推荐峰表" in sheet_names
    assert "工作峰表" in sheet_names
    assert "Structure" in sheet_names
    assert "Elastic Constants" in sheet_names
    assert "result_reading_order" in summary_text
    assert "warning_guidance" in summary_text
    assert "r_hkl_guidance" in summary_text
    assert "elastic_guidance" in summary_text
    assert "结果阅读顺序" in guide_text
    assert "警告处理建议" in guide_text
    assert "R_hkl 使用边界" in guide_text
    assert "Cij / 弹性结果" in guide_text


def test_batch_module_help_and_package_main_cli(tmp_path: Path) -> None:
    help_result = subprocess.run(
        [sys.executable, "-m", "diffractscout.compat.cif2peaks.batch", "--help"],
        cwd=ROOT,
        env=_subprocess_env(),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert help_result.returncode == 0
    assert "Batch-export" in help_result.stdout

    output = tmp_path / "package_main.xlsx"
    run_result = subprocess.run(
        [sys.executable, "-m", "diffractscout.compat.cif2peaks", str(TI_BETA_CIF), "-o", str(output)],
        cwd=ROOT,
        env=_subprocess_env(),
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert run_result.returncode == 0, run_result.stderr
    assert output.exists()
    assert "Exported" in run_result.stdout


def test_batch_cli_default_output_is_excel(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "diffractscout.compat.cif2peaks.batch", str(TI_BETA_CIF)],
        cwd=tmp_path,
        env=_subprocess_env(),
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "cif2peaks_peak_reference.xlsx").exists()
    assert not (tmp_path / "cif2peaks_peak_reference.csv").exists()


def test_batch_output_path_without_suffix_defaults_to_excel(tmp_path: Path) -> None:
    peak_output, pattern_output = export_output_paths(tmp_path / "reference", export_peaks=True, export_patterns=False)

    assert peak_output == tmp_path / "reference.xlsx"
    assert pattern_output is None


def test_simple_gui_builds_energy_settings_from_user_inputs() -> None:
    from diffractscout.compat.cif2peaks.constants import X_RAY_ENERGY_WAVELENGTH_KEV_A
    from diffractscout.compat.cif2peaks.gui import build_gui_settings

    settings = build_gui_settings("20.0", "5", "120")

    assert settings.input_mode == "energy"
    assert settings.energy_keV == 20.0
    assert np.isclose(settings.wavelength_A, X_RAY_ENERGY_WAVELENGTH_KEV_A / 20.0)
    assert settings.two_theta_min_deg == 5.0
    assert settings.two_theta_max_deg == 120.0


def test_beginner_gui_defaults_to_cu_ka_without_user_parameters() -> None:
    from diffractscout.compat.cif2peaks.gui import build_beginner_gui_settings

    settings = build_beginner_gui_settings()

    assert settings.input_mode == "source"
    assert settings.source_preset == "Cu Ka"
    assert settings.two_theta_min_deg == 0.0
    assert settings.two_theta_max_deg == 180.0


def test_beginner_gui_d_range_defaults_to_unrestricted_cu_ka() -> None:
    from diffractscout.compat.cif2peaks.gui import build_beginner_gui_settings_from_d_range

    settings = build_beginner_gui_settings_from_d_range()

    assert settings.input_mode == "source"
    assert settings.source_preset == "Cu Ka"
    assert settings.d_min_A is None
    assert settings.d_max_A is None
    assert settings.two_theta_min_deg == 0.0
    assert settings.two_theta_max_deg == 180.0


def test_beginner_gui_d_range_converts_boundaries_for_cu_ka() -> None:
    from diffractscout.compat.cif2peaks.constants import DEFAULT_XRD_WAVELENGTH_A
    from diffractscout.compat.cif2peaks.gui import build_beginner_gui_settings_from_d_range

    lower_bound = build_beginner_gui_settings_from_d_range(d_min_A=str(DEFAULT_XRD_WAVELENGTH_A))
    upper_bound = build_beginner_gui_settings_from_d_range(d_max_A=str(DEFAULT_XRD_WAVELENGTH_A))
    bounded = build_beginner_gui_settings_from_d_range(d_min_A="1.0", d_max_A="2.0")

    assert np.isclose(lower_bound.two_theta_min_deg, 0.0)
    assert np.isclose(lower_bound.two_theta_max_deg, 60.0)
    assert np.isclose(upper_bound.two_theta_min_deg, 60.0)
    assert np.isclose(upper_bound.two_theta_max_deg, 180.0)
    assert np.isclose(bounded.two_theta_min_deg, 45.3061, atol=1e-4)
    assert np.isclose(bounded.two_theta_max_deg, 100.7617, atol=1e-4)


def test_beginner_gui_d_range_uses_manual_energy_before_conversion() -> None:
    from diffractscout.compat.cif2peaks.constants import X_RAY_ENERGY_WAVELENGTH_KEV_A
    from diffractscout.compat.cif2peaks.gui import build_beginner_gui_settings_from_d_range

    settings = build_beginner_gui_settings_from_d_range(d_min_A="1.0", energy_keV="20.0", xray_preset="83 keV")

    assert settings.input_mode == "energy"
    assert settings.energy_keV == 20.0
    assert np.isclose(settings.wavelength_A, X_RAY_ENERGY_WAVELENGTH_KEV_A / 20.0)
    assert np.isclose(settings.two_theta_max_deg, 36.1137, atol=1e-4)


def test_beginner_gui_d_range_uses_visible_energy_presets_before_conversion() -> None:
    from diffractscout.compat.cif2peaks.constants import X_RAY_ENERGY_WAVELENGTH_KEV_A
    from diffractscout.compat.cif2peaks.gui import build_beginner_gui_settings_from_d_range

    low_energy = build_beginner_gui_settings_from_d_range(d_min_A="1.0", xray_preset="30 keV")
    high_energy = build_beginner_gui_settings_from_d_range(d_min_A="1.0", xray_preset="83 keV")

    assert np.isclose(low_energy.wavelength_A, X_RAY_ENERGY_WAVELENGTH_KEV_A / 30.0)
    assert np.isclose(high_energy.wavelength_A, X_RAY_ENERGY_WAVELENGTH_KEV_A / 83.0)
    assert low_energy.two_theta_max_deg > high_energy.two_theta_max_deg


@pytest.mark.parametrize(
    ("d_min_A", "d_max_A", "expected_error"),
    [
        ("bad", "", "must be a number"),
        ("-1", "", "must be greater than 0"),
        ("2.0", "1.0", "d range"),
        ("", "0.1", "no observable"),
    ],
)
def test_beginner_gui_d_range_rejects_invalid_inputs(d_min_A: str, d_max_A: str, expected_error: str) -> None:
    from diffractscout.compat.cif2peaks.gui import build_beginner_gui_settings_from_d_range

    with pytest.raises(ValueError, match=expected_error):
        build_beginner_gui_settings_from_d_range(d_min_A=d_min_A, d_max_A=d_max_A)


def test_beginner_gui_keeps_cu_ka_when_energy_is_blank() -> None:
    from diffractscout.compat.cif2peaks.gui import build_beginner_gui_settings

    settings = build_beginner_gui_settings(energy_keV=" ")

    assert settings.input_mode == "source"
    assert settings.source_preset == "Cu Ka"


def test_beginner_gui_uses_custom_energy_when_provided() -> None:
    from diffractscout.compat.cif2peaks.gui import build_beginner_gui_settings

    settings = build_beginner_gui_settings(energy_keV="20.0", two_theta_min="5", two_theta_max="120")

    assert settings.input_mode == "energy"
    assert settings.energy_keV == 20.0
    assert settings.two_theta_min_deg == 5.0
    assert settings.two_theta_max_deg == 120.0


def test_beginner_gui_uses_visible_energy_presets() -> None:
    from diffractscout.compat.cif2peaks.constants import X_RAY_ENERGY_WAVELENGTH_KEV_A
    from diffractscout.compat.cif2peaks.gui import build_beginner_gui_settings

    low_energy = build_beginner_gui_settings(xray_preset="30 keV")
    high_energy = build_beginner_gui_settings(xray_preset="83 keV")

    assert low_energy.input_mode == "energy"
    assert low_energy.energy_keV == 30.0
    assert np.isclose(low_energy.wavelength_A, X_RAY_ENERGY_WAVELENGTH_KEV_A / 30.0)
    assert high_energy.input_mode == "energy"
    assert high_energy.energy_keV == 83.0
    assert np.isclose(high_energy.wavelength_A, X_RAY_ENERGY_WAVELENGTH_KEV_A / 83.0)


def test_beginner_gui_manual_energy_overrides_selected_preset() -> None:
    from diffractscout.compat.cif2peaks.constants import X_RAY_ENERGY_WAVELENGTH_KEV_A
    from diffractscout.compat.cif2peaks.gui import build_beginner_gui_settings

    settings = build_beginner_gui_settings(energy_keV="20.0", xray_preset="83 keV")

    assert settings.input_mode == "energy"
    assert settings.energy_keV == 20.0
    assert np.isclose(settings.wavelength_A, X_RAY_ENERGY_WAVELENGTH_KEV_A / 20.0)


def test_beginner_gui_suggests_clear_output_path(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import next_gui_output_path, suggest_output_path

    single = suggest_output_path([tmp_path / "Ti.cif"])
    many = suggest_output_path([tmp_path / "Ti.cif", tmp_path / "TiB.cif"])

    assert single == tmp_path / "Ti_CIF2Peaks峰表.xlsx"
    assert many == tmp_path / "CIF2Peaks峰表_2个CIF.xlsx"
    assert next_gui_output_path(tmp_path / "custom.xlsx", [tmp_path / "Ti.cif"], user_customized=False) == single
    assert next_gui_output_path(tmp_path / "custom.xlsx", [tmp_path / "Ti.cif"], user_customized=True) == tmp_path / "custom.xlsx"


def test_beginner_gui_turns_common_errors_into_chinese_guidance() -> None:
    from diffractscout.compat.cif2peaks.gui import friendly_error_message

    no_file_message = friendly_error_message(ValueError("Select at least one CIF file."))
    assert "哪里出错" in no_file_message
    assert "可能原因" in no_file_message
    assert "下一步" in no_file_message
    assert "请先" in no_file_message
    assert "数字" in friendly_error_message(ValueError("2theta min must be a number."))
    assert "能量" in friendly_error_message(ValueError("X-ray energy keV must be greater than 0."))
    assert "d 范围" in friendly_error_message(ValueError("d range has no observable first-order Bragg peaks for this wavelength."))
    assert "Excel" in friendly_error_message(PermissionError("locked"))
    assert "重新选择" in friendly_error_message(FileNotFoundError("Missing CIF file(s): old.cif"))
    fallback_message = friendly_error_message(RuntimeError("unexpected failure"))
    assert "处理失败" in fallback_message
    assert "unexpected failure" in fallback_message


def test_beginner_gui_can_render_error_guidance_in_english() -> None:
    from diffractscout.compat.cif2peaks.gui import friendly_error_message

    message = friendly_error_message(ValueError("Select at least one CIF file."), language="en")

    assert "Problem:" in message
    assert "Likely cause:" in message
    assert "Next step:" in message
    assert "Add files" in message


def test_gui_export_diagnostics_summarize_phase_outcomes(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import SimpleGuiExportResult, summarize_gui_export_result

    result = SimpleGuiExportResult(
        output_path=tmp_path / "result.xlsx",
        total_peaks=12,
        phase_rows=[
            ("alpha", "Ti", "Im-3m", 12, "", "no_elastic_constants"),
            ("beta", "Ti", "P63/mmc", 0, "CIF warning", "valid"),
            ("bad", "-", "-", 0, "CIF format error", "no_elastic_constants"),
        ],
    )

    summary = summarize_gui_export_result(result)

    assert summary.total_phases == 3
    assert summary.ready_count == 2
    assert summary.failed_count == 1
    assert summary.warning_count == 1
    assert summary.zero_peak_count == 1


def test_gui_export_diagnostics_use_explicit_error_flags_for_simulation_failures(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import SimpleGuiExportResult, summarize_gui_export_result

    result = SimpleGuiExportResult(
        output_path=tmp_path / "result.xlsx",
        total_peaks=0,
        phase_rows=[
            ("loaded_but_failed", "Ti", "Im-3m", 0, "XRD calculation failed", "no_elastic_constants"),
        ],
        phase_error_flags=[True],
    )

    summary = summarize_gui_export_result(result)

    assert summary.ready_count == 0
    assert summary.failed_count == 1
    assert summary.warning_count == 0
    assert summary.zero_peak_count == 0


def test_gui_completion_guidance_reports_outputs_and_next_steps(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import SimpleGuiExportResult, gui_export_completion_text

    peak_output = tmp_path / "result_峰表.xlsx"
    pattern_output = tmp_path / "result_谱线.xlsx"
    figure_output = tmp_path / "result_01_alpha_publication.svg"
    result = SimpleGuiExportResult(
        output_path=peak_output,
        total_peaks=42,
        phase_rows=[
            ("alpha", "Ti", "Im-3m", 42, "", "no_elastic_constants"),
            ("bad", "-", "-", 0, "CIF format error", "no_elastic_constants"),
        ],
        peak_output_path=peak_output,
        pattern_output_path=pattern_output,
        publication_figure_paths=[figure_output],
    )

    status_zh, dialog_zh = gui_export_completion_text(result, "zh")
    status_en, dialog_en = gui_export_completion_text(result, "en")

    assert "42 条峰记录" in status_zh
    assert "失败 1 个" in dialog_zh
    assert "下一步" in dialog_zh
    assert "使用说明" in dialog_zh
    assert "Summary" in dialog_zh
    assert "推荐峰表" in dialog_zh
    assert str(pattern_output) in dialog_zh
    assert str(figure_output) in dialog_zh
    assert "42 peak record" in status_en
    assert "1 failed" in dialog_en
    assert "Next step" in dialog_en
    assert "User Guide" in dialog_en
    assert "Recommended peak table" in dialog_en


def test_gui_completion_guidance_handles_diagnostic_workbook(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import SimpleGuiExportResult, gui_export_completion_text

    result = SimpleGuiExportResult(
        output_path=tmp_path / "diagnostic.xlsx",
        total_peaks=0,
        phase_rows=[("bad", "-", "-", 0, "CIF format error", "no_elastic_constants")],
    )

    status, dialog = gui_export_completion_text(result, "zh")

    assert "诊断 Excel" in status
    assert "失败 1 个" in dialog
    assert "请先打开 Summary 和 使用说明" in dialog


def test_beginner_gui_previews_cif_metadata_before_export(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import preview_simple_gui_inputs

    good_cif = tmp_path / TI_BETA_CIF.name
    bad_cif = tmp_path / "bad.cif"
    good_cif.write_bytes(TI_BETA_CIF.read_bytes())
    bad_cif.write_text("data_bad\n_cell_length_a 3\n", encoding="utf-8")

    result = preview_simple_gui_inputs([good_cif, bad_cif])

    assert result.ready_count == 1
    assert result.failed_count == 1
    assert result.phase_rows[0][0] == good_cif.name
    assert result.phase_rows[0][1] == "Ti"
    assert result.phase_rows[0][2] != "-"
    assert result.phase_rows[0][3] == "待导出"
    assert result.phase_rows[0][4] == ""
    assert result.phase_rows[0][5] == "no_elastic_constants"
    assert result.phase_rows[1][0] == bad_cif.name
    assert result.phase_rows[1][1] == "-"
    assert result.phase_rows[1][3] == "无法读取"
    assert "CIF" in result.phase_rows[1][4]
    assert "格式" in result.phase_rows[1][4]
    assert "Traceback" not in result.phase_rows[1][4]
    assert "[Errno" not in result.phase_rows[1][4]
    assert result.phase_rows[1][5] == "no_elastic_constants"

    folder_result = preview_simple_gui_inputs([tmp_path])
    assert folder_result.ready_count == 1
    assert folder_result.failed_count == 1
    assert [row[0] for row in folder_result.phase_rows] == [bad_cif.name, good_cif.name]


def test_preview_gui_keeps_language_as_third_positional_argument(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import preview_simple_gui_inputs

    cif_path = tmp_path / TI_BETA_CIF.name
    cif_path.write_bytes(TI_BETA_CIF.read_bytes())

    result = preview_simple_gui_inputs([cif_path], None, "en")

    assert result.phase_rows[0][3] == "Ready"
    assert result.phase_rows[0][5] == "no_elastic_constants"


def test_gui_startup_collects_dragged_cif_files_and_folders(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import initial_gui_cif_paths

    cif = tmp_path / "Ti.cif"
    uppercase_suffix_cif = tmp_path / "Ti_copy.CIF"
    notes = tmp_path / "notes.txt"
    nested = tmp_path / "nested"
    nested_cif = nested / "TiB.cif"
    for path in (cif, uppercase_suffix_cif, notes):
        path.write_text("data_test\n", encoding="utf-8")
    nested.mkdir()
    nested_cif.write_text("data_nested\n", encoding="utf-8")

    paths = initial_gui_cif_paths([cif, notes, nested, uppercase_suffix_cif, cif, tmp_path / "missing.cif"])

    assert paths == [cif.resolve(), nested_cif.resolve(), uppercase_suffix_cif.resolve()]


def test_gui_splits_drop_event_paths_with_spaces(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import split_drop_event_paths

    spaced_cif = tmp_path / "Ti beta.cif"
    folder = tmp_path / "folder with spaces"
    drop_data = f"{{{spaced_cif}}} {{{folder}}}"

    paths = split_drop_event_paths(drop_data, lambda value: (str(spaced_cif), str(folder)))

    assert paths == [str(spaced_cif), str(folder)]


def test_gui_drop_adds_cifs_and_reports_ignored_inputs(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import add_gui_cif_inputs

    cif = tmp_path / "Ti beta.cif"
    uppercase_cif = tmp_path / "Ti copy.CIF"
    notes = tmp_path / "notes.txt"
    folder = tmp_path / "folder"
    nested_cif = folder / "nested.cif"
    empty_folder = tmp_path / "empty"
    for path in (cif, uppercase_cif, notes):
        path.write_text("data_test\n", encoding="utf-8")
    folder.mkdir()
    empty_folder.mkdir()
    nested_cif.write_text("data_nested\n", encoding="utf-8")
    selected_paths = [cif.resolve()]

    result = add_gui_cif_inputs(selected_paths, [cif, uppercase_cif, notes, folder, empty_folder, tmp_path / "missing.cif"])

    assert result.added_count == 2
    assert result.ignored_count == 4
    assert selected_paths == [cif.resolve(), uppercase_cif.resolve(), nested_cif.resolve()]


def test_gui_language_pack_covers_primary_controls() -> None:
    from diffractscout.compat.cif2peaks.gui import GUI_TEXT, SUPPORTED_GUI_LANGUAGES

    required_keys = {
        "window_title",
        "app_title",
        "app_subtitle",
        "developer_credit",
        "toggle_language",
        "files_panel",
        "display_name_label",
        "apply_display_name",
        "reset_display_name",
        "add_files",
        "add_folder",
        "remove_selected",
        "clear_files",
        "settings_panel",
        "output_file",
        "choose_output",
        "xray_preset",
        "manual_energy",
        "d_range",
        "preview_panel",
        "activity_log_title",
        "tree_display_name",
        "tree_formula",
        "tree_space_group",
        "tree_status",
        "tree_warning",
        "export_excel",
        "open_excel",
        "workspace_section",
        "data_source_title",
        "parameters_title",
        "required_parameters_group",
        "output_content_group",
        "optional_outputs_group",
        "advanced_elastic_group",
        "preview_title",
        "status_ready",
        "publication_export",
        "figure_preset",
        "result_next_step",
    }

    assert set(SUPPORTED_GUI_LANGUAGES) == {"zh", "en"}
    for language in SUPPORTED_GUI_LANGUAGES:
        missing = [key for key in sorted(required_keys) if not GUI_TEXT[language].get(key)]
        assert not missing
    assert GUI_TEXT["zh"]["export_excel"] == "导出结果"
    assert GUI_TEXT["zh"]["add_files"] == "添加 CIF"
    assert GUI_TEXT["zh"]["clear_files"] == "清空列表"
    assert GUI_TEXT["zh"]["choose_output"] == "选择输出"
    assert GUI_TEXT["zh"]["apply_display_name"] == "应用相名"
    assert GUI_TEXT["zh"]["activity_log_title"] == "运行记录"
    assert GUI_TEXT["zh"]["required_parameters_group"] == "必需参数"
    assert GUI_TEXT["zh"]["advanced_elastic_group"] == "可选高级项：Cij 弹性常数"
    assert "使用说明" in GUI_TEXT["zh"]["result_next_step"]
    assert "图像选项" in GUI_TEXT["zh"]["ready_to_export"]
    assert GUI_TEXT["en"]["export_excel"] == "Export results"
    assert GUI_TEXT["en"]["add_files"] == "Add CIFs"
    assert GUI_TEXT["en"]["clear_files"] == "Clear list"
    assert GUI_TEXT["en"]["choose_output"] == "Choose output"
    assert GUI_TEXT["en"]["apply_display_name"] == "Apply phase name"
    assert GUI_TEXT["en"]["activity_log_title"] == "Activity log"
    assert GUI_TEXT["en"]["required_parameters_group"] == "Required settings"
    assert GUI_TEXT["en"]["advanced_elastic_group"] == "Optional advanced: Cij elastic constants"
    assert "User Guide" in GUI_TEXT["en"]["result_next_step"]
    assert GUI_TEXT["en"]["publication_export"] == "Export figures (SVG/PDF/EPS/PNG/TIFF)"
    assert GUI_TEXT["en"]["settings_hint"] == "Manual energy overrides preset; blank uses preset."
    assert "figure options" in GUI_TEXT["en"]["ready_to_export"]


def test_gui_export_control_states_follow_selected_outputs() -> None:
    from diffractscout.compat.cif2peaks.gui import gui_export_control_states

    assert gui_export_control_states(
        has_files=True,
        export_peaks=True,
        export_patterns=False,
        export_publication_figures=False,
    ) == {
        "export_button": "normal",
        "pattern_axis": "disabled",
        "figure_preset": "disabled",
    }
    assert gui_export_control_states(
        has_files=True,
        export_peaks=False,
        export_patterns=False,
        export_publication_figures=True,
    ) == {
        "export_button": "disabled",
        "pattern_axis": "disabled",
        "figure_preset": "readonly",
    }
    assert gui_export_control_states(
        has_files=True,
        export_peaks=False,
        export_patterns=True,
        export_publication_figures=True,
        is_busy=True,
    ) == {
        "export_button": "disabled",
        "pattern_axis": "readonly",
        "figure_preset": "readonly",
    }


def test_gui_activity_log_language_pack_covers_user_feedback_events() -> None:
    from diffractscout.compat.cif2peaks.gui import GUI_TEXT, SUPPORTED_GUI_LANGUAGES

    required_log_keys = {
        "log_ready",
        "log_added",
        "log_add_none",
        "log_cleared",
        "log_preview_reading",
        "log_preview_ready",
        "log_preview_with_failures",
        "log_exporting",
        "log_export_done",
        "log_export_failed",
        "log_export_cancelled",
    }

    for language in SUPPORTED_GUI_LANGUAGES:
        missing = [key for key in sorted(required_log_keys) if not GUI_TEXT[language].get(key)]
        assert not missing
    assert "加入" in GUI_TEXT["zh"]["log_added"]
    assert "added" in GUI_TEXT["en"]["log_added"]
    assert "导出失败" in GUI_TEXT["zh"]["log_export_failed"]
    assert "Export failed" in GUI_TEXT["en"]["log_export_failed"]
    assert "{failed}" in GUI_TEXT["zh"]["log_export_done"]
    assert "{warnings}" in GUI_TEXT["en"]["log_export_done"]


def test_gui_exposes_minimal_workbench_theme_contract() -> None:
    from diffractscout.compat.cif2peaks.gui import GUI_THEME, GUI_WORKBENCH_LAYOUT

    assert GUI_WORKBENCH_LAYOUT["geometry"] == "1200x760"
    assert GUI_WORKBENCH_LAYOUT["minsize"] == (1040, 680)
    assert GUI_WORKBENCH_LAYOUT["sidebar_width"] == 330
    assert GUI_WORKBENCH_LAYOUT["scrollable_main"] is True
    assert GUI_THEME["surface"] == "#e8edf3"
    assert GUI_THEME["panel"] == "#ffffff"
    assert GUI_THEME["panel_raised"] == "#fdfefe"
    assert GUI_THEME["panel_muted"] == "#f5f7fb"
    assert GUI_THEME["primary"] == "#2563eb"
    assert GUI_THEME["primary_active"] == "#1d4ed8"
    assert GUI_THEME["accent"] == "#0f766e"
    assert GUI_THEME["success"] == "#188038"
    assert GUI_THEME["warning"] == "#b7791f"
    assert GUI_THEME["danger"] == "#b3261e"
    assert GUI_THEME["focus"] == "#60a5fa"
    assert GUI_THEME["border"] == "#cbd5e1"
    assert GUI_THEME["border_strong"] == "#94a3b8"
    assert GUI_THEME["text"] == "#111827"
    assert GUI_THEME["table_header"] == "#dbe5f1"
    assert GUI_THEME["section_header"] == "#f1f5f9"


def test_gui_defines_tooltips_and_clear_confirmation_contract(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import (
        GUI_PUBLICATION_PRESET_LABELS,
        GUI_TEXT,
        GUI_TOOLTIP_KEYS,
        SUPPORTED_GUI_LANGUAGES,
        planned_gui_output_paths,
        should_clear_gui_files,
        should_overwrite_gui_output,
        should_overwrite_gui_outputs,
    )
    from diffractscout.compat.cif2peaks.plotting import FIGURE_EXPORT_PRESETS

    expected_tooltip_roles = {
        "add_files",
        "add_folder",
        "remove_selected",
        "clear_files",
        "display_name",
        "output_file",
        "choose_output",
        "xray_preset",
        "manual_energy",
        "d_range",
        "publication_export",
        "figure_preset",
        "export_excel",
        "open_excel",
    }

    assert expected_tooltip_roles.issubset(GUI_TOOLTIP_KEYS)
    assert set(GUI_PUBLICATION_PRESET_LABELS) == set(FIGURE_EXPORT_PRESETS)
    assert GUI_PUBLICATION_PRESET_LABELS[0] == "publication"
    for language in SUPPORTED_GUI_LANGUAGES:
        for tooltip_key in GUI_TOOLTIP_KEYS.values():
            assert GUI_TEXT[language].get(tooltip_key)
        assert GUI_TEXT[language].get("confirm_clear_title")
        assert GUI_TEXT[language].get("confirm_clear_message")
        assert GUI_TEXT[language].get("confirm_overwrite_title")
        assert GUI_TEXT[language].get("confirm_overwrite_message")
        assert GUI_TEXT[language].get("export_cancelled_overwrite")
        assert "PNG" in GUI_TEXT[language]["publication_export"]
        assert "TIFF" in GUI_TEXT[language]["tooltip_publication_export"]
        assert GUI_TEXT[language].get("tooltip_figure_preset")
        assert "Excel" in GUI_TEXT[language]["tooltip_export_excel"]
        assert "图" in GUI_TEXT[language]["tooltip_export_excel"] or "figure" in GUI_TEXT[language]["tooltip_export_excel"]

    calls: list[int] = []

    def deny_clear() -> bool:
        calls.append(1)
        return False

    assert should_clear_gui_files(0, deny_clear)
    assert calls == []
    assert not should_clear_gui_files(2, deny_clear)
    assert calls == [1]
    assert should_clear_gui_files(2, lambda: True)

    missing_output = tmp_path / "missing_gui_output.xlsx"
    assert should_overwrite_gui_output(missing_output, lambda _path: False)
    existing_output = tmp_path / "existing_gui_output.xlsx"
    existing_output.write_text("old workbook placeholder", encoding="utf-8")
    overwrite_calls: list[Path] = []

    assert not should_overwrite_gui_output(existing_output, lambda path: overwrite_calls.append(path) or False)
    assert overwrite_calls == [existing_output.resolve()]
    assert should_overwrite_gui_output(existing_output, lambda _path: True)

    peak_output = tmp_path / "result_峰表.xlsx"
    pattern_output = tmp_path / "result_谱线.xlsx"
    peak_output.write_text("old peak workbook", encoding="utf-8")
    pattern_output.write_text("old pattern workbook", encoding="utf-8")
    overwrite_calls.clear()

    assert not should_overwrite_gui_outputs([peak_output, pattern_output], lambda path: overwrite_calls.append(path) or False)
    assert overwrite_calls == [peak_output.resolve()]
    overwrite_calls.clear()
    assert should_overwrite_gui_outputs([None, peak_output, pattern_output, peak_output], lambda path: overwrite_calls.append(path) or True)
    assert overwrite_calls == [peak_output.resolve(), pattern_output.resolve()]

    planned_outputs = planned_gui_output_paths(
        tmp_path / "review_target.xlsx",
        [tmp_path / "alpha.cif", tmp_path / "beta.cif"],
        display_names={tmp_path / "alpha.cif": "Alpha phase"},
        export_peaks=True,
        export_patterns=False,
        export_publication_figures=True,
    )
    assert planned_outputs[0] == (tmp_path / "review_target.xlsx").resolve()
    assert (tmp_path / "review_target_01_Alpha_phase_publication.svg").resolve() in planned_outputs
    assert (tmp_path / "review_target_01_Alpha_phase_publication.png").resolve() in planned_outputs
    assert (tmp_path / "review_target_02_beta_cif_publication.tif").resolve() in planned_outputs
    assert len(planned_outputs) == 11

    existing_figure = tmp_path / "review_target_01_Alpha_phase_publication.svg"
    existing_figure.write_text("old figure placeholder", encoding="utf-8")
    overwrite_calls.clear()
    assert not should_overwrite_gui_outputs(
        planned_outputs,
        lambda path: overwrite_calls.append(path) or False,
    )
    assert overwrite_calls == [existing_figure.resolve()]


def test_publication_figure_presets_cover_common_export_contexts() -> None:
    from diffractscout.compat.cif2peaks.plotting import FIGURE_EXPORT_PRESETS, PUBLICATION_EXPORT_FORMATS

    assert set(FIGURE_EXPORT_PRESETS) == {
        "single_column",
        "double_column",
        "presentation",
        "raw_inspection",
        "publication",
    }
    assert PUBLICATION_EXPORT_FORMATS == ("svg", "pdf", "eps", "png", "tif")
    publication = FIGURE_EXPORT_PRESETS["publication"]
    assert publication.dpi >= 600
    assert publication.width_in > 0
    assert publication.height_in > 0
    assert publication.line_width_pt <= 1.4
    assert publication.axis_width_pt <= 1.0
    assert publication.constrained_layout
    assert "Arial" in publication.font_family
    assert publication.color_cycle[0].startswith("#")


def test_publication_svg_export_writes_clean_xrd_vector_plot(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.plotting import export_xrd_pattern_svg

    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    service.simulate_phase(phase, Cif2PeaksSettings())
    assert phase.result is not None
    output = tmp_path / "ti_beta_publication.svg"

    export_xrd_pattern_svg(phase.result, output, title="Ti beta reference", preset_name="publication")

    svg = output.read_text(encoding="utf-8")
    assert svg.startswith("<?xml")
    assert "<svg" in svg
    assert "viewBox=" in svg
    assert "2θ (°)" in svg
    assert "Intensity (a.u.)" in svg
    assert "Ti beta reference" in svg
    assert "<polyline" in svg
    assert "stroke-linejoin=\"round\"" in svg
    assert "rainbow" not in svg.lower()


def test_publication_pdf_and_eps_exports_write_vector_xrd_plots(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.plotting import export_xrd_pattern_eps, export_xrd_pattern_pdf

    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    service.simulate_phase(phase, Cif2PeaksSettings())
    assert phase.result is not None
    pdf_output = tmp_path / "ti_beta_publication.pdf"
    eps_output = tmp_path / "ti_beta_publication.eps"

    export_xrd_pattern_pdf(phase.result, pdf_output, title="Ti beta reference", preset_name="publication")
    export_xrd_pattern_eps(phase.result, eps_output, title="Ti beta reference", preset_name="publication")

    pdf_bytes = pdf_output.read_bytes()
    eps_text = eps_output.read_text(encoding="ascii")
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert b"/MediaBox" in pdf_bytes
    assert b"2theta (deg)" in pdf_bytes
    assert b"Intensity (a.u.)" in pdf_bytes
    assert b"Ti beta reference" in pdf_bytes
    assert b" m " in pdf_bytes and b" l " in pdf_bytes
    assert eps_text.startswith("%!PS-Adobe-3.0 EPSF-3.0")
    assert "%%BoundingBox:" in eps_text
    assert "2theta (deg)" in eps_text
    assert "Intensity (a.u.)" in eps_text
    assert "Ti beta reference" in eps_text
    assert "moveto" in eps_text and "lineto" in eps_text
    assert "rainbow" not in eps_text.lower()


def test_publication_png_and_tiff_exports_write_high_dpi_raster_plots(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.plotting import FIGURE_EXPORT_PRESETS, export_xrd_pattern_png, export_xrd_pattern_tiff

    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    service.simulate_phase(phase, Cif2PeaksSettings())
    assert phase.result is not None
    png_output = tmp_path / "ti_beta_publication.png"
    tiff_output = tmp_path / "ti_beta_publication.tif"

    export_xrd_pattern_png(phase.result, png_output, title="Ti beta reference", preset_name="publication")
    export_xrd_pattern_tiff(phase.result, tiff_output, title="Ti beta reference", preset_name="publication")

    png_bytes = png_output.read_bytes()
    tiff_bytes = tiff_output.read_bytes()
    preset = FIGURE_EXPORT_PRESETS["publication"]
    expected_width = int(round(preset.width_in * preset.dpi))
    expected_height = int(round(preset.height_in * preset.dpi))
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert int.from_bytes(png_bytes[16:20], "big") == expected_width
    assert int.from_bytes(png_bytes[20:24], "big") == expected_height
    assert b"2theta (deg)" in png_bytes
    assert b"Intensity (a.u.)" in png_bytes
    assert b"Ti beta reference" in png_bytes
    assert tiff_bytes.startswith(b"II*\x00")
    assert b"2theta (deg)" in tiff_bytes
    assert b"Intensity (a.u.)" in tiff_bytes
    assert b"Ti beta reference" in tiff_bytes
    assert len(tiff_bytes) > expected_width * expected_height


def test_publication_raster_export_can_fallback_without_optional_matplotlib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import diffractscout.compat.cif2peaks.plotting as plotting

    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    service.simulate_phase(phase, Cif2PeaksSettings())
    assert phase.result is not None
    output = tmp_path / "fallback_publication.png"
    monkeypatch.setattr(plotting, "_matplotlib_xrd_pattern", lambda *args, **kwargs: None)

    plotting.export_xrd_pattern_png(phase.result, output, title="Fallback raster", preset_name="publication")

    png_bytes = output.read_bytes()
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"Fallback raster" in png_bytes
    assert b"XLabel\x002theta (deg)" in png_bytes


def test_publication_raster_export_uses_optional_matplotlib_when_available() -> None:
    pytest.importorskip("matplotlib")
    from diffractscout.compat.cif2peaks.plotting import _matplotlib_xrd_pattern

    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    service.simulate_phase(phase, Cif2PeaksSettings())
    assert phase.result is not None

    raster = _matplotlib_xrd_pattern(phase.result, title="Ti beta reference", preset_name="publication")

    assert raster is not None
    width, height, dpi, buffer, description = raster
    assert width > 0 and height > 0 and dpi >= 300
    assert len(buffer) == width * height * 3
    assert "Renderer: matplotlib Agg" in description


def test_gui_export_uses_custom_cif_display_names_and_preserves_original_cif_trace(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import run_simple_gui_export

    cif1 = tmp_path / TI_BETA_CIF.name
    cif2 = tmp_path / TI_NB_HCP_CIF.name
    cif1.write_bytes(TI_BETA_CIF.read_bytes())
    cif2.write_bytes(TI_NB_HCP_CIF.read_bytes())
    output = tmp_path / "custom_names.xlsx"

    result = run_simple_gui_export(
        [cif1, cif2],
        output,
        display_names={
            cif1: "Beta Ti sample A",
            str(cif2.resolve()): "HCP Ti-Nb reference",
        },
    )

    assert [row[0] for row in result.phase_rows] == ["Beta Ti sample A", "HCP Ti-Nb reference"]

    combined_rows = _worksheet_rows_by_name(output, "Combined Peaks")
    headers = combined_rows[0]
    phase_index = headers.index("phase_name")
    cif_name_index = headers.index("cif_name")
    assert "Beta Ti sample A" in {row[phase_index] for row in combined_rows[1:]}
    assert "HCP Ti-Nb reference" in {row[phase_index] for row in combined_rows[1:]}
    assert {row[cif_name_index] for row in combined_rows[1:]} == {cif1.name, cif2.name}

    summary_rows = _worksheet_rows(output, 1)
    summary_header_index = next(index for index, row in enumerate(summary_rows) if row and row[0] == "phase_name")
    summary_header = summary_rows[summary_header_index]
    summary_data = summary_rows[summary_header_index + 1 : summary_header_index + 3]
    assert "cif_path" in summary_header
    assert [row[0] for row in summary_data] == ["Beta Ti sample A", "HCP Ti-Nb reference"]
    assert {row[summary_header.index("cif_name")] for row in summary_data} == {cif1.name, cif2.name}
    assert {row[summary_header.index("cif_path")] for row in summary_data} == {str(cif1.resolve()), str(cif2.resolve())}

    with ZipFile(output) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
    assert "Beta Ti sample A" in workbook_xml
    assert "HCP Ti-Nb reference" in workbook_xml


def test_quick_export_uses_dragged_cifs_and_smart_default_output(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.quick_export import quick_export_cif2peaks

    cif1 = tmp_path / TI_BETA_CIF.name
    cif2 = tmp_path / TI_NB_HCP_CIF.name
    cif1.write_bytes(TI_BETA_CIF.read_bytes())
    cif2.write_bytes(TI_NB_HCP_CIF.read_bytes())

    result = quick_export_cif2peaks([cif1, cif2])

    assert result.output_path == tmp_path / "CIF2Peaks峰表_2个CIF.xlsx"
    assert result.output_path.exists()
    assert result.total_peaks > 0


def test_quick_export_accepts_output_override(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.quick_export import quick_export_cif2peaks

    output = tmp_path / "custom_result.xlsx"

    result = quick_export_cif2peaks([TI_BETA_CIF], output_path=output)

    assert result.output_path == output.resolve()
    assert output.exists()
    assert result.total_peaks > 0


def test_quick_export_cli_treats_diagnostic_workbook_as_success(tmp_path: Path) -> None:
    bad_cif = tmp_path / "bad.cif"
    output = tmp_path / "diagnostic.xlsx"
    bad_cif.write_text("data_bad\n_cell_length_a 3\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "diffractscout.compat.cif2peaks.quick_export", str(bad_cif), "-o", str(output)],
        cwd=ROOT,
        env=_subprocess_env(),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.exists()
    assert "未得到可用峰记录" in result.stdout
    assert "Summary" in result.stdout


def test_gui_completion_message_explains_diagnostic_workbook(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import gui_export_completion_text, run_simple_gui_export

    bad_cif = tmp_path / "bad.cif"
    output = tmp_path / "diagnostic.xlsx"
    bad_cif.write_text("data_bad\n_cell_length_a 3\n", encoding="utf-8")

    result = run_simple_gui_export([bad_cif], output)
    status_text, dialog_text = gui_export_completion_text(result)

    assert result.total_peaks == 0
    assert "诊断 Excel" in status_text
    assert "未得到可用峰记录" in dialog_text
    assert "Summary" in dialog_text
    assert str(output) in dialog_text


def test_gui_open_result_prefers_excel_file(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import open_export_result

    output = tmp_path / "result.xlsx"
    opened: list[str] = []

    opened_path = open_export_result(output, opener=lambda target: opened.append(target))

    assert opened_path == output
    assert opened == [str(output)]


def test_gui_open_result_falls_back_to_folder_when_file_open_fails(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import open_export_result

    output = tmp_path / "result.xlsx"
    opened: list[str] = []

    def opener(target: str) -> None:
        opened.append(target)
        if target == str(output):
            raise OSError("no app associated")

    opened_path = open_export_result(output, opener=opener)

    assert opened_path == output.parent
    assert opened == [str(output), str(output.parent)]


def test_gui_export_summarizes_bad_cif_with_friendly_chinese_message(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import run_simple_gui_export

    bad_cif = tmp_path / "bad.cif"
    bad_cif.write_text("data_bad\n_cell_length_a 3\n", encoding="utf-8")

    result = run_simple_gui_export([TI_BETA_CIF, bad_cif], tmp_path / "with_bad.xlsx")

    assert result.total_peaks > 0
    assert result.phase_rows[1][0] == bad_cif.name
    assert result.phase_rows[1][3] == 0
    assert "CIF" in result.phase_rows[1][4]
    assert "格式" in result.phase_rows[1][4]
    assert "Traceback" not in result.phase_rows[1][4]
    assert "[Errno" not in result.phase_rows[1][4]


def test_gui_configures_tcl_tk_environment_from_python_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from diffractscout.compat.cif2peaks.gui import _configure_tcl_tk_environment

    tcl_dir = tmp_path / "tcl" / "tcl8.6"
    tk_dir = tmp_path / "tcl" / "tk8.6"
    tcl_dir.mkdir(parents=True)
    tk_dir.mkdir(parents=True)
    (tcl_dir / "init.tcl").write_text("", encoding="utf-8")
    (tk_dir / "tk.tcl").write_text("", encoding="utf-8")
    monkeypatch.delenv("TCL_LIBRARY", raising=False)
    monkeypatch.delenv("TK_LIBRARY", raising=False)

    _configure_tcl_tk_environment(tmp_path)

    assert os.environ["TCL_LIBRARY"] == str(tcl_dir)
    assert os.environ["TK_LIBRARY"] == str(tk_dir)


def test_simple_gui_export_writes_xlsx_without_json_sidecar(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import run_simple_gui_export

    output_without_suffix = tmp_path / "gui_reference"

    result = run_simple_gui_export([TI_BETA_CIF], output_without_suffix, energy_keV="20.0")

    assert result.output_path == output_without_suffix.with_suffix(".xlsx")
    assert result.output_path.exists()
    assert not result.output_path.with_suffix(".json").exists()
    assert not result.output_path.with_suffix(".svg").exists()
    assert result.total_peaks > 0
    assert result.phase_rows[0][0] == "ti_beta_bcc_im3m.cif"
    assert result.phase_rows[0][1] == "Ti"
    assert result.phase_rows[0][3] == result.total_peaks
    assert result.phase_rows[0][4] == ""
    assert result.publication_figure_paths == []


def test_simple_gui_export_can_write_only_patterns_or_both_outputs(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import run_simple_gui_export

    patterns_only_base = tmp_path / "patterns_only.xlsx"
    both_base = tmp_path / "both.xlsx"

    patterns_only = run_simple_gui_export(
        [TI_BETA_CIF],
        patterns_only_base,
        export_peaks=False,
        export_patterns=True,
        pattern_axis="g",
    )
    both = run_simple_gui_export([TI_BETA_CIF], both_base, export_patterns=True, pattern_axis="d_spacing")

    assert patterns_only.output_path == tmp_path / "patterns_only_谱线.xlsx"
    assert patterns_only.peak_output_path is None
    assert patterns_only.pattern_output_path == patterns_only.output_path
    assert patterns_only.pattern_output_path.exists()
    assert not patterns_only_base.exists()
    rows = _worksheet_rows(patterns_only.pattern_output_path, 2)
    assert rows[1][2] == "g"

    assert both.output_path == tmp_path / "both_峰表.xlsx"
    assert both.peak_output_path == tmp_path / "both_峰表.xlsx"
    assert both.pattern_output_path == tmp_path / "both_谱线.xlsx"
    assert both.peak_output_path.exists()
    assert both.pattern_output_path.exists()
    assert not both_base.exists()


def test_simple_gui_export_can_write_publication_vector_sidecars(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import run_simple_gui_export, simple_export_message_lines

    output = tmp_path / "gui_reference.xlsx"

    result = run_simple_gui_export([TI_BETA_CIF], output, export_publication_svg=True, publication_preset="single_column")

    assert result.output_path == output
    assert result.output_path.exists()
    assert {path.suffix for path in result.publication_figure_paths} == {".eps", ".pdf", ".png", ".svg", ".tif"}
    svg_path = next(path for path in result.publication_figure_paths if path.suffix == ".svg")
    pdf_path = next(path for path in result.publication_figure_paths if path.suffix == ".pdf")
    eps_path = next(path for path in result.publication_figure_paths if path.suffix == ".eps")
    png_path = next(path for path in result.publication_figure_paths if path.suffix == ".png")
    tiff_path = next(path for path in result.publication_figure_paths if path.suffix == ".tif")
    assert svg_path.exists()
    assert pdf_path.exists()
    assert eps_path.exists()
    assert png_path.exists()
    assert tiff_path.exists()
    assert svg_path.parent == output.parent
    svg = svg_path.read_text(encoding="utf-8")
    assert "2θ (°)" in svg
    assert "Intensity (a.u.)" in svg
    assert "ti_beta_bcc_im3m.cif" in svg
    assert pdf_path.read_bytes().startswith(b"%PDF-1.4")
    assert eps_path.read_text(encoding="ascii").startswith("%!PS-Adobe-3.0 EPSF-3.0")
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert tiff_path.read_bytes().startswith(b"II*\x00")
    png_bytes = png_path.read_bytes()
    assert int.from_bytes(png_bytes[16:20], "big") == 2010
    assert int.from_bytes(png_bytes[20:24], "big") == 1410
    message_text = "\n".join(simple_export_message_lines(result, language="en"))
    assert "Publication figure" in message_text
    for path in result.publication_figure_paths:
        assert str(path) in message_text


def test_simple_gui_export_filters_by_d_range_and_records_summary(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.gui import run_simple_gui_export

    output = tmp_path / "d_filtered.xlsx"

    result = run_simple_gui_export([TI_BETA_CIF], output, d_min_A="1.0", d_max_A="2.0")

    assert result.output_path == output
    assert result.total_peaks > 0
    combined_rows = _worksheet_rows_by_name(output, "Combined Peaks")
    d_index = combined_rows[0].index("d_A")
    d_values = [float(row[d_index]) for row in combined_rows[1:]]
    assert d_values
    assert all(1.0 <= value <= 2.0 for value in d_values)
    summary = {row[0]: row[1] for row in _worksheet_rows(output, 1) if len(row) >= 2}
    assert summary["d_min_A"] == "1"
    assert summary["d_max_A"] == "2"
    assert float(summary["two_theta_min_deg"]) > 0.0
    assert float(summary["two_theta_max_deg"]) < 180.0


def _phasescout_elasticity_payload() -> dict:
    # Simple cubic-like positive-definite matrix (GPa)
    c11, c12, c44 = 250.0, 150.0, 100.0
    m = [[0.0] * 6 for _ in range(6)]
    for i in range(3):
        m[i][i] = c11
        for j in range(3):
            if i != j:
                m[i][j] = c12
    for i in range(3, 6):
        m[i][i] = c44
    return {
        "material_id": "mp-test",
        "status": "ok",
        "cij_basis": "ieee_format",
        "elastic_tensor": {"ieee_format": m, "raw": m},
        "provenance": {
            "provider": "Materials Project",
            "nature_of_data": "DFT_calculated",
            "numerical_cij": True,
            "methodology_url": "https://docs.materialsproject.org/methodology/materials-methodology/elasticity",
            "not_experimental": True,
        },
        "cif2peaks": {
            "schema": "phasescout_elasticity_v1",
            "stiffness_GPa": m,
            "coordinate_frame": "materials_project_ieee_conventional",
        },
    }


def test_load_elastic_for_cif_from_phasescout_sidecar(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.elastic_io import load_elastic_for_cif

    cif = tmp_path / "demo_phase.cif"
    cif.write_text(TI_BETA_CIF.read_text(encoding="utf-8"), encoding="utf-8")
    sidecar = tmp_path / "demo_phase_elasticity.json"
    sidecar.write_text(json.dumps(_phasescout_elasticity_payload()), encoding="utf-8")

    elastic = load_elastic_for_cif(cif)
    assert elastic is not None
    assert elastic.status in {"valid", "valid_with_warnings"}
    assert "PhaseScout" in elastic.source
    assert elastic.coordinate_frame == "materials_project_ieee_conventional"
    assert elastic.stiffness_matrix_GPa[0, 0] == pytest.approx(250.0)


def test_load_elastic_skips_non_ok_status(tmp_path: Path) -> None:
    from diffractscout.compat.cif2peaks.elastic_io import load_elastic_for_cif

    cif = tmp_path / "missing.cif"
    cif.write_text(TI_BETA_CIF.read_text(encoding="utf-8"), encoding="utf-8")
    payload = _phasescout_elasticity_payload()
    payload["status"] = "no_elasticity_data"
    payload["provenance"]["numerical_cij"] = False
    (tmp_path / "missing_elasticity.json").write_text(json.dumps(payload), encoding="utf-8")
    assert load_elastic_for_cif(cif) is None


def test_service_auto_loads_phasescout_elastic_sidecar(tmp_path: Path) -> None:
    cif = tmp_path / "auto_phase.cif"
    cif.write_text(TI_BETA_CIF.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "auto_phase_elasticity.json").write_text(
        json.dumps(_phasescout_elasticity_payload()), encoding="utf-8"
    )
    service = Cif2PeaksService()
    phase = service.load_phase(cif, auto_elastic=True)
    assert phase.elastic_constants is not None
    assert "PhaseScout" in phase.elastic_constants.source

    phase_off = service.load_phase(cif, auto_elastic=False)
    assert phase_off.elastic_constants is None


def test_combined_peaks_use_auto_loaded_phasescout_cij(tmp_path: Path) -> None:
    cif = tmp_path / "mod_phase.cif"
    cif.write_text(TI_BETA_CIF.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "mod_phase_elasticity.json").write_text(
        json.dumps(_phasescout_elasticity_payload()), encoding="utf-8"
    )
    service = Cif2PeaksService()
    phase = service.load_phase(cif)
    service.simulate_phase(phase, Cif2PeaksSettings())
    rows = combined_peak_rows([phase])
    assert rows
    assert rows[0]["young_modulus_hkl_normal_GPa"] != ""
    assert float(rows[0]["young_modulus_hkl_normal_GPa"]) > 0.0
    assert "PhaseScout" in (phase.elastic_constants.source if phase.elastic_constants else "")


def test_load_elastic_matches_paired_cif_after_rename(tmp_path: Path) -> None:
    """CIF renamed but JSON still records original paired_cif / material_id."""
    from diffractscout.compat.cif2peaks.elastic_io import load_elastic_for_cif

    payload = _phasescout_elasticity_payload()
    payload["material_id"] = "mp-150"
    payload["cif_filename"] = "mp-150_Fe_FCC.cif"
    payload["provenance"]["material_id"] = "mp-150"
    (tmp_path / "other_stem_elasticity.json").write_text(json.dumps(payload), encoding="utf-8")

    # Rename: stem differs from JSON filename, but material_id is in CIF name
    cif = tmp_path / "mp-150_renamed_copy.cif"
    cif.write_text(TI_BETA_CIF.read_text(encoding="utf-8"), encoding="utf-8")
    elastic = load_elastic_for_cif(cif)
    assert elastic is not None
    assert elastic.stiffness_matrix_GPa[0, 0] == pytest.approx(250.0)


def test_example_cifs_mark_equivalent_hermann_mauguin_symbols_as_match() -> None:
    from diffractscout.compat.cif2peaks.workbook_views import space_group_symbols_equivalent, structure_status_rows

    assert space_group_symbols_equivalent("I m 3 m", "Im-3m")
    assert space_group_symbols_equivalent("P 63/m m c", "P6_3/mmc")
    assert not space_group_symbols_equivalent("P 1", "Pm-3m")

    service = Cif2PeaksService()
    phases = [service.load_phase(TI_BETA_CIF), service.load_phase(TI_NB_HCP_CIF)]
    rows = structure_status_rows(phases)
    headers = rows[0]
    status_i = headers.index("space_group_status")
    cif_i = headers.index("space_group_from_cif")
    det_i = headers.index("space_group_detected")
    by_phase = {row[headers.index("phase_name")]: row for row in rows[1:]}

    beta = by_phase["ti_beta_bcc_im3m"]
    hcp = by_phase["ti_nb_hcp_p63mmc"]
    assert "m 3 m" in beta[cif_i] or "m3m" in beta[cif_i].replace(" ", "").lower()
    assert beta[cif_i] != beta[det_i]
    assert hcp[cif_i] != hcp[det_i]
    assert beta[status_i] == "match"
    assert hcp[status_i] == "match"


def test_overlap_records_only_pairs_inside_the_stated_window() -> None:
    from diffractscout.compat.cif2peaks.workbook_views import overlap_peak_records

    rows = [
        {
            "phase_name": "alpha",
            "hkl": "(1 0 0)",
            "d_A": 2.000,
            "two_theta_current_deg": 45.000,
            "relative_intensity": 100,
        },
        {
            "phase_name": "beta",
            "hkl": "(1 1 0)",
            "d_A": 2.001,
            "two_theta_current_deg": 45.020,
            "relative_intensity": 80,
        },
        {
            "phase_name": "beta",
            "hkl": "(2 0 0)",
            "d_A": 1.200,
            "two_theta_current_deg": 80.000,
            "relative_intensity": 40,
        },
    ]

    inside = overlap_peak_records(rows, delta_two_theta_deg=0.05, delta_d_A=0.005)
    outside = overlap_peak_records(rows, delta_two_theta_deg=0.001, delta_d_A=0.0001)

    assert len(inside) == 1
    assert inside[0]["phase_a"] == "alpha"
    assert inside[0]["phase_b"] == "beta"
    assert inside[0]["hkl_b"] == "(1 1 0)"
    assert inside[0]["match_by"] == "two_theta+d"
    assert outside == []


def test_workbook_includes_working_structure_and_conditional_overlap(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phases = [
        service.load_phase(TI_BETA_CIF),
        service.load_phase(TI_NB_HCP_CIF),
        service.load_phase(TI_NB_ORTHO_CIF),
    ]
    settings = Cif2PeaksSettings()
    service.simulate_phases(phases, settings)
    output = tmp_path / "usable.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, settings), output)

    names = _workbook_sheet_names(output)
    assert names[1] == "工作峰表"
    assert "Structure" in names
    assert "Overlap" in names

    working = _worksheet_rows_by_name(output, "工作峰表")
    assert working[0] == [
        "相名",
        "晶面 hkl",
        "d 间距 (Å)",
        "2θ 当前设置 (°)",
        "相对强度",
        "多重性",
        "提示",
        "晶面法向杨氏模量 (GPa)",
        "弹性常数状态",
    ]
    assert len(working) > 1
    assert {row[0] for row in working[1:]} >= {phase.phase_name for phase in phases}

    structure = _worksheet_rows_by_name(output, "Structure")
    headers = structure[0]
    by_phase = {row[headers.index("phase_name")]: row for row in structure[1:]}
    ortho = by_phase["ti_nb_orthorhombic_cmcm_partial_occupancy"]
    assert float(ortho[headers.index("a_A")]) > 0
    assert ortho[headers.index("occupancy_status")] == "partial"
    assert ortho[headers.index("occupancy_sites")]
    assert by_phase["ti_beta_bcc_im3m"][headers.index("occupancy_status")] == "full"
    beta = by_phase["ti_beta_bcc_im3m"]
    hcp = by_phase["ti_nb_hcp_p63mmc"]
    assert beta[headers.index("space_group_from_cif")] != beta[headers.index("space_group_detected")]
    assert hcp[headers.index("space_group_from_cif")] != hcp[headers.index("space_group_detected")]
    assert beta[headers.index("space_group_status")] == "match"
    assert hcp[headers.index("space_group_status")] == "match"

    overlap = _worksheet_rows_by_name(output, "Overlap")
    assert overlap[0][0] == "overlap_rule"
    assert overlap[1][0] == "delta_two_theta_deg"
    header_row = next(row for row in overlap if row and row[0] == "phase_a")
    data_rows = overlap[overlap.index(header_row) + 1 :]
    window_tth = float(overlap[1][1])
    window_d = float(overlap[2][1])
    for row in data_rows:
        assert float(row[header_row.index("delta_two_theta_deg")]) <= window_tth or float(
            row[header_row.index("delta_d_A")]
        ) <= window_d


def test_single_phase_workbook_omits_overlap_sheet(tmp_path: Path) -> None:
    service = Cif2PeaksService()
    phase = service.load_phase(TI_BETA_CIF)
    service.simulate_phase(phase, Cif2PeaksSettings())
    output = tmp_path / "single.xlsx"

    export_cif2peaks_workbook(Cif2PeaksExportPayload([phase], Cif2PeaksSettings()), output)

    assert "Overlap" not in _workbook_sheet_names(output)
    assert "工作峰表" in _workbook_sheet_names(output)
    assert "Structure" in _workbook_sheet_names(output)


def test_workbook_binds_sibling_cij_and_labels_missing_without_inventing(tmp_path: Path) -> None:
    paired = tmp_path / "paired.cif"
    missing = tmp_path / "missing.cif"
    paired.write_text(TI_BETA_CIF.read_text(encoding="utf-8"), encoding="utf-8")
    missing.write_text(TI_NB_HCP_CIF.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "paired_elasticity.json").write_text(
        json.dumps(_phasescout_elasticity_payload()), encoding="utf-8"
    )

    service = Cif2PeaksService()
    phases = service.load_phases([paired, missing], auto_elastic=True)
    service.simulate_phases(phases, Cif2PeaksSettings())
    output = tmp_path / "cij_bind.xlsx"
    export_cif2peaks_workbook(Cif2PeaksExportPayload(phases, Cif2PeaksSettings()), output)

    working = _worksheet_rows_by_name(output, "工作峰表")
    headers = working[0]
    modulus_i = headers.index("晶面法向杨氏模量 (GPa)")
    status_i = headers.index("弹性常数状态")
    by_phase = {}
    for row in working[1:]:
        by_phase.setdefault(row[0], row)
    assert float(by_phase["paired"][modulus_i]) > 0
    assert by_phase["paired"][status_i] in {"valid", "valid_with_warnings"}
    assert by_phase["missing"][modulus_i] == ""
    assert by_phase["missing"][status_i] == "no_elastic_constants"

    elastic_rows = _worksheet_rows_by_name(output, "Elastic Constants")
    elastic_headers = elastic_rows[0]
    c11_i = elastic_headers.index("C11")
    status_col = elastic_headers.index("elastic_status")
    paired_row = next(row for row in elastic_rows[1:] if row[0] == "paired")
    missing_row = next(row for row in elastic_rows[1:] if row[0] == "missing")
    assert paired_row[c11_i] != ""
    assert float(paired_row[c11_i]) == pytest.approx(250.0)
    assert missing_row[status_col] == "no_elastic_constants"
    assert missing_row[c11_i] == ""
    assert all(missing_row[elastic_headers.index(f"C{i}{j}")] == "" for i in range(1, 7) for j in range(1, 7))
