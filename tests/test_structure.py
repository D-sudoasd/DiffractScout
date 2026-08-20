from pathlib import Path
import subprocess
import sys
import warnings

import gemmi
import pytest

from diffractscout.structure import load_structure, structure_mass_metadata


def test_load_synthetic_fcc(demo_inputs: Path) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    assert not any("OLD_ERROR_HANDLING" in str(item.message) for item in caught)
    assert structure.formula == "Al"
    assert structure.space_group_number == 225
    assert structure.space_group_symbol.replace(" ", "") == "Fm-3m"
    assert structure.site_count_asymmetric == 1
    assert structure.site_count_unit_cell == 4
    assert not structure.has_partial_occupancy
    assert structure.small_structure.sites[0].occ == 1.0
    assert structure.structure_factor_structure.sites[0].occ == 1.0 / 48.0
    assert len(structure.cif_sha256) == 64


def test_space_group_number_is_used_when_symbol_is_absent(tmp_path: Path) -> None:
    cif = tmp_path / "number_only.cif"
    cif.write_text(
        """data_number_only
_cell_length_a 4
_cell_length_b 4
_cell_length_c 4
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_IT_number 225
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al1 Al 0 0 0 1
""",
        encoding="utf-8",
    )
    structure = load_structure(cif)
    assert structure.space_group_number == 225
    assert structure.source_metadata["space_group_resolution_source"] == "cif_number"


