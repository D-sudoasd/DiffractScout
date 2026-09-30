import csv
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from diffractscout.cli import main
from diffractscout.models import CandidateRecord
from diffractscout.phase_cif import (
    adapt_cif,
    fetch_prototypes,
    resolve_occupancies,
    scaffold_resource,
    select_prototype,
)
from diffractscout.structure import load_structure
from diffractscout.utils import sha256_file

ROOT = Path(__file__).parents[1]
HCP = ROOT / "examples" / "inherited_cif2peaks" / "ti_nb_hcp_p63mmc.cif"
CMCM = ROOT / "examples" / "inherited_cif2peaks" / "ti_nb_orthorhombic_cmcm_partial_occupancy.cif"
BCC = ROOT / "examples" / "inherited_cif2peaks" / "ti_beta_bcc_im3m.cif"
ELEMENTS = ("Ti", "Al", "V")
CITATION = "Test citation for a caller-supplied lattice edit."


def _candidate(
    material_id: str,
    formula: str,
    space_group_number: int,
    *,
    energy: float | None = 0.0,
    symbol: str = "",
    deprecated: bool = False,
) -> CandidateRecord:
    return CandidateRecord(
        material_id=material_id,
        formula=formula,
        energy_above_hull_eV_atom=energy,
        space_group=symbol,
        space_group_number=space_group_number,
        deprecated=deprecated,
    )


def _tag(text: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}\s+(\S+)", text)
    assert match is not None, name
    return match.group(1).strip("'\"")


def _atom_rows(text: str, label: str) -> list[list[str]]:
    return [line.split() for line in text.splitlines() if line.startswith(label + " ")]


def test_nominal_tc4_occupancies_sum_to_one() -> None:
    basis, _note, occupancies = resolve_occupancies(nominal="tc4")
    assert basis == "nominal_grade"
    assert occupancies == {
        "Ti": Decimal("0.86204"),
        "Al": Decimal("0.10195"),
        "V": Decimal("0.03601"),
    }
    assert sum(occupancies.values(), Decimal(0)) == Decimal(1)
    _basis, _other, from_weight = resolve_occupancies(weight_percent="Ti=90,Al=6,V=4")
    assert from_weight == occupancies


def test_composition_percentages_must_be_positive_and_complete() -> None:
    with pytest.raises(ValueError, match="100"):
        resolve_occupancies(weight_percent="Ti=50,Al=40")
    with pytest.raises(ValueError, match="positive"):
        resolve_occupancies(weight_percent="Ti=96,Al=0,V=4")
    with pytest.raises(ValueError, match="exactly one"):
        resolve_occupancies(nominal="tc4", weight_percent="Ti=90,Al=6,V=4")


def test_alpha_family_rejects_intermetallic_and_omega_prototypes() -> None:
    ti3al = _candidate("mp-ti3al", "Ti3Al", 194, symbol="P6_3/mmc")
    omega = _candidate("mp-omega", "Ti", 191, symbol="P6/mmm")
    c14 = _candidate("mp-c14", "TiAl2", 194, symbol="P6_3/mmc")
    alpha = _candidate("mp-46", "Ti", 194, energy=0.02, symbol="P6_3/mmc")
    chosen = select_prototype(
        [ti3al, omega, c14, alpha],
        phase="alpha",
        elements=ELEMENTS,
        host="Ti",
    )
    assert chosen is not None
    assert chosen.material_id == "mp-46"
    assert (
        select_prototype([ti3al, omega, c14], phase="alpha", elements=ELEMENTS, host="Ti")
        is None
    )
    assert (
        select_prototype(
            [_candidate("mp-46", "Ti", 194, deprecated=True)],
            phase="alpha",
            elements=ELEMENTS,
            host="Ti",
        )
        is None
    )


def test_beta_prefers_elemental_host_and_rejects_pure_vanadium() -> None:
    vanadium = _candidate("mp-v", "V", 229, energy=0.0)
    alloy = _candidate("mp-tiv", "TiV", 229, energy=0.01)
    beta = _candidate("mp-73", "Ti", 229, energy=0.15)
    chosen = select_prototype(
        [vanadium, alloy, beta],
        phase="beta",
        elements=ELEMENTS,
        host="Ti",
    )
    assert chosen is not None
    assert chosen.material_id == "mp-73"
    assert select_prototype([vanadium], phase="beta", elements=ELEMENTS, host="Ti") is None


