"""Candidate-phase discovery and deterministic ranking."""

from __future__ import annotations

import math
from dataclasses import replace

from .composition import chemsys_subsystems
from .models import CandidateRecord, DiscoveryResult, DiscoverySettings, ParsedComposition
from .providers.base import PhaseProvider


def validate_discovery_settings(settings: DiscoverySettings) -> None:
    """Reject ambiguous or unsafe discovery limits before provider access."""

    valid_modes = {"possible_phases", "near_stable", "single_chemsys", "mpids_only"}
    if settings.mode not in valid_modes:
        raise ValueError(
            f"Unknown discovery mode {settings.mode!r}; choose one of: "
            + ", ".join(sorted(valid_modes))
            + "."
        )
    if settings.e_hull_max_eV_atom is not None:
        value = float(settings.e_hull_max_eV_atom)
        if not math.isfinite(value) or value < 0:
            raise ValueError("e_hull_max_eV_atom must be a finite non-negative value.")
    for name in ("max_subsystem_order", "max_subsystems", "max_per_subsystem", "max_total"):
        value = getattr(settings, name)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
            raise ValueError(f"{name} must be a positive integer when supplied.")


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
    validate_discovery_settings(settings)
    warnings: list[str] = []
    subsystem_counts: dict[str, int] = {}

    resolver = getattr(provider, "search_material_ids", None)

    def resolve_explicit_ids() -> dict[str, CandidateRecord]:
        resolved: dict[str, CandidateRecord] = {}
        if not parsed.material_ids:
            return resolved
        if not callable(resolver):
            warnings.append(
                "Provider does not support explicit material-ID lookup; no IDs were resolved."
            )
            return resolved
        try:
            requested = {material_id.lower() for material_id in parsed.material_ids}
            resolved = {
                item.material_id.lower(): item
                for item in resolver(parsed.material_ids)
                if item.material_id and item.material_id.lower() in requested
            }
        except Exception as exc:
            warnings.append(f"Provider lookup failed for explicit material IDs: {exc}")
            return {}
        missing = sorted(requested - set(resolved))
        if missing:
            warnings.append(
                "Provider lookup returned no record for explicit material ID(s): "
                + ", ".join(missing)
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
            element_count = len(set(parsed.elements))
            upper_order = (
                element_count
                if settings.max_subsystem_order is None
                else min(element_count, settings.max_subsystem_order)
            )
            estimated_subsystems = sum(
                math.comb(element_count, order)
                for order in range(1, upper_order + 1)
            )
            if estimated_subsystems > settings.max_subsystems:
                raise ValueError(
                    "Chemical-subsystem expansion would create "
                    f"{estimated_subsystems} queries, above max_subsystems="
                    f"{settings.max_subsystems}. Reduce max_subsystem_order or "
                    "explicitly raise max_subsystems after reviewing the query scope."
                )
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
            # The explicit-ID summary is preferred because it addresses the exact record.
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