def _write_space_group_variant(
    path: Path,
    *,
    number: int,
    symbol: str | None,
    cell: tuple[float, float, float, float, float, float],
    element: str = "Al",
    fractional: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> None:
    symbol_line = (
        f"_space_group_name_H-M_alt '{symbol}'\n" if symbol is not None else ""
    )
    path.write_text(
        f"""data_space_group_variant
_cell_length_a {cell[0]}
_cell_length_b {cell[1]}
_cell_length_c {cell[2]}
_cell_angle_alpha {cell[3]}
_cell_angle_beta {cell[4]}
_cell_angle_gamma {cell[5]}
{symbol_line}_space_group_IT_number {number}
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
{element}1 {element} {fractional[0]} {fractional[1]} {fractional[2]} 1
""",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("name", "number", "symbol", "cell", "hkl", "element", "fractional"),
    [
        ("fcc", 225, "F m -3 m", (4, 4, 4, 90, 90, 90), (1, 1, 1), "Al", (0.0, 0.0, 0.0)),
        ("bcc", 229, "I m -3 m", (3, 3, 3, 90, 90, 90), (1, 1, 0), "Fe", (0.0, 0.0, 0.0)),
        ("r_hex", 166, "R -3 m:H", (4, 4, 6, 90, 90, 120), (0, 0, 3), "Al", (0.0, 0.0, 0.0)),
        ("r_rhom", 166, "R -3 m:R", (5, 5, 5, 75, 75, 75), (1, 1, 1), "Al", (0.0, 0.0, 0.0)),
    ],
)
def test_number_only_space_group_reparse_matches_explicit_symbol(
    tmp_path: Path,
    name: str,
    number: int,
    symbol: str,
    cell: tuple[float, float, float, float, float, float],
    hkl: tuple[int, int, int],
    element: str,
    fractional: tuple[float, float, float],
) -> None:
    number_only_path = tmp_path / f"{name}_number_only.cif"
    explicit_path = tmp_path / f"{name}_explicit.cif"
    _write_space_group_variant(
        number_only_path,
        number=number,
        symbol=None,
        cell=cell,
        element=element,
        fractional=fractional,
    )
    _write_space_group_variant(
        explicit_path,
        number=number,
        symbol=symbol,
        cell=cell,
        element=element,
        fractional=fractional,
    )

    number_only = load_structure(number_only_path)
    explicit = load_structure(explicit_path)

    assert number_only.space_group_symbol == explicit.space_group_symbol
    assert number_only.site_count_unit_cell == explicit.site_count_unit_cell
    assert number_only.formula == explicit.formula
    assert number_only.source_metadata["space_group_reparsed_with_resolved_symbol"] is True
    assert explicit.source_metadata["space_group_reparsed_with_resolved_symbol"] is False
    for key in ("formula_weight_g_mol", "density_g_cm3"):
        assert structure_mass_metadata(number_only)[key] == pytest.approx(
            structure_mass_metadata(explicit)[key], rel=1e-12
        )

    number_only_factor = gemmi.StructureFactorCalculatorX(number_only.small_structure.cell)
    explicit_factor = gemmi.StructureFactorCalculatorX(explicit.small_structure.cell)
    number_only_sf = number_only_factor.calculate_sf_from_small_structure(
        number_only.structure_factor_structure, hkl
    )
    explicit_sf = explicit_factor.calculate_sf_from_small_structure(
        explicit.structure_factor_structure, hkl
    )
    assert abs(number_only_sf) ** 2 == pytest.approx(abs(explicit_sf) ** 2, rel=1e-12)

    # If spglib is installed, a complete authoritative symmetry declaration
    # must not be reported as a mismatch merely because the CIF used a number.
    assert number_only.source_metadata["symmetry_crosscheck"] != "mismatch"
    assert explicit.source_metadata["symmetry_crosscheck"] != "mismatch"


def _write_number_only_r_cif(path: Path, *, rhombohedral: bool) -> None:
    if rhombohedral:
        cell = """_cell_length_a 5
_cell_length_b 5
_cell_length_c 5
_cell_angle_alpha 75
_cell_angle_beta 75
_cell_angle_gamma 75"""
    else:
        cell = """_cell_length_a 4
_cell_length_b 4
_cell_length_c 6
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120"""
    path.write_text(
        f"""data_number_only_r
{cell}
_space_group_IT_number 146
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al1 Al 0 0 0 1
""",
        encoding="utf-8",
    )


def test_number_only_r_group_uses_cell_metric_to_select_setting(tmp_path: Path) -> None:
    rhombohedral = tmp_path / "rhombohedral.cif"
    hexagonal = tmp_path / "hexagonal.cif"
    _write_number_only_r_cif(rhombohedral, rhombohedral=True)
    _write_number_only_r_cif(hexagonal, rhombohedral=False)
    r_structure = load_structure(rhombohedral)
    h_structure = load_structure(hexagonal)
    assert r_structure.space_group_symbol.endswith(":R")
    assert h_structure.space_group_symbol.endswith(":H")
    assert r_structure.source_metadata["space_group_setting"] == "R"
    assert h_structure.source_metadata["space_group_setting"] == "H"


@pytest.mark.parametrize(
    ("symbol", "rhombohedral", "expected", "expected_source"),
    [
        ("R -3:H", False, "H", "cif_symbol"),
        ("R -3:R", True, "R", "cif_symbol"),
        ("R -3", False, "H", "cif_symbol_metric_H"),
        ("R -3", True, "R", "cif_symbol_metric_R"),
    ],
)
def test_explicit_r_family_symbol_preserves_or_resolves_setting(
    tmp_path: Path,
    symbol: str,
    rhombohedral: bool,
    expected: str,
    expected_source: str,
) -> None:
    if rhombohedral:
        cell = """_cell_length_a 5
_cell_length_b 5
_cell_length_c 5
_cell_angle_alpha 75
_cell_angle_beta 75
_cell_angle_gamma 75"""
    else:
        cell = """_cell_length_a 4
_cell_length_b 4
_cell_length_c 6
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120"""
    cif = tmp_path / f"explicit_{expected}_{symbol.replace(':', '_').replace(' ', '_')}.cif"
    cif.write_text(
        f"""data_explicit_r
{cell}
_space_group_name_H-M_alt '{symbol}'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al1 Al 0 0 0 1
""",
        encoding="utf-8",
    )
    structure = load_structure(cif)
    assert structure.space_group_symbol.endswith(f":{expected}")
    assert structure.source_metadata["space_group_setting"] == expected
    assert structure.source_metadata["space_group_resolution_source"] == expected_source


def test_unqualified_explicit_r_symbol_fails_on_ambiguous_metric(tmp_path: Path) -> None:
    cif = tmp_path / "ambiguous_r.cif"
    cif.write_text(
        """data_ambiguous_r
_cell_length_a 5
_cell_length_b 5
_cell_length_c 5
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_name_H-M_alt 'R -3'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al1 Al 0 0 0 1
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not distinguish"):
        load_structure(cif)


@pytest.mark.parametrize("occupancy", ["?", ".", "nan", "inf", "-0.1", "1.1"])
def test_unknown_nonfinite_or_out_of_range_occupancy_fails_closed(
    tmp_path: Path, occupancy: str
) -> None:
    cif = tmp_path / "invalid_occupancy.cif"
    cif.write_text(
        f"""data_invalid_occupancy
_cell_length_a 4
_cell_length_b 4
_cell_length_c 4
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_IT_number 225
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al1 Al 0 0 0 {occupancy}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="occupancy"):
        load_structure(cif)


@pytest.mark.parametrize("coordinate", ["?", ".", "nan", "inf", "-inf"])
def test_unknown_or_nonfinite_fractional_coordinate_fails_before_gemmi(
    tmp_path: Path, coordinate: str
) -> None:
    cif = tmp_path / "invalid_fractional_coordinate.cif"
    cif.write_text(
        f"""data_invalid_fractional_coordinate
_cell_length_a 4
_cell_length_b 4
_cell_length_c 4
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_IT_number 225
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al1 Al {coordinate} 0 0 1
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="fractional coordinate"):
        load_structure(cif)


def test_invalid_fractional_coordinate_subprocess_exits_without_native_crash(
    tmp_path: Path,
) -> None:
    cif = tmp_path / "invalid_fractional_coordinate_subprocess.cif"
    cif.write_text(
        """data_invalid_fractional_coordinate_subprocess
_cell_length_a 4
_cell_length_b 4
_cell_length_c 4
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_IT_number 225
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al1 Al ? 0 0 1
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from diffractscout.structure import load_structure; "
                f"load_structure({str(cif)!r})"
            ),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parents[1],
    )
    assert result.returncode == 1
    assert "ValueError" in result.stderr
    assert "fractional coordinate" in result.stderr


def test_spglib_dict_and_attribute_datasets_are_supported(
    demo_inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import diffractscout.structure as structure_module

    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")

    class DictSpglib:
        @staticmethod
        def get_symmetry_dataset(_cell: object, **_kwargs: object) -> dict[str, object]:
            return {"number": 225, "international": "Fm-3m", "choice": ""}

    monkeypatch.setitem(sys.modules, "spglib", DictSpglib())
    assert structure_module._spglib_crosscheck(
        structure.small_structure,
        225,
        "F m -3 m",
    )[2] == "match"

    class Dataset:
        number = 225
        international = "Fm-3m"
        choice = ""

    class AttributeSpglib:
        @staticmethod
        def get_symmetry_dataset(_cell: object, **_kwargs: object) -> Dataset:
            return Dataset()

    monkeypatch.setitem(sys.modules, "spglib", AttributeSpglib())
    assert structure_module._spglib_crosscheck(
        structure.small_structure,
        225,
        "F m -3 m",
    )[2] == "match"
