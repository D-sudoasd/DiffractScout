from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from diffractscout.demo import write_demo_inputs
from diffractscout.models import CandidateRecord, DiscoverySettings, DownloadArtifact
from diffractscout.pipeline import run_pipeline
from diffractscout.validation import verify_bundle


class OfflineProvider:
    name = "offline-fixture"

    def search_subsystem(self, chemsys: str, **_kwargs: object) -> list[CandidateRecord]:
        return [
            CandidateRecord(
                material_id="fixture-1",
                formula="Al",
                energy_above_hull_eV_atom=0.0,
                is_stable=True,
                space_group="F m -3 m",
                space_group_number=225,
                queried_chemsys=chemsys,
                source_provider=self.name,
                source_url="https://example.invalid/fixture-1",
            )
        ]

    def metadata(self) -> dict[str, object]:
        return {"provider": self.name, "database_version": "offline"}

    def download_candidates(
        self,
        candidates: object,
        output_dir: Path,
        **_kwargs: object,
    ) -> list[DownloadArtifact]:
        fixture_dir = write_demo_inputs(output_dir / "_fixture")
        cif = output_dir / "fixture-1.cif"
        elastic = output_dir / "fixture-1_elasticity.json"
        shutil.copy2(fixture_dir / "synthetic_fcc_al.cif", cif)
        shutil.copy2(fixture_dir / "synthetic_fcc_al_elasticity.json", elastic)
        shutil.rmtree(fixture_dir)
        candidate = list(candidates)[0]
        return [
            DownloadArtifact(
                candidate=candidate,
                cif_path=cif,
                elasticity_path=elastic,
                status="ok",
                provider_metadata=self.metadata(),
            )
        ]


def test_discovery_to_diffraction_bundle_without_network(tmp_path: Path) -> None:
    output = tmp_path / "complete"
    result = run_pipeline(
        "Al",
        OfflineProvider(),
        output,
        discovery_settings=DiscoverySettings(mode="single_chemsys", max_total=1),
        confirm_above=5,
    )
    assert len(result.discovery.candidates) == 1
    assert len(result.downloads) == 1
    assert len(result.analyses) == 1
    assert result.analyses[0].reflections[0].hkl == (1, 1, 1)
    assert verify_bundle(output)["ok"]


def test_primitive_download_rejects_automatic_elastic_pairing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Primitive-cell downloads"):
        run_pipeline(
            "Al",
            OfflineProvider(),
            tmp_path / "primitive",
            conventional_unit_cell=False,
            include_elasticity=True,
        )
    assert not (tmp_path / "primitive").exists()
