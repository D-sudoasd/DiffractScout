"""Candidate-phase discovery and deterministic ranking."""

from __future__ import annotations

from dataclasses import replace

from .composition import chemsys_subsystems
from .models import CandidateRecord, DiscoveryResult, DiscoverySettings, ParsedComposition
from .providers.base import PhaseProvider


def _sort_key(candidate: CandidateRecord) -> tuple[float, int, str]:
    energy = (
        candidate.energy_above_hull_eV_atom
        if candidate.energy_above_hull_eV_atom is not None
        else float("inf")
    )
    stable_priority = 0 if candidate.is_stable is True else 1
    return energy, stable_priority, candidate.material_id


def search_candidates(
    provider: PhaseProvider,
    parsed: ParsedComposition,
    settings: DiscoverySettings,
) -> DiscoveryResult:
    warnings: list[str] = []
    subsystem_counts: dict[str, int] = {}

    resolver = getattr(provider, "search_material_ids", None)

    def resolve_explicit_ids() -> dict[str, CandidateRecord]:
        resolved: dict[str, CandidateRecord] = {}
        if callable(resolver) and parsed.material_ids:
            try:
                resolved = {
                    item.material_id.lower(): item
                    for item in resolver(parsed.material_ids)
                    if item.material_id
                }
            except Exception as exc:
                warnings.append(f"Provider lookup failed for explicit material IDs: {exc}")
        for material_id in parsed.material_ids:
            resolved.setdefault(
                material_id,
                CandidateRecord(
                    material_id=material_id,
                    queried_chemsys="explicit_material_id",
                    source_provider=provider.name,
                    source_url=f"https://materialsproject.org/materials/{material_id}",
                ),
            )
        return resolved

    if settings.mode == "mpids_only" or (
        parsed.material_ids and not parsed.elements and settings.mode == "possible_phases"
    ):
        subsystems = ["material_ids"]
        by_id = resolve_explicit_ids()
        subsystem_counts["material_ids"] = len(by_id)
    else:
        if not parsed.elements:
            raise ValueError("Element-based discovery requires at least one parsed element.")
        if settings.mode == "single_chemsys":
            subsystems = [parsed.chemsys]
        else:
            subsystems = chemsys_subsystems(
                parsed.elements,
                max_order=settings.max_subsystem_order,
            )

        e_hull_max = settings.e_hull_max_eV_atom
        if settings.mode == "near_stable" and e_hull_max is None:
            e_hull_max = 0.05
        if settings.mode == "possible_phases" and settings.e_hull_max_eV_atom is None:
            e_hull_max = None

        by_id: dict[str, CandidateRecord] = {}
        for subsystem in subsystems:
            try:
                found = provider.search_subsystem(
                    subsystem,
                    max_results=settings.max_per_subsystem,
                    e_hull_max_eV_atom=e_hull_max,
                    exclude_deprecated=settings.exclude_deprecated,
                )
            except Exception as exc:
                warnings.append(f"Provider query failed for {subsystem}: {exc}")
                found = []
            subsystem_counts[subsystem] = len(found)
            for candidate in found:
                material_id = candidate.material_id.lower()
                if not material_id:
                    continue
                previous = by_id.get(material_id)
                if previous is None:
                    by_id[material_id] = candidate
                    continue
                query_paths = sorted(
                    set(filter(None, previous.queried_chemsys.split(";")))
                    | set(filter(None, candidate.queried_chemsys.split(";")))
                )
                preferred = min((previous, candidate), key=_sort_key)
                by_id[material_id] = replace(preferred, queried_chemsys=";".join(query_paths))

        for material_id, explicit in resolve_explicit_ids().items():
            previous = by_id.get(material_id)
            if previous is None:
                by_id[material_id] = explicit
                continue
            query_paths = sorted(
                set(filter(None, previous.queried_chemsys.split(";")))
                | {"explicit_material_id"}
            )
            # The explicit-ID summary is preferred because it is queried for the exact record.
            by_id[material_id] = replace(explicit, queried_chemsys=";".join(query_paths))

    candidates = sorted(by_id.values(), key=_sort_key)
    if settings.max_total is not None and len(candidates) > settings.max_total:
        warnings.append(
            f"Candidate list was truncated from {len(candidates)} to {settings.max_total} "
            "using energy-above-hull, stability, and material-ID ordering."
        )
        candidates = candidates[: settings.max_total]

    return DiscoveryResult(
        parsed=parsed,
        settings=settings,
        candidates=candidates,
        subsystems=subsystems,
        subsystem_counts=subsystem_counts,
        provider_metadata=provider.metadata(),
        warnings=warnings,
    )
