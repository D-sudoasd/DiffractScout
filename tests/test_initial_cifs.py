import csv
import json
import math
from pathlib import Path

import gemmi
import pytest

from diffractscout.cif_quality import normalize_prototype, validate_phase_model, write_clean_model
from diffractscout.cli import main
from diffractscout.initial_cifs import prepare_cifs, read_phase_parameters
from diffractscout.models import CandidateRecord, DownloadArtifact
from diffractscout.structure import load_structure
from diffractscout.utils import sha256_file
from diffractscout.validation import verify_bundle

ROOT = Path(__file__).parents[1]
PROTOTYPES = ROOT / "src" / "diffractscout" / "prototype_data"


def _payload(result):
    return json.loads((result.output_dir / "preparation.json").read_text(encoding="utf-8"))


def _p1_bcc(path: Path, *, a: float = 3.2, second_site: bool = True):
    small = gemmi.SmallStructure()
    small.cell = gemmi.UnitCell(a, a, a, 90, 90, 90)
    small.spacegroup_hm = "P 1"
    positions = [(0, 0, 0), (0.5, 0.5, 0.5)] if second_site else [(0, 0, 0)]
    for index, position in enumerate(positions):
        site = gemmi.SmallStructure.Site()
        site.element = gemmi.Element("Ti")
        site.label = f"Ti{index}"
        site.type_symbol = "Ti"
        site.fract = gemmi.Fractional(*position)
        site.occ = 1
        small.add_site(site)
    write_clean_model(small, path, details="Synthetic P1 test input.")


def test_offline_nominal_bundle_is_portable_validated_and_explicit(tmp_path):
    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError(f"Offline mode attempted provider access: {name}")

    result = prepare_cifs(
        "TC4", tmp_path / "bundle", offline=True, provider=NoNetwork(), api_key="never-use-this"
    )
    assert result.exit_code == 0
    assert verify_bundle(result.output_dir)["ok"]
    payload = _payload(result)
    assert payload["host"] == "Ti"
    assert payload["query_status"] == "offline"
    assert payload["queries"] == []
    assert payload["not_experimental_refinement"] is True
    assert len(payload["records"]) == 3
    for record in payload["records"]:
        assert record["status"] == "ready"
        assert record["lattice_basis"] == "prototype_lattice"
        assert record["composition_role"] == "bulk_starting_assumption"
        assert record["occupancies"] == {"Ti": "0.86204", "Al": "0.10195", "V": "0.03601"}
        assert any("not the measured composition" in warning for warning in record["warnings"])
        cif = result.output_dir / record["cif"]
        loaded = validate_phase_model(cif, record["phase"], host="Ti")
        assert loaded.source_metadata["symmetry_crosscheck"] == "match"
        assert record["sha256"] == sha256_file(cif)
        assert (
            sha256_file(result.output_dir / record["prototype"]["source_cif"])
            == record["prototype"]["source_sha256"]
        )
        text = cif.read_text(encoding="utf-8")
        assert "_audit_creation_method" in text
        assert "_cod_database_code" not in text
        assert "_publ_author_name" not in text
        assert "_diffrn_ambient_temperature" not in text
        sidecar = json.loads(cif.with_suffix(".adapt.json").read_text(encoding="utf-8"))
        assert sidecar["source_cif"].startswith("prototypes/")
        assert sidecar["output_sha256"] == sha256_file(cif)
    all_json = "\n".join(
        path.read_text(encoding="utf-8") for path in result.output_dir.rglob("*.json")
    )
    assert ".diffractscout-initial-" not in all_json
    assert "never-use-this" not in all_json
    assert "1173 K" in result.report_path.read_text(encoding="utf-8")


