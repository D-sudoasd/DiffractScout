import json
from pathlib import Path

import pytest

from diffractscout.composition import parse_composition_text
from diffractscout.exporters import export_result_bundle
from diffractscout.models import AnalysisSettings, CandidateRecord, DiscoverySettings
from diffractscout.selection import _sort_key, search_candidates


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


def test_explicit_material_id_lookup_failure_does_not_create_placeholder() -> None:
    class FailingIdProvider(FakeProvider):
        def search_material_ids(self, _material_ids: object) -> list[CandidateRecord]:
            raise RuntimeError("lookup unavailable")

    result = search_candidates(
        FailingIdProvider(),
        parse_composition_text("mp-404"),
        DiscoverySettings(mode="mpids_only"),
    )
    assert result.candidates == []
    assert any("lookup failed" in warning for warning in result.warnings)


def test_provider_without_explicit_id_lookup_is_not_a_resolved_success() -> None:
    result = search_candidates(
        FakeProvider(),
        parse_composition_text("mp-404"),
        DiscoverySettings(mode="mpids_only"),
    )
    assert result.candidates == []
    assert any("does not support" in warning for warning in result.warnings)


def test_invalid_discovery_limits_fail_before_provider_access() -> None:
    parsed = parse_composition_text("Ti-Al")
    try:
        search_candidates(FakeProvider(), parsed, DiscoverySettings(max_total=0))
    except ValueError as exc:
        assert "max_total" in str(exc)
    else:
        raise AssertionError("Expected invalid max_total to be rejected")


def test_unknown_discovery_mode_fails_before_provider_access() -> None:
    parsed = parse_composition_text("Ti-Al")
    with pytest.raises(ValueError, match="Unknown discovery mode"):
        search_candidates(
            FakeProvider(),
            parsed,
            DiscoverySettings(mode="typo"),  # type: ignore[arg-type]
        )


def test_subsystem_expansion_limit_fails_before_provider_access() -> None:
    parsed = parse_composition_text("Ti-Al-V-Cu")
    with pytest.raises(ValueError, match="above max_subsystems=10"):
        search_candidates(
            FakeProvider(),
            parsed,
            DiscoverySettings(max_subsystems=10),
        )


def test_nonfinite_energy_is_ranked_as_infinite() -> None:
    for energy in (float("nan"), float("inf"), float("-inf")):
        key = _sort_key(
            CandidateRecord(
                material_id="mp-nonfinite",
                energy_above_hull_eV_atom=energy,
            )
        )
        assert key[0] == float("inf")


class ThresholdProvider(FakeProvider):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search_subsystem(self, chemsys: str, **kwargs: object) -> list[CandidateRecord]:
        self.calls.append(dict(kwargs))
        return super().search_subsystem(chemsys, **kwargs)


def test_near_stable_default_threshold_is_persisted_and_exported(tmp_path: Path) -> None:
    provider = ThresholdProvider()
    result = search_candidates(
        provider,
        parse_composition_text("Ti-Al"),
        DiscoverySettings(mode="near_stable"),
    )

    assert provider.calls
    assert all(call["e_hull_max_eV_atom"] == 0.05 for call in provider.calls)
    assert result.settings.e_hull_max_eV_atom == 0.05

    output = tmp_path / "bundle"
    export_result_bundle(
        output,
        analyses=[],
        settings=AnalysisSettings(),
        discovery=result,
        include_excel=False,
    )
    provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["discovery"]["settings"]["e_hull_max_eV_atom"] == 0.05


def test_explicit_near_stable_threshold_is_preserved() -> None:
    provider = ThresholdProvider()
    settings = DiscoverySettings(mode="near_stable", e_hull_max_eV_atom=0.17)
    result = search_candidates(provider, parse_composition_text("Ti-Al"), settings)

    assert provider.calls
    assert all(call["e_hull_max_eV_atom"] == 0.17 for call in provider.calls)
    assert result.settings.e_hull_max_eV_atom == 0.17