def test_alpha_double_prime_rejects_an_oxide() -> None:
    oxide = _candidate("mp-o", "TiO2", 63, symbol="Cmcm")
    assert (
        select_prototype([oxide], phase="alpha-double-prime", elements=ELEMENTS, host="Ti")
        is None
    )


def test_hcp_lattice_edit_keeps_space_group_and_coordinates(tmp_path: Path) -> None:
    source_hash = sha256_file(HCP)
    destination = tmp_path / "alpha.cif"
    result = adapt_cif(
        HCP,
        destination,
        nominal="TC4",
        a=2.935,
        b=2.935,
        c=4.673,
        citation=CITATION,
    )

    text = destination.read_text(encoding="utf-8")
    assert text.startswith("# DiffractScout adapt:")
    assert CITATION in text
    assert "McHargue" in text
    assert _tag(text, "_cell_length_a") == "2.935"
    assert _tag(text, "_cell_length_b") == "2.935"
    assert _tag(text, "_cell_length_c") == "4.673"
    assert _tag(text, "_cell_angle_gamma") == "120"
    assert _tag(text, "_cell_volume") != "35.080"
    assert _atom_rows(text, "Ti1")[0][2:5] == ["0.3333", "0.6667", "0.25"]
    loaded = load_structure(destination)
    assert loaded.space_group_number == 194
    assert loaded.source_metadata["symmetry_crosscheck"] == "match"
    assert result.symmetry_crosscheck == "match"
    assert result.occupancies == {"Ti": "0.86204", "Al": "0.10195", "V": "0.03601"}
    sidecar = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["source_sha256"] == source_hash
    assert sidecar["composition_basis"] == "nominal_grade"
    assert sidecar["lattice_edits"]["a"]["to"] == "2.935"
    assert sidecar["coordinates_unchanged"] == ["x", "y", "z"]
    assert sha256_file(HCP) == source_hash


def test_cmcm_lattice_edit_leaves_prototype_y(tmp_path: Path) -> None:
    destination = tmp_path / "alpha-double-prime.cif"
    adapt_cif(
        CMCM,
        destination,
        nominal="ti64",
        a=2.956,
        b=5.05,
        c=4.61,
        citation=CITATION,
    )

    text = destination.read_text(encoding="utf-8")
    assert "Brown, A.R.G." in text
    assert _tag(text, "_cell_length_a") == "2.956"
    assert _tag(text, "_cell_length_b") == "5.05"
    assert _tag(text, "_cell_length_c") == "4.61"
    assert _tag(text, "_cell_volume") != "71.491"
    for label in ("Ti1", "Al1", "V1"):
        assert _atom_rows(text, label)[0][2:5] == ["0", "0.2", "0.25"]
    loaded = load_structure(destination)
    assert loaded.space_group_number == 63
    assert loaded.source_metadata["symmetry_crosscheck"] == "match"


def test_cited_fractional_coordinate_replaces_only_that_axis(tmp_path: Path) -> None:
    destination = tmp_path / "moved-y.cif"
    adapt_cif(
        CMCM,
        destination,
        nominal="ti-6al-4v",
        fract={"y": 0.166667},
        citation=CITATION,
    )
    text = destination.read_text(encoding="utf-8")
    assert _atom_rows(text, "Ti1")[0][2:5] == ["0", "0.166667", "0.25"]
    assert load_structure(destination).space_group_number == 63


def test_adapt_refuses_missing_citation_source_overwrite_and_bad_symmetry(tmp_path: Path) -> None:
    missing = tmp_path / "missing-citation.cif"
    with pytest.raises(ValueError, match="citation"):
        adapt_cif(HCP, missing, nominal="tc4", a=2.935, b=2.935, c=4.673)
    assert not missing.exists()

    source = tmp_path / "source.cif"
    source.write_bytes(CMCM.read_bytes())
    before = sha256_file(source)
    with pytest.raises(ValueError, match="source"):
        adapt_cif(source, source, nominal="tc4")
    assert sha256_file(source) == before

    existing = tmp_path / "existing.cif"
    existing.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        adapt_cif(CMCM, existing, nominal="tc4")
    assert existing.read_text(encoding="utf-8") == "keep"

    broken = tmp_path / "broken.cif"
    with pytest.raises(ValueError, match="cross-check"):
        adapt_cif(BCC, broken, nominal="tc4", gamma=95, citation=CITATION)
    assert not broken.exists()
    assert not Path(str(broken).replace(".cif", ".adapt.json")).exists()


