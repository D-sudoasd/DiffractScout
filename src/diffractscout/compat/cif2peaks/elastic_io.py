"""Load elastic constants from PhaseScout (or compatible) sidecars next to CIFs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .elastic import DEFAULT_ELASTIC_COORDINATE_FRAME, ElasticConstants

# PhaseScout MP IEEE tensors paired with conventional-cell CIFs.
PHASESCOUT_IEEE_COORDINATE_FRAME = "materials_project_ieee_conventional"
PHASESCOUT_SCHEMA = "phasescout_elasticity_v1"


def _as_6x6(matrix: object) -> list[list[float]] | None:
    if matrix is None:
        return None
    try:
        rows = list(matrix)  # type: ignore[arg-type]
    except TypeError:
        return None
    if len(rows) < 6:
        return None
    out: list[list[float]] = []
    for row_index in range(6):
        try:
            row = list(rows[row_index])  # type: ignore[arg-type]
        except TypeError:
            return None
        if len(row) < 6:
            return None
        try:
            out.append([float(row[c]) for c in range(6)])
        except (TypeError, ValueError):
            return None
    return out


def _matrix_from_phasescout_payload(payload: dict[str, Any]) -> tuple[list[list[float]] | None, str, list[str]]:
    """Return (matrix, basis_label, warnings)."""

    warnings: list[str] = []
    # Preferred: explicit cif2peaks / stiffness block
    for key in ("stiffness_GPa", "cij_GPa"):
        matrix = _as_6x6(payload.get(key))
        if matrix is not None:
            return matrix, key, warnings

    cif2peaks = payload.get("cif2peaks")
    if isinstance(cif2peaks, dict):
        matrix = _as_6x6(cif2peaks.get("stiffness_GPa"))
        if matrix is not None:
            return matrix, "cif2peaks.stiffness_GPa", warnings

    tensor = payload.get("elastic_tensor")
    if isinstance(tensor, dict):
        ieee = _as_6x6(tensor.get("ieee_format"))
        if ieee is not None:
            return ieee, "ieee_format", warnings
        raw = _as_6x6(tensor.get("raw"))
        if raw is not None:
            warnings.append(
                "Using elastic_tensor.raw because ieee_format is missing; "
                "verify orientation vs CIF lattice."
            )
            return raw, "raw", warnings

    # Flat C11_GPa ... from index-style documents
    if any(f"C{i}{j}_GPa" in payload for i in range(1, 7) for j in range(1, 7)):
        matrix = []
        try:
            for i in range(1, 7):
                matrix.append([float(payload.get(f"C{i}{j}_GPa", "")) for j in range(1, 7)])
            return matrix, "flat_Cij_GPa", warnings
        except (TypeError, ValueError):
            return None, "", warnings

    return None, "", warnings


def _source_from_payload(payload: dict[str, Any], *, basis: str) -> str:
    parts: list[str] = ["PhaseScout"]
    prov = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    provider = str(prov.get("provider") or payload.get("source") or "Materials Project")
    parts.append(str(provider))
    mid = str(payload.get("material_id") or prov.get("material_id") or "").strip()
    if mid:
        parts.append(mid)
    nature = str(prov.get("nature_of_data") or "")
    if nature:
        parts.append(nature)
    elif payload.get("status") == "ok":
        parts.append("DFT_calculated")
    url = str(prov.get("methodology_url") or "").strip()
    if url:
        parts.append(url)
    parts.append(f"basis={basis}")
    return " | ".join(parts)


def _coordinate_frame_from_payload(payload: dict[str, Any], basis: str) -> str:
    cif2peaks = payload.get("cif2peaks")
    if isinstance(cif2peaks, dict):
        frame = str(cif2peaks.get("coordinate_frame") or "").strip()
        if frame:
            return frame
    prov = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    frame = str(prov.get("coordinate_frame") or "").strip()
    if frame:
        return frame
    if basis in {"ieee_format", "cif2peaks.stiffness_GPa", "stiffness_GPa"}:
        return PHASESCOUT_IEEE_COORDINATE_FRAME
    return DEFAULT_ELASTIC_COORDINATE_FRAME


def elastic_constants_from_phasescout_dict(payload: dict[str, Any]) -> ElasticConstants | None:
    """Build ElasticConstants from a PhaseScout elasticity JSON object."""

    status = str(payload.get("status") or "").strip().lower()
    if status and status not in {"ok", "valid"}:
        return None

    prov = payload.get("provenance")
    if isinstance(prov, dict) and prov.get("numerical_cij") is False:
        return None

    matrix, basis, extra_warnings = _matrix_from_phasescout_payload(payload)
    if matrix is None:
        return None

    elastic = ElasticConstants.from_matrix(
        matrix,
        source=_source_from_payload(payload, basis=basis),
        unit="GPa",
        coordinate_frame=_coordinate_frame_from_payload(payload, basis),
    )
    if extra_warnings:
        elastic.warnings = [*extra_warnings, *elastic.warnings]
        if elastic.status == "valid" and elastic.warnings:
            elastic.status = "valid_with_warnings"
    # Always note non-experimental DFT provenance when from PhaseScout/MP
    note = "Cij from PhaseScout/Materials Project DFT export; not experimental handbook values."
    if note not in elastic.warnings:
        elastic.warnings = [*elastic.warnings, note]
        if elastic.status == "valid":
            elastic.status = "valid_with_warnings"
    return elastic


def load_elastic_from_json_file(path: Path) -> ElasticConstants | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return elastic_constants_from_phasescout_dict(payload)


def _matrix_from_index_row(row: dict[str, str]) -> list[list[float]] | None:
    try:
        return [[float(row[f"C{i}{j}_GPa"]) for j in range(1, 7)] for i in range(1, 7)]
    except (KeyError, TypeError, ValueError):
        return None


def load_elastic_from_index_csv(index_path: Path, cif_name: str) -> ElasticConstants | None:
    if not index_path.is_file():
        return None
    try:
        with index_path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return None

    target = cif_name.strip().lower()
    for row in rows:
        names = {
            str(row.get("cif_filename", "")).strip().lower(),
            str(row.get("paired_cif", "")).strip().lower(),
        }
        if target not in names:
            continue
        status = str(row.get("status", "")).strip().lower()
        if status and status not in {"ok", "valid"}:
            continue
        numerical = str(row.get("numerical_cij", "")).strip().lower()
        if numerical in {"false", "0", "no"}:
            continue
        matrix = _matrix_from_index_row(row)
        if matrix is None:
            continue
        source_bits = [
            "PhaseScout",
            str(row.get("provider") or "Materials Project"),
            str(row.get("material_id") or ""),
            str(row.get("nature_of_data") or "DFT_calculated"),
            str(row.get("methodology_url") or ""),
        ]
        source = " | ".join(b for b in source_bits if b)
        elastic = ElasticConstants.from_matrix(
            matrix,
            source=source,
            unit="GPa",
            coordinate_frame=PHASESCOUT_IEEE_COORDINATE_FRAME,
        )
        note = "Cij from PhaseScout elasticity_index.csv; DFT, not experimental."
        elastic.warnings = [*elastic.warnings, note]
        if elastic.status == "valid":
            elastic.status = "valid_with_warnings"
        return elastic
    return None


def _mpid_from_name(name: str) -> str | None:
    import re

    match = re.search(r"(mp-\d+)", name, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower()


def _load_elastic_from_directory_scan(cif_path: Path) -> ElasticConstants | None:
    """Fallback: scan sibling *_elasticity.json by paired_cif / material_id."""

    cif_name = cif_path.name.lower()
    mpid = _mpid_from_name(cif_path.name)
    by_paired: list[Path] = []
    by_mpid: list[Path] = []

    try:
        candidates = sorted(cif_path.parent.glob("*_elasticity.json"))
    except OSError:
        return None

    for json_path in candidates:
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        paired = {
            str(payload.get("cif_filename") or "").strip().lower(),
            str(payload.get("paired_cif") or "").strip().lower(),
        }
        prov = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
        if isinstance(payload.get("cif2peaks"), dict):
            paired.add(str(payload["cif2peaks"].get("paired_cif") or "").strip().lower())
        if cif_name in paired:
            by_paired.append(json_path)
            continue
        json_mid = str(payload.get("material_id") or prov.get("material_id") or "").strip().lower()
        if mpid and json_mid == mpid:
            by_mpid.append(json_path)

    # Prefer explicit paired_cif; require unique mpid hit to avoid cross-phase mixups
    for group in (by_paired, by_mpid):
        if len(group) == 1:
            elastic = load_elastic_from_json_file(group[0])
            if elastic is not None:
                return elastic
    return None


def load_elastic_for_cif(cif_path: str | Path) -> ElasticConstants | None:
    """Discover PhaseScout sidecars beside a CIF and load numerical Cij if present.

    Lookup order:
      1. ``{cif_stem}_elasticity.json``
      2. sibling ``*_elasticity.json`` with matching ``cif_filename`` / ``paired_cif``
         (or unique ``material_id`` / ``mp-####`` in the CIF name)
      3. ``elasticity_index.csv`` in the same directory (match cif_filename)
    """

    path = Path(cif_path).expanduser().resolve()
    if path.suffix.lower() != ".cif":
        return None

    json_path = path.with_name(f"{path.stem}_elasticity.json")
    if json_path.is_file():
        elastic = load_elastic_from_json_file(json_path)
        if elastic is not None:
            return elastic

    scanned = _load_elastic_from_directory_scan(path)
    if scanned is not None:
        return scanned

    index_path = path.parent / "elasticity_index.csv"
    return load_elastic_from_index_csv(index_path, path.name)


def load_elastic_map_for_cifs(
    cif_paths: list[str | Path],
) -> dict[Path, ElasticConstants]:
    """Return path→elastic map for CIFs that have loadable sidecars."""

    out: dict[Path, ElasticConstants] = {}
    for cif in cif_paths:
        path = Path(cif).expanduser().resolve()
        elastic = load_elastic_for_cif(path)
        if elastic is not None:
            out[path] = elastic
    return out