def test_cited_independent_axes_and_per_phase_chemistry(tmp_path):
    values = {
        "alpha": {
            "lattice": {"a": 2.95, "c": 4.70},
            "citation": "Synthetic test lattice, not literature",
            "conditions": "test only",
        },
        "beta": {
            "lattice": {"a": 3.22},
            "citation": "Synthetic test lattice",
            "weight_percent": "Ti=80,Al=2,V=18",
        },
        "alpha-double-prime": {
            "lattice": {"a": 3.08, "b": 4.64, "c": 4.62},
            "fract": {"y": 0.17},
            "citation": "Synthetic test lattice",
        },
    }
    result = prepare_cifs("Ti64", tmp_path / "cited", offline=True, phase_parameters=values)
    assert result.exit_code == 0
    records = {record["phase"]: record for record in _payload(result)["records"]}
    assert all(record["lattice_basis"] == "caller_cited_lattice" for record in records.values())
    assert all(record["inherited_independent_axes"] == [] for record in records.values())
    assert records["alpha"]["cell_parameters"][:3] == [2.95, 2.95, 4.7]
    assert records["beta"]["cell_parameters"][:3] == [3.22] * 3
    assert records["beta"]["composition_role"] == "caller_supplied_phase"
    assert records["beta"]["occupancies"] != records["alpha"]["occupancies"]
    assert records["alpha-double-prime"]["coordinate_edits"] == {"y": "0.17"}
    assert not any(
        "y is inherited" in warning for warning in records["alpha-double-prime"]["warnings"]
    )


def test_peak_preview_obeys_independent_bragg_and_q_relations(tmp_path):
    result = prepare_cifs("TC4", tmp_path / "bundle", offline=True, preview_wavelength_A=0.5)
    with (result.output_dir / "peak_preview.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    for row in rows:
        spacing = float(row["d_A"])
        assert float(row["q_invA"]) == pytest.approx(2 * math.pi / spacing, rel=1e-12)
        angle = math.degrees(2 * math.asin(0.5 / (2 * spacing)))
        assert float(row["two_theta_deg"]) == pytest.approx(angle, abs=1e-9)
        assert 5 - 1e-9 <= angle <= 120 + 1e-9


def test_p1_symmetry_restoration_preserves_source(tmp_path):
    source = tmp_path / "raw.cif"
    _p1_bcc(source)
    before = sha256_file(source)
    destination = tmp_path / "normalized.cif"
    audit = normalize_prototype(source, destination, "beta", host="Ti")
    assert audit["symmetry_restored_from_p1"] is True
    assert sha256_file(source) == before
    loaded = validate_phase_model(destination, "beta", host="Ti")
    assert loaded.space_group_number == 229
    assert len(loaded.small_structure.sites) == 1
    assert loaded.cell_parameters[:3] == pytest.approx((3.2, 3.2, 3.2))


def test_reject_bad_candidate_and_try_next_with_provenance(tmp_path):
    class Provider:
        def search_subsystem(self, system, **kwargs):
            assert kwargs["e_hull_max_eV_atom"] is None
            return [
                CandidateRecord("mp-bad", "Ti", 0, space_group_number=229),
                CandidateRecord("mp-good", "Ti", 0.05, space_group_number=229),
            ]

        def download_candidates(self, candidates, output, **kwargs):
            assert kwargs == {"conventional_unit_cell": True, "include_elasticity": False}
            candidate = candidates[0]
            path = output / "raw.cif"
            _p1_bcc(path, second_site=candidate.material_id != "mp-bad")
            return [DownloadArtifact(candidate, path)]

        def metadata(self):
            return {"database_version": "test-db", "api_key": "should-not-appear"}

    result = prepare_cifs("TC4", tmp_path / "mp", phases=["beta"], provider=Provider())
    assert result.exit_code == 0
    payload = _payload(result)
    record = payload["records"][0]
    assert record["prototype"]["candidate"]["material_id"] == "mp-good"
    assert record["prototype"]["symmetry_restored_from_p1"] is True
    assert record["prototype"]["selection_attempts"][0]["material_id"] == "mp-bad"
    assert "api_key" not in payload["provider_metadata"]
    assert payload["provider_metadata"]["database_version"] == "test-db"


def test_same_space_group_multiple_orbits_are_not_a_parent_prototype(tmp_path):
    small = gemmi.SmallStructure()
    small.cell = gemmi.UnitCell(3.1, 4.7, 4.6, 90, 90, 90)
    small.spacegroup_hm = "C m c m"
    for index, value in enumerate((0.20, 0.36)):
        site = gemmi.SmallStructure.Site()
        site.element = gemmi.Element("Ti")
        site.type_symbol = "Ti"
        site.label = f"Ti{index}"
        site.fract = gemmi.Fractional(0, value, 0.25)
        site.occ = 1
        small.add_site(site)
    source = tmp_path / "multiple.cif"
    write_clean_model(small, source, details="Synthetic two-orbit test")
    assert load_structure(source).space_group_number == 63
    with pytest.raises(ValueError, match="orbit"):
        validate_phase_model(source, "alpha-double-prime", host="Ti")


def test_failed_explicit_template_is_not_silently_replaced(tmp_path):
    source = tmp_path / "wrong.cif"
    _p1_bcc(source)
    before = sha256_file(source)
    result = prepare_cifs("TC4", tmp_path / "partial", offline=True, templates={"alpha": source})
    assert result.exit_code == 3
    assert result.records[0].status == "failed"
    assert result.records[0].cif_path is None
    assert not (result.output_dir / "initial" / "alpha.cif").exists()
    assert sha256_file(source) == before
    assert verify_bundle(result.output_dir)["ok"]


def test_non_ti_system_does_not_receive_a_ti_scaffold(tmp_path):
    result = prepare_cifs("Ni", tmp_path / "nickel", offline=True)
    assert result.exit_code == 2
    assert all(record.cif_path is None for record in result.records)
    assert not list((result.output_dir / "initial").glob("*.cif"))
    assert verify_bundle(result.output_dir)["ok"]


def test_host_is_dominant_atomic_fraction_not_first_input_element(tmp_path):
    result = prepare_cifs(
        "Al-Ti-V",
        tmp_path / "host",
        offline=True,
        weight_percent="Al=6,V=4,Ti=90",
        phases=["alpha"],
    )
    assert _payload(result)["host"] == "Ti"
    with pytest.raises(ValueError, match="Host"):
        prepare_cifs("TC4", tmp_path / "bad-host", offline=True, host="Ni")
    with pytest.raises(ValueError, match="Equal"):
        prepare_cifs("Ti-Nb", tmp_path / "tie", offline=True, atomic_percent="Ti=50,Nb=50")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"phase_parameters": {"alpha": {"lattice": {"a": 3.0}}}},
        {"phase_parameters": {"alpha": {"lattice": {"aa": 3.0}, "citation": "test"}}},
        {"phase_parameters": {"alpha": {"lattice": {"a": float("nan")}, "citation": "test"}}},
        {"phase_parameters": {"alpha": {"fract": {"y": True}, "citation": "test"}}},
        {"phase_parameters": {"alpha": {"unknown": "test"}}},
        {"weight_percent": "Ti=90,Al=10"},
        {"nominal": "tc4", "atomic_percent": "Ti=100"},
        {"preview_wavelength_A": 0},
    ],
)
def test_invalid_inputs_fail_before_creating_output(tmp_path, kwargs):
    destination = tmp_path / "invalid"
    with pytest.raises(ValueError):
        prepare_cifs("TC4", destination, offline=True, **kwargs)
    assert not destination.exists()