def test_beta_composition_edit_keeps_im3m(tmp_path: Path) -> None:
    destination = tmp_path / "beta.cif"
    result = adapt_cif(BCC, destination, nominal="tc4")
    text = destination.read_text(encoding="utf-8")
    assert "Wyckoff" in text
    assert "_exptl_crystal_density_diffrn" not in text
    assert _tag(text, "_cell_length_a") == "3.3065"
    assert "Ti0.86204" in text
    loaded = load_structure(destination)
    assert loaded.space_group_number == 229
    assert loaded.source_metadata["symmetry_crosscheck"] == "match"
    assert result.warnings
    assert all(item.startswith("Partial occupancies are included") for item in result.warnings)
    sidecar = json.loads((tmp_path / "beta.adapt.json").read_text(encoding="utf-8"))
    assert sidecar["citation"] is None
    assert sidecar["lattice_edits"] == {}


def test_equivalent_lattice_axes_are_linked_and_conflicts_refused(tmp_path: Path) -> None:
    cubic = adapt_cif(BCC, tmp_path / "cubic.cif", nominal="tc4", a=3.2, citation=CITATION)
    assert load_structure(cubic.cif_path).cell_parameters[:3] == (3.2, 3.2, 3.2)
    sidecar = json.loads(cubic.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["lattice_axes_implied_by_symmetry"] == ["b", "c"]
    hexagonal = adapt_cif(HCP, tmp_path / "hex.cif", nominal="tc4", a=2.94, c=4.69, citation=CITATION)
    assert load_structure(hexagonal.cif_path).cell_parameters[:3] == (2.94, 2.94, 4.69)
    with pytest.raises(ValueError, match="equal cell axes"):
        adapt_cif(BCC, tmp_path / "conflict.cif", nominal="tc4", a=3.2, b=3.3, citation=CITATION)


def test_formula_and_Z_use_expanded_multiplicities(tmp_path: Path) -> None:
    result = adapt_cif(BCC, tmp_path / "formula.cif", nominal="tc4")
    text = result.cif_path.read_text(encoding="utf-8")
    assert _tag(text, "_cell_formula_units_Z") == "2"
    expected = 0.86204 * 47.867 + 0.10195 * 26.9815385 + 0.03601 * 50.9415
    assert float(_tag(text, "_chemical_formula_weight")) == pytest.approx(expected, rel=1e-8)
    with pytest.raises(ValueError, match="interstitial"):
        adapt_cif(BCC, tmp_path / "oxygen.cif", atomic_percent="Ti=90,O=10")


def test_adapt_publish_race_never_replaces_external_files(tmp_path, monkeypatch):
    import diffractscout.phase_cif as phase_cif

    original = phase_cif._publish_new_file
    output = tmp_path / "race.cif"

    def publish(temporary, destination):
        if destination == output:
            destination.write_text("external CIF", encoding="utf-8")
        original(temporary, destination)

    monkeypatch.setattr(phase_cif, "_publish_new_file", publish)
    with pytest.raises(FileExistsError):
        adapt_cif(BCC, output, nominal="tc4")
    assert output.read_text(encoding="utf-8") == "external CIF"
    assert not output.with_suffix(".adapt.json").exists()


def test_adapt_sidecar_race_preserves_external_sidecar(tmp_path, monkeypatch):
    import diffractscout.phase_cif as phase_cif

    original = phase_cif._publish_new_file
    output = tmp_path / "race.cif"
    sidecar = output.with_suffix(".adapt.json")

    def publish(temporary, destination):
        if destination == sidecar:
            destination.write_text("external sidecar", encoding="utf-8")
        original(temporary, destination)

    monkeypatch.setattr(phase_cif, "_publish_new_file", publish)
    with pytest.raises(FileExistsError):
        adapt_cif(BCC, output, nominal="tc4")
    assert sidecar.read_text(encoding="utf-8") == "external sidecar"
    assert not output.exists()


def test_distinct_fractional_axis_and_mixed_site_are_refused(tmp_path: Path) -> None:
    distinct = tmp_path / "two-y.cif"
    distinct.write_text(
        """data_test
_symmetry_space_group_name_H-M 'P 1'
_cell_length_a 4
_cell_length_b 5
_cell_length_c 6
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_symmetry_equiv_pos_as_xyz
x,y,z
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Ti1 Ti 0.10 0.20 0.30 1
Ti2 Ti 0.10 0.40 0.30 1
""",
        encoding="utf-8",
    )
    refused = tmp_path / "refused.cif"
    with pytest.raises(ValueError, match="fractional y"):
        adapt_cif(distinct, refused, nominal="tc4", fract={"y": 0.2}, citation=CITATION)
    assert not refused.exists()

    mixed = tmp_path / "mixed.cif"
    mixed.write_text(
        distinct.read_text(encoding="utf-8").replace(
            "Ti2 Ti 0.10 0.40 0.30 1",
            "O1 O 0.10 0.20 0.30 1",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="interstitial"):
        adapt_cif(mixed, tmp_path / "mixed-out.cif", nominal="tc4")


def test_interstitial_site_is_preserved(tmp_path: Path) -> None:
    source = tmp_path / "with-oxygen.cif"
    source.write_text(
        """data_test
_symmetry_space_group_name_H-M 'P 1'
_cell_length_a 4.2
_cell_length_b 5.3
_cell_length_c 6.4
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_symmetry_equiv_pos_as_xyz
x,y,z
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Ti1 Ti 0.13 0.27 0.41 1
O1 O 0.61 0.19 0.73 1
""",
        encoding="utf-8",
    )
    destination = tmp_path / "kept-oxygen.cif"
    adapt_cif(source, destination, nominal="tc4")
    loaded = load_structure(destination)
    assert {site.element.name for site in loaded.small_structure.sites} == {"Ti", "Al", "V", "O"}
    assert loaded.source_metadata["symmetry_crosscheck"] == "match"
    assert _atom_rows(destination.read_text(encoding="utf-8"), "O1")[0][2:5] == ["0.61", "0.19", "0.73"]


def test_packaged_scaffold_is_the_cod_entry() -> None:
    data = scaffold_resource().read_bytes()
    assert b"1523304" in data
    assert b"Nb" in data


def test_non_ti_fetch_does_not_receive_ti_scaffold(tmp_path: Path) -> None:
    result = fetch_prototypes("Ni", tmp_path / "nickel", phases=["alpha-double-prime"])
    assert result.exit_code == 3
    assert result.records[0].status == "missing"
    assert not (result.output_dir / "alpha-double-prime.cif").exists()


def test_fetch_query_and_download_errors_redact_provider_credentials(tmp_path):
    from diffractscout.models import DownloadArtifact

    key = "fetch-secret-key"

    class QueryFailure:
        api_key = key

        def search_subsystem(self, *_args, **_kwargs):
            raise RuntimeError(f"Query failed for {key}")

    with pytest.raises(RuntimeError) as captured:
        fetch_prototypes("TC4", tmp_path / "query", phases=["alpha"], provider=QueryFailure())
    assert key not in str(captured.value)
    assert "[redacted]" in str(captured.value)

    class DownloadFailure:
        api_key = key

        def search_subsystem(self, *_args, **_kwargs):
            return [_candidate("mp-46", "Ti", 194)]

        def download_candidates(self, candidates, *_args, **_kwargs):
            return [DownloadArtifact(candidates[0], None, status="failed", error=f"download failed for {key}")]

    result = fetch_prototypes("TC4", tmp_path / "download", phases=["alpha"], provider=DownloadFailure())
    assert result.exit_code == 3
    assert key not in result.index_path.read_text(encoding="utf-8")
    assert "[redacted]" in result.index_path.read_text(encoding="utf-8")


def test_fetch_alpha_double_prime_uses_scaffold_without_a_provider(tmp_path: Path) -> None:
    output = tmp_path / "prototypes"
    result = fetch_prototypes("Ti-6Al-4V", output, phases=["alpha-double-prime"])

    assert result.exit_code == 0
    assert result.host == "Ti"
    copied = output / "alpha-double-prime.cif"
    assert copied.read_bytes() == scaffold_resource().read_bytes()
    rows = list(csv.DictReader(result.index_path.open(encoding="utf-8")))
    assert rows[0]["status"] == "scaffold"
    assert rows[0]["target_composition"] == "false"
    assert rows[0]["source"] == "COD 1523304"
    assert "not the target alloy" in rows[0]["note"]
    assert "Nb" in rows[0]["formula"]


def test_template_supplies_alpha_without_a_key(tmp_path: Path) -> None:
    output = tmp_path / "from-template"
    result = fetch_prototypes(
        "Ti-Al-V",
        output,
        phases=["alpha"],
        templates={"alpha": HCP},
    )
    assert result.exit_code == 0
    assert (output / "alpha.cif").read_bytes() == HCP.read_bytes()
    assert result.records[0].status == "template"
    assert result.records[0].target_composition is False


def test_subsystem_cap_stops_before_a_provider_call(tmp_path: Path) -> None:
    class Boom:
        def search_subsystem(self, *_args, **_kwargs):
            raise AssertionError("subsystem cap should stop before the provider")

    with pytest.raises(ValueError, match="7"):
        fetch_prototypes(
            "Ti-Al-V",
            tmp_path / "capped",
            phases=["alpha"],
            provider=Boom(),
            max_subsystems=1,
        )
    assert not (tmp_path / "capped").exists()


def test_downloaded_prototype_is_copied_under_a_stable_name(tmp_path: Path) -> None:
    class Provider:
        def search_subsystem(self, chemsys, **_kwargs):
            if chemsys != "Ti":
                return []
            return [_candidate("mp-46", "Ti", 194, energy=0.02, symbol="P6_3/mmc")]

        def download_candidates(self, candidates, output_dir, **kwargs):
            from diffractscout.models import DownloadArtifact

            assert kwargs["include_elasticity"] is False
            assert kwargs["conventional_unit_cell"] is True
            path = Path(output_dir) / "mp-46.cif"
            path.write_text(
                "data_mp\n_symmetry_space_group_name_H-M 'P 1'\n"
                "_cell_length_a 1\n_cell_length_b 1\n_cell_length_c 1\n"
                "_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n"
                "loop_\n_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n"
                "0 0 0\n",
                encoding="utf-8",
            )
            return [
                DownloadArtifact(candidate=candidates[0], cif_path=path, status="ok")
            ]

    output = tmp_path / "downloaded"
    result = fetch_prototypes(
        "Ti64",
        output,
        phases=["alpha"],
        provider=Provider(),
    )
    assert result.exit_code == 0
    text = (output / "alpha.cif").read_text(encoding="utf-8")
    assert "P 1" in text
    assert result.records[0].target_composition is False
    assert result.records[0].space_group == "194"
    assert "P1" in result.records[0].note
    assert not list(output.glob("*elasticity*"))


def test_partial_prototype_fetch_exits_3(tmp_path: Path) -> None:
    class Empty:
        def search_subsystem(self, *_args, **_kwargs):
            return []

    output = tmp_path / "partial"
    result = fetch_prototypes(
        "Ti-Al-V",
        output,
        phases=["alpha", "alpha-double-prime"],
        provider=Empty(),
    )
    assert result.exit_code == 3
    assert (output / "alpha-double-prime.cif").is_file()
    assert not (output / "alpha.cif").exists()
    statuses = {record.phase: record.status for record in result.records}
    assert statuses == {"alpha": "missing", "alpha-double-prime": "scaffold"}


def test_cli_scaffold_and_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MP_API_KEY", raising=False)
    output = tmp_path / "cli-prototypes"
    assert (
        main(
            [
                "fetch-prototypes",
                "Ti-6Al-4V",
                "-o",
                str(output),
                "--phase",
                "alpha-double-prime",
            ]
        )
        == 0
    )
    assert b"1523304" in (output / "alpha-double-prime.cif").read_bytes()

    missing_key = tmp_path / "needs-key"
    assert (
        main(["fetch-prototypes", "Ti-6Al-4V", "-o", str(missing_key), "--phase", "alpha"])
        == 2
    )
    assert not missing_key.exists()

    destination = tmp_path / "cli-adapt.cif"
    assert (
        main(
            [
                "adapt",
                str(HCP),
                "-o",
                str(destination),
                "--nominal",
                "tc4",
                "--a",
                "2.935",
                "--b",
                "2.935",
                "--c",
                "4.673",
            ]
        )
        == 2
    )
    assert not destination.exists()
