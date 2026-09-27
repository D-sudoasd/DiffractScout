#!/usr/bin/env python3
"""PhaseScout CLI: alloy / chemsys / MP-ID → possible-phase CIF batch.

Examples:
  python scripts/fetch_possible_phases.py "Ti-6Al-4V" --dry-run
  python scripts/fetch_possible_phases.py "Ti-Al-V-Cu" --mode possible_phases
  python scripts/fetch_possible_phases.py "Ti6Al4V" --mode near_stable --e-hull-max 0.05
  python scripts/fetch_possible_phases.py --mpids mp-23,mp-149 --label selected
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path
from ...console import configure_cli_output

from ..paths import user_data_dir

ROOT = user_data_dir()

from .composition_parse import (  # noqa: E402
    ParsedComposition,
    applies_to_for_elements,
    chemsys_subsystems,
    parse_composition_text,
)
from .elasticity_web import ElasticityWebTarget, run_web_fallback  # noqa: E402
from .mp_client import (  # noqa: E402
    CifNameMeta,
    MaterialsProjectService,
    PhaseCandidate,
    parse_mpids,
    sanitize_filename_part,
)
from .structure_type import infer_structure_type_detailed  # noqa: E402


def load_api_key(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env = os.environ.get("MP_API_KEY", "").strip()
    if env:
        return env
    settings = ROOT / "config" / "settings.json"
    if settings.is_file():
        data = json.loads(settings.read_text(encoding="utf-8-sig"))
        key = str(data.get("api_key", "") or "").strip()
        if key:
            return key
    raise SystemExit(
        "No API key. Set MP_API_KEY, pass --api-key, or save key in config/settings.json"
    )


def next_slot_dir(downloads_root: Path, label: str) -> Path:
    downloads_root.mkdir(parents=True, exist_ok=True)
    max_n = 0
    for child in downloads_root.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if len(name) >= 3 and name[:2].isdigit() and name[2] == "_":
            max_n = max(max_n, int(name[:2]))
    n = max_n + 1
    safe = sanitize_filename_part(label, "batch")
    path = downloads_root / f"{n:02d}_{safe}"
    if path.exists():
        raise SystemExit(f"Output directory already exists: {path}")
    return path


def formula_elements(formula: str) -> set[str]:
    try:
        from pymatgen.core import Composition

        return {str(e) for e in Composition(formula).elements}
    except Exception:
        import re

        return set(re.findall(r"[A-Z][a-z]?", formula or ""))


def collect_candidates(
    service: MaterialsProjectService,
    parsed: ParsedComposition,
    *,
    mode: str,
    e_hull_max: float | None,
    max_per_subsystem: int | None,
    exclude_deprecated: bool,
) -> tuple[list[PhaseCandidate], dict[str, int], list[str]]:
    """Return unique candidates, per-subsystem counts, subsystem list."""
    by_id: dict[str, PhaseCandidate] = {}
    subsystem_counts: Counter[str] = Counter()
    subsystems: list[str] = []

    if mode == "mpids_only" or (parsed.mpids and not parsed.elements and mode != "possible_phases"):
        # Direct ID path: fetch summary one chemsys-less via get is not in service;
        # create stub candidates; download will validate.
        for mpid in parsed.mpids:
            by_id[mpid] = PhaseCandidate(
                material_id=mpid,
                formula="",
                energy_above_hull=None,
                is_stable=None,
                theoretical=None,
                space_group="",
                space_group_number=None,
                crystal_system="",
                queried_chemsys="mpid",
            )
        return list(by_id.values()), dict(subsystem_counts), ["mpid"]

    if not parsed.elements:
        raise SystemExit("No elements parsed; cannot expand subsystems.")

    if mode == "possible_phases":
        subsystems = chemsys_subsystems(parsed.elements)
        hull = None
    elif mode == "near_stable":
        subsystems = [parsed.chemsys]  # full system only; still expand optional?
        # For near_stable on alloys, still scan subsystems but filter hull
        subsystems = chemsys_subsystems(parsed.elements)
        hull = e_hull_max if e_hull_max is not None else 0.05
    elif mode == "single_chemsys":
        subsystems = [parsed.chemsys]
        hull = e_hull_max
    else:
        raise SystemExit(f"Unknown mode: {mode}")

    for chemsys in subsystems:
        try:
            found = service.search_chemsys_phases(
                chemsys,
                max_results=max_per_subsystem,
                exclude_deprecated=exclude_deprecated,
                e_hull_max=hull,
            )
        except Exception as exc:  # keep batch going
            print(f"[warn] search failed for {chemsys}: {exc}", file=sys.stderr)
            found = []
        subsystem_counts[chemsys] = len(found)
        for cand in found:
            mid = cand.material_id.lower()
            if mid not in by_id:
                by_id[mid] = cand
            # keep lowest e_hull record if duplicate from another subsystem
            else:
                old = by_id[mid]
                if (
                    cand.energy_above_hull is not None
                    and (
                        old.energy_above_hull is None
                        or cand.energy_above_hull < old.energy_above_hull
                    )
                ):
                    by_id[mid] = cand

    # Also allow explicit MPIDs to be unioned
    for mpid in parsed.mpids:
        if mpid not in by_id:
            by_id[mpid] = PhaseCandidate(
                material_id=mpid,
                formula="",
                energy_above_hull=None,
                is_stable=None,
                theoretical=None,
                space_group="",
                space_group_number=None,
                crystal_system="",
                queried_chemsys="mpid",
            )

    # Sort by e_hull then id
    def sort_key(c: PhaseCandidate):
        eh = c.energy_above_hull if c.energy_above_hull is not None else 1e9
        return (eh, c.material_id)

    ordered = sorted(by_id.values(), key=sort_key)
    return ordered, dict(subsystem_counts), subsystems


def write_query_summary(
    path: Path,
    *,
    title: str,
    mode: str,
    parsed: ParsedComposition,
    subsystems: list[str],
    subsystem_counts: dict[str, int],
    unique_n: int,
    ok_n: int,
    fail_n: int,
    conventional: bool,
    e_hull_max: float | None,
) -> None:
    lines = [
        title,
        f"Mode: {mode}",
        f"Input: {parsed.raw}",
        f"Elements: {'-'.join(parsed.elements) if parsed.elements else '(mpids only)'}",
        "Definition: non-deprecated MP entries in subsystems; "
        + (
            "no energy_above_hull filtering."
            if e_hull_max is None and mode == "possible_phases"
            else f"energy_above_hull <= {e_hull_max}."
        ),
        f"CIF export: final=True, conventional_unit_cell={conventional}.",
        "",
    ]
    for sys_name in subsystems:
        lines.append(f"{sys_name}: {subsystem_counts.get(sys_name, 0)}")
    lines.extend(
        [
            "",
            f"Unique candidates: {unique_n}",
            f"Successful CIF downloads: {ok_n}",
            f"Failed CIF downloads: {fail_n}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_phase_index(
    path: Path,
    rows: list[dict[str, object]],
) -> None:
    fieldnames = [
        "material_id",
        "formula",
        "structure_type",
        "structure_type_rule",
        "queried_chemsys",
        "applies_to",
        "space_group",
        "space_group_number",
        "energy_above_hull",
        "is_stable",
        "theoretical",
        "cif_filename",
        "download_status",
        "download_error",
        "elasticity_status",
        "elasticity_source",
        "elasticity_nature",
        "elasticity_json",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_alloy_label_map(parsed: ParsedComposition, extra_labels: list[str]) -> dict[str, set[str]]:
    """Map applies_to labels to element sets (subset rule)."""
    els = set(parsed.elements)
    labels = list(parsed.labels) + list(extra_labels)
    if not labels and parsed.elements:
        labels = ["".join(parsed.elements)]
    out: dict[str, set[str]] = {}
    for lab in labels:
        safe = sanitize_filename_part(lab, "alloy")
        out[safe] = set(els)
    # If user gave multiple alloys in applies-to with same full element set, OK
    return out


def main(argv: list[str] | None = None) -> int:
    configure_cli_output()
    parser = argparse.ArgumentParser(
        description="PhaseScout: fetch Materials Project possible-phase CIFs from alloy/composition text."
    )
    parser.add_argument(
        "composition",
        nargs="?",
        default="",
        help='Free text: "Ti-6Al-4V", "Ti-Al-V-Cu", "Ti 90 Al 6 V 4 wt%%", or empty if --mpids',
    )
    parser.add_argument(
        "--mpids",
        default="",
        help="Comma/space separated MP-IDs (optional union or standalone)",
    )
    parser.add_argument(
        "--mode",
        choices=("possible_phases", "near_stable", "single_chemsys", "mpids_only"),
        default="possible_phases",
        help="Search strategy (default: possible_phases = all subsystems, no E_hull cut)",
    )
    parser.add_argument(
        "--e-hull-max",
        type=float,
        default=None,
        help="Max energy_above_hull (eV/atom). Default 0.05 for near_stable.",
    )
    parser.add_argument(
        "--max-per-subsystem",
        type=int,
        default=None,
        help="Cap results per subsystem search (default: unlimited API pages as returned)",
    )
    parser.add_argument(
        "--max-total",
        type=int,
        default=None,
        help="Cap total unique materials after merge (safety)",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=ROOT / "downloads",
        help="Parent directory for numbered batch folders (default: ./downloads)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Exact output directory (skip auto 0N_ slot naming)",
    )
    parser.add_argument("--label", default="", help="Batch folder label suffix")
    parser.add_argument(
        "--applies-to",
        default="",
        help="Semicolon/comma labels for applies_to column (default: parsed labels)",
    )
    parser.add_argument("--api-key", default="", help="Materials Project API key")
    parser.add_argument(
        "--no-conventional",
        action="store_true",
        help="Export primitive/final cell without conventional_unit_cell",
    )
    parser.add_argument(
        "--elasticity",
        action="store_true",
        help="Also export MP elasticity JSON/CSV for successful CIFs",
    )
    parser.add_argument(
        "--no-elasticity-web",
        action="store_true",
        help="With --elasticity: do not run internet/literature fallback for MP misses",
    )
    parser.add_argument(
        "--elasticity-web-offline",
        action="store_true",
        help="With --elasticity: write web search pack only (no live OpenAlex calls)",
    )
    parser.add_argument(
        "--include-deprecated",
        action="store_true",
        help="Do not filter deprecated MP entries",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and write phase_index/query_summary only; no CIF download",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Do not prompt when candidate count is large",
    )
    parser.add_argument(
        "--confirm-above",
        type=int,
        default=200,
        help="Require --yes if unique candidates exceed this (default 200)",
    )
    args = parser.parse_args(argv)

    text_parts = []
    if args.composition.strip():
        text_parts.append(args.composition.strip())
    if args.mpids.strip():
        text_parts.append(args.mpids.strip())
    if not text_parts:
        parser.error("Provide composition text and/or --mpids")

    combined = "\n".join(text_parts)
    if args.mode == "mpids_only" or (args.mpids and not args.composition.strip() and args.mode == "possible_phases"):
        valid, invalid = parse_mpids(args.mpids or args.composition)
        if invalid and not valid:
            raise SystemExit(f"Invalid MP-IDs: {invalid}")
        if args.mode == "mpids_only" or not args.composition.strip():
            parsed = ParsedComposition(
                elements=(),
                labels=(sanitize_filename_part(args.label, "mpids"),) if args.label else ("mpids",),
                mpids=tuple(valid),
                notes=("mpids_only",),
                raw=combined,
            )
            mode = "mpids_only"
        else:
            parsed = parse_composition_text(combined)
            mode = args.mode
    else:
        parsed = parse_composition_text(combined)
        mode = args.mode
        if args.mpids.strip():
            valid, _invalid = parse_mpids(args.mpids)
            # merge into parsed via new instance
            mpids = list(parsed.mpids)
            for m in valid:
                if m not in mpids:
                    mpids.append(m)
            parsed = ParsedComposition(
                elements=parsed.elements,
                labels=parsed.labels,
                mpids=tuple(mpids),
                notes=parsed.notes,
                raw=parsed.raw,
            )

    label = args.label.strip() or parsed.default_label
    extra_applies = [
        sanitize_filename_part(x.strip(), "")
        for x in re_split_labels(args.applies_to)
        if x.strip()
    ]
    alloy_map = build_alloy_label_map(parsed, extra_applies)

    print(f"Parsed elements: {parsed.elements or '(none)'}")
    print(f"Parsed labels:   {parsed.labels}")
    print(f"Parsed MPIDs:    {parsed.mpids}")
    print(f"Mode:            {mode}")
    print(f"Label:           {label}")

    api_key = load_api_key(args.api_key or None)
    service = MaterialsProjectService(api_key)

    e_hull = args.e_hull_max
    if mode == "near_stable" and e_hull is None:
        e_hull = 0.05

    candidates, subsystem_counts, subsystems = collect_candidates(
        service,
        parsed,
        mode=mode,
        e_hull_max=e_hull,
        max_per_subsystem=args.max_per_subsystem,
        exclude_deprecated=not args.include_deprecated,
    )

    if args.max_total is not None and len(candidates) > args.max_total:
        print(
            f"[info] truncating {len(candidates)} → {args.max_total} by energy_above_hull",
            file=sys.stderr,
        )
        candidates = candidates[: args.max_total]

    unique_n = len(candidates)
    print(f"Unique candidates: {unique_n}")
    for sys_name in subsystems:
        print(f"  {sys_name}: {subsystem_counts.get(sys_name, 0)}")

    if unique_n == 0:
        raise SystemExit("No candidates found.")

    if unique_n > args.confirm_above and not args.yes and not args.dry_run:
        raise SystemExit(
            f"Refusing to download {unique_n} CIFs (>{args.confirm_above}). "
            "Re-run with --yes, raise --confirm-above, or use --dry-run / --max-total."
        )

    out_dir = args.out_dir
    if out_dir is None:
        out_dir = next_slot_dir(args.out_root, label)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output: {out_dir}")

    conventional = not args.no_conventional
    rows: list[dict[str, object]] = []
    ok_n = 0
    fail_n = 0

    if args.dry_run:
        for cand in candidates:
            applies = applies_to_for_elements(formula_elements(cand.formula), alloy_map)
            if not applies and alloy_map:
                applies = ";".join(alloy_map.keys())
            st = infer_structure_type_detailed(
                cand.formula, cand.space_group, cand.space_group_number
            )
            rows.append(
                {
                    "material_id": cand.material_id,
                    "formula": cand.formula,
                    "structure_type": st.type,
                    "structure_type_rule": st.rule,
                    "queried_chemsys": cand.queried_chemsys,
                    "applies_to": applies,
                    "space_group": cand.space_group,
                    "space_group_number": cand.space_group_number
                    if cand.space_group_number is not None
                    else "",
                    "energy_above_hull": cand.energy_above_hull
                    if cand.energy_above_hull is not None
                    else "",
                    "is_stable": cand.is_stable if cand.is_stable is not None else "",
                    "theoretical": cand.theoretical if cand.theoretical is not None else "",
                    "cif_filename": "",
                    "download_status": "dry_run",
                    "download_error": "",
                    "elasticity_status": "",
                    "elasticity_source": "",
                    "elasticity_nature": "",
                    "elasticity_json": "",
                }
            )
        write_phase_index(out_dir / "phase_index.csv", rows)
        write_query_summary(
            out_dir / "query_summary.txt",
            title=f"Materials Project possible phases for {label} (DRY RUN)",
            mode=mode,
            parsed=parsed,
            subsystems=subsystems,
            subsystem_counts=subsystem_counts,
            unique_n=unique_n,
            ok_n=0,
            fail_n=0,
            conventional=conventional,
            e_hull_max=e_hull,
        )
        # machine-readable parse sidecar for agents
        (out_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "dry_run": True,
                    "mode": mode,
                    "label": label,
                    "elements": list(parsed.elements),
                    "mpids": list(parsed.mpids),
                    "unique_candidates": unique_n,
                    "subsystem_counts": subsystem_counts,
                    "out_dir": str(out_dir),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Dry-run OK → {out_dir / 'phase_index.csv'}")
        return 0

    # Download (scheme B filenames: mp-id + formula + SG + e_hull [+ stable])
    name_meta = {
        c.material_id.lower(): CifNameMeta.from_phase_candidate(c) for c in candidates
    }
    download_results = service.download_cifs(
        [c.material_id for c in candidates],
        out_dir,
        conventional_unit_cell=conventional,
        include_elasticity=args.elasticity,
        name_meta=name_meta,
    )
    result_by_id = {r.material_id.lower(): r for r in download_results}
    cand_by_id = {c.material_id.lower(): c for c in candidates}

    web_targets: list[ElasticityWebTarget] = []
    for mpid, cand in cand_by_id.items():
        res = result_by_id.get(mpid)
        applies = applies_to_for_elements(formula_elements(cand.formula), alloy_map)
        if not applies and alloy_map:
            applies = ";".join(alloy_map.keys())
        el_status, el_source, el_nature, el_json = "", "", "", ""
        if res is None:
            fail_n += 1
            status, err, cif_name = "missing_result", "No download result", ""
        elif res.ok and res.path is not None:
            ok_n += 1
            status, err, cif_name = "ok", "", res.path.name
            # Prefer structure formula from download when API summary formula was empty.
            if not cand.formula and res.formula:
                cand = PhaseCandidate(
                    material_id=cand.material_id,
                    formula=res.formula,
                    energy_above_hull=cand.energy_above_hull,
                    is_stable=cand.is_stable,
                    theoretical=cand.theoretical,
                    space_group=cand.space_group,
                    space_group_number=cand.space_group_number,
                    crystal_system=cand.crystal_system,
                    deprecated=cand.deprecated,
                    queried_chemsys=cand.queried_chemsys,
                )
            if args.elasticity:
                el_status = res.elasticity_status or (
                    "ok" if res.elasticity_found else "no_elasticity_data"
                )
                el_source = res.elasticity_source or (
                    "materials_project" if res.elasticity_found is not None else ""
                )
                el_json = res.elasticity_path.name if res.elasticity_path else ""
                if res.elasticity_found is True:
                    el_nature = "DFT_calculated"
                elif res.elasticity_found is False:
                    el_nature = "missing"
                    web_targets.append(
                        ElasticityWebTarget(
                            material_id=mpid,
                            formula=cand.formula or res.formula,
                            space_group=cand.space_group,
                            space_group_number=cand.space_group_number,
                            cif_filename=cif_name,
                            mp_status=el_status,
                            mp_error=res.elasticity_error or "",
                        )
                    )
        else:
            fail_n += 1
            status, err, cif_name = "failed", (res.error if res else ""), ""

        st = infer_structure_type_detailed(
            cand.formula, cand.space_group, cand.space_group_number
        )
        rows.append(
            {
                "material_id": mpid,
                "formula": cand.formula,
                "structure_type": st.type,
                "structure_type_rule": st.rule,
                "queried_chemsys": cand.queried_chemsys,
                "applies_to": applies,
                "space_group": cand.space_group,
                "space_group_number": cand.space_group_number
                if cand.space_group_number is not None
                else "",
                "energy_above_hull": cand.energy_above_hull
                if cand.energy_above_hull is not None
                else "",
                "is_stable": cand.is_stable if cand.is_stable is not None else "",
                "theoretical": cand.theoretical if cand.theoretical is not None else "",
                "cif_filename": cif_name,
                "download_status": status,
                "download_error": err,
                "elasticity_status": el_status,
                "elasticity_source": el_source,
                "elasticity_nature": el_nature,
                "elasticity_json": el_json,
            }
        )

    web_summary: dict[str, object] = {}
    if args.elasticity and web_targets and not args.no_elasticity_web:
        live = not args.elasticity_web_offline
        print(
            f"MP Cij missing for {len(web_targets)} phase(s); "
            f"running internet/literature fallback"
            f"{' (offline pack only)' if not live else ''}…"
        )
        web_summary = run_web_fallback(
            out_dir,
            web_targets,
            live_search=live,
        )
        # Mark rows that received web hints (still no verified numerical Cij).
        missing_ids = {t.material_id.lower() for t in web_targets}
        for row in rows:
            mid = str(row.get("material_id", "")).lower()
            if mid in missing_ids and row.get("elasticity_status") not in ("ok",):
                row["elasticity_status"] = "web_hints"
                row["elasticity_source"] = "web_literature"
                row["elasticity_nature"] = "literature_hint_only"
                # Keep elasticity_json pointing at MP sidecar (documents the miss).

    write_phase_index(out_dir / "phase_index.csv", rows)
    write_query_summary(
        out_dir / "query_summary.txt",
        title=f"Materials Project possible phases for {label}",
        mode=mode,
        parsed=parsed,
        subsystems=subsystems,
        subsystem_counts=subsystem_counts,
        unique_n=unique_n,
        ok_n=ok_n,
        fail_n=fail_n,
        conventional=conventional,
        e_hull_max=e_hull,
    )
    (out_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "dry_run": False,
                "mode": mode,
                "label": label,
                "elements": list(parsed.elements),
                "mpids": list(parsed.mpids),
                "unique_candidates": unique_n,
                "successful_cifs": ok_n,
                "failed_cifs": fail_n,
                "subsystem_counts": subsystem_counts,
                "out_dir": str(out_dir),
                "elasticity": bool(args.elasticity),
                "elasticity_web": bool(
                    args.elasticity and web_targets and not args.no_elasticity_web
                ),
                "elasticity_web_missing": len(web_targets) if args.elasticity else 0,
                "elasticity_web_summary": web_summary,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Done: {ok_n} ok, {fail_n} failed → {out_dir}")
    print(f"Index: {out_dir / 'phase_index.csv'}")
    if args.elasticity:
        print(f"Elasticity index: {out_dir / 'elasticity_index.csv'}")
        if web_summary.get("web_search_csv"):
            print(f"Web search pack: {web_summary['web_search_csv']}")
        if web_summary.get("web_hits_jsonl"):
            print(f"Web literature hits: {web_summary['web_hits_jsonl']}")
    return 0 if fail_n == 0 else 2


def re_split_labels(text: str) -> list[str]:
    import re

    if not text.strip():
        return []
    return re.split(r"[,;，；]+", text.strip())


if __name__ == "__main__":
    raise SystemExit(main())