def test_plain_element_set_does_not_invent_bulk_percentages(tmp_path):
    with pytest.raises(ValueError, match="Provide"):
        prepare_cifs("Ti-Al-V", tmp_path / "unknown", offline=True)


def test_json_duplicate_keys_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema":"diffractscout_phase_parameters_v1","phases":{"alpha":{"citation":"a","citation":"b"}}}'
    )
    with pytest.raises(ValueError, match="Duplicate"):
        read_phase_parameters(path)


def test_existing_output_remains_untouched(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "sample.txt"
    sentinel.write_text("keep")
    with pytest.raises(FileExistsError):
        prepare_cifs("TC4", output, offline=True)
    assert sentinel.read_text() == "keep"
    assert list(output.iterdir()) == [sentinel]


def test_cli_prepare_and_bundle_verify(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MP_API_KEY", "never-use-this-key")
    output = tmp_path / "cli"
    assert main(["prepare-cifs", "Ti-6Al-4V", "-o", str(output), "--offline", "--json"]) == 0
    response = json.loads(capsys.readouterr().out)
    assert len(response["records"]) == 3
    assert main(["verify", str(output)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_optional_independent_cif_reader_accepts_disorder_and_formula(tmp_path):
    pymatgen_cif = pytest.importorskip("pymatgen.io.cif")
    result = prepare_cifs("TC4", tmp_path / "interop", offline=True)
    for record in result.records:
        parser = pymatgen_cif.CifParser(str(record.cif_path))
        structure = parser.parse_structures(primitive=False, on_error="raise")[0]
        fractions = structure.composition.fractional_composition.get_el_amt_dict()
        assert fractions == pytest.approx({"Ti": 0.86204, "Al": 0.10195, "V": 0.03601}, abs=1e-8)
        assert structure.volume == pytest.approx(
            load_structure(record.cif_path).small_structure.cell.volume, rel=1e-8
        )


def test_subsystem_cap_rejects_before_provider_construction(tmp_path):
    class NoQuery:
        def search_subsystem(self, *_args, **_kwargs):
            raise AssertionError("cap must be checked first")

    output = tmp_path / "cap"
    with pytest.raises(ValueError, match="max-subsystems"):
        prepare_cifs("TC4", output, provider=NoQuery(), max_subsystems=1)
    assert not output.exists()


@pytest.mark.parametrize("pass_key", [True, False])
def test_candidate_failure_credentials_are_redacted_after_fallback(tmp_path, pass_key):
    key = "secret-key-for-redaction-test"

    class Provider:
        api_key = key

        def search_subsystem(self, *_args, **_kwargs):
            return [CandidateRecord("mp-test", "Ti", space_group_number=229)]

        def download_candidates(self, *_args, **_kwargs):
            raise RuntimeError(f"request failed with api_key={key}")

    result = prepare_cifs(
        "TC4",
        tmp_path / "redacted",
        phases=["beta"],
        provider=Provider(),
        api_key=key if pass_key else None,
    )
    assert result.exit_code == 0
    for path in result.output_dir.rglob("*"):
        if path.is_file():
            assert key not in path.read_text(encoding="utf-8-sig")
    assert "[redacted]" in (result.output_dir / "preparation.json").read_text(encoding="utf-8")


def test_publication_race_preserves_external_target(tmp_path, monkeypatch):
    import diffractscout.pipeline as pipeline

    output = tmp_path / "race"
    original = pipeline._rename_directory_noreplace

    def raced(source, target):
        if target == output:
            target.mkdir()
            (target / "external.txt").write_text("keep external data")
        original(source, target)

    monkeypatch.setattr(pipeline, "_rename_directory_noreplace", raced)
    with pytest.raises(FileExistsError):
        prepare_cifs("TC4", output, offline=True)
    assert (output / "external.txt").read_text() == "keep external data"
    assert not list(tmp_path.glob(".diffractscout-initial-*"))


def test_normalization_never_overwrites_source_or_destination(tmp_path):
    source = tmp_path / "raw.cif"
    _p1_bcc(source)
    before = sha256_file(source)
    with pytest.raises(ValueError, match="source"):
        normalize_prototype(source, source, "beta")
    assert sha256_file(source) == before
    destination = tmp_path / "existing.cif"
    destination.write_text("keep")
    with pytest.raises(FileExistsError):
        normalize_prototype(source, destination, "beta")
    assert destination.read_text() == "keep"


def test_candidate_attempt_budget_is_visible_and_can_reach_later_valid_candidate(tmp_path):
    class Provider:
        def search_subsystem(self, *_args, **_kwargs):
            return [
                CandidateRecord(f"mp-{index}", "Ti", index / 100, space_group_number=229)
                for index in range(9)
            ]

        def download_candidates(self, candidates, output, **_kwargs):
            candidate = candidates[0]
            path = output / "raw.cif"
            _p1_bcc(path, second_site=candidate.material_id == "mp-8")
            return [DownloadArtifact(candidate, path)]

    capped = prepare_cifs("TC4", tmp_path / "capped", phases=["beta"], provider=Provider())
    record = _payload(capped)["records"][0]
    assert record["prototype"]["untried_candidate_count"] == 1
    assert record["prototype"]["source"].startswith("COD")
    assert any("not attempted" in warning for warning in record["warnings"])
    extended = prepare_cifs(
        "TC4", tmp_path / "extended", phases=["beta"], provider=Provider(), max_prototype_attempts=9
    )
    record = _payload(extended)["records"][0]
    assert record["prototype"]["candidate"]["material_id"] == "mp-8"
    assert record["prototype"]["untried_candidate_count"] == 0
