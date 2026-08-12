from pathlib import Path

import pytest

from diffractscout.composition import parse_composition_text
from diffractscout.models import CandidateRecord, DiscoverySettings
from diffractscout.selection import search_candidates


class FakeProvider:
    name = "fake"

    def search_subsystem(self, chemsys: str, **_kwargs: object) -> list[CandidateRecord]:
        common = CandidateRecord(
            material_id="mp-1",
            formula="AB",
            energy_above_hull_eV_atom=0.02 if chemsys.count("-") else 0.03,
            queried_chemsys=chemsys,
            source_provider=self.name,
        )
        unique = CandidateRecord(
            material_id=f"mp-{100 + len(chemsys)}",
            formula="A",
            energy_above_hull_eV_atom=0.0,
            is_stable=True,
            queried_chemsys=chemsys,
            source_provider=self.name,
        )
        return [common, unique]

    def download_candidates(self, candidates: object, output_dir: Path, **kwargs: object) -> list[object]:
        raise AssertionError("not used")

    def metadata(self) -> dict[str, object]:
        return {"provider": "fake", "database_version": "fixture"}


def test_deduplicate_and_keep_lowest_hull_record() -> None:
    parsed = parse_composition_text("Ti-Al")
    result = search_candidates(FakeProvider(), parsed, DiscoverySettings())
    common = next(item for item in result.candidates if item.material_id == "mp-1")
    assert common.energy_above_hull_eV_atom == 0.02
    assert set(common.queried_chemsys.split(";")) == {"Al", "Ti", "Al-Ti"}
    assert result.provider_metadata["database_version"] == "fixture"


def test_explicit_material_ids_use_provider_metadata() -> None:
    class IdProvider(FakeProvider):
        def search_material_ids(self, material_ids: object) -> list[CandidateRecord]:
            material_id = list(material_ids)[0]
            return [
                CandidateRecord(
                    material_id=material_id,
                    formula="Al",
                    energy_above_hull_eV_atom=0.0,
                    is_stable=True,
                    space_group="F m -3 m",
                    space_group_number=225,
                    queried_chemsys="explicit_material_id",
                    source_provider=self.name,
                )
            ]

    parsed = parse_composition_text("mp-134")
    result = search_candidates(IdProvider(), parsed, DiscoverySettings(mode="mpids_only"))
    assert len(result.candidates) == 1
    assert result.candidates[0].formula == "Al"
    assert result.candidates[0].space_group_number == 225
    assert result.subsystem_counts == {"material_ids": 1}


def test_invalid_discovery_limits_fail_before_provider_access() -> None:
    parsed = parse_composition_text("Ti-Al")
    try:
        search_candidates(FakeProvider(), parsed, DiscoverySettings(max_total=0))
    except ValueError as exc:
        assert "max_total" in str(exc)
    else:
        raise AssertionError("Expected invalid max_total to be rejected")


def test_subsystem_expansion_limit_fails_before_provider_access() -> None:
    parsed = parse_composition_text("Ti-Al-V-Cu")
    with pytest.raises(ValueError, match="above max_subsystems=10"):
        search_candidates(
            FakeProvider(),
            parsed,
            DiscoverySettings(max_subsystems=10),
        )
