from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from ..models import CandidateRecord, DownloadArtifact


class PhaseProvider(Protocol):
    """Minimal provider contract used by discovery and end-to-end pipelines."""

    name: str

    def search_subsystem(
        self,
        chemsys: str,
        *,
        max_results: int | None = None,
        e_hull_max_eV_atom: float | None = None,
        exclude_deprecated: bool = True,
    ) -> list[CandidateRecord]: ...

    def download_candidates(
        self,
        candidates: Sequence[CandidateRecord],
        output_dir: Path,
        *,
        conventional_unit_cell: bool = True,
        include_elasticity: bool = True,
    ) -> list[DownloadArtifact]: ...

    def metadata(self) -> dict[str, object]: ...
