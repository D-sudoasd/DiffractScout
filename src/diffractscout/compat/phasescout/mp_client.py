"""Materials Project query and CIF export helpers."""

from __future__ import annotations

import re
import csv
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

try:
    from mp_api.client import MPRester
except Exception:  # pragma: no cover - used for a clear GUI error message
    MPRester = None  # type: ignore[assignment]


from .structure_type import (  # noqa: E402
    StructureTypeResult,
    infer_structure_type,
    infer_structure_type_detailed,
)

MPID_RE = re.compile(r"^mp-\d+$", re.IGNORECASE)
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.+-]+")
ELASTICITY_SOURCE = "Materials Project materials/elasticity"
ELASTICITY_METHODOLOGY_URL = (
    "https://docs.materialsproject.org/methodology/materials-methodology/elasticity"
)
ELASTICITY_DISCLAIMER = (
    "DFT elastic constants from Materials Project. Not experimental Cij. "
    "Verify phase identity, cell setting, and orientation before continuum/FEM use."
)
ELASTICITY_DISCLAIMER_SHORT = "MP DFT Cij (not experimental); check orientation vs conventional CIF"
PHASESCOUT_ELASTICITY_SCHEMA = "phasescout_elasticity_v1"
CIF2PEAKS_COORDINATE_FRAME = "materials_project_ieee_conventional"
ELASTICITY_FIELDS = [
    "material_id",
    "formula_pretty",
    "elastic_tensor",
    "bulk_modulus",
    "shear_modulus",
    "homogeneous_poisson",
    "universal_anisotropy",
    "fitting_method",
    "state",
]
CIJ_LABELS = tuple(f"C{i}{j}_GPa" for i in range(1, 7) for j in range(1, 7))


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        value = enum_value
    return str(value)


@dataclass(frozen=True)
class MaterialSummary:
    """Small, GUI-friendly subset of Materials Project summary data."""

    material_id: str
    formula: str
    energy_above_hull: float | None
    band_gap: float | None
    crystal_system: str
    spacegroup: str

    @classmethod
    def from_doc(cls, doc: object) -> "MaterialSummary":
        symmetry = getattr(doc, "symmetry", None)
        crystal_system = ""
        spacegroup = ""

        if symmetry is not None:
            crystal_system = _clean_text(getattr(symmetry, "crystal_system", ""))
            symbol = getattr(symmetry, "symbol", "") or ""
            number = getattr(symmetry, "number", "") or ""
            spacegroup = f"{symbol} ({number})" if number else str(symbol)

        return cls(
            material_id=str(getattr(doc, "material_id", "")),
            formula=str(getattr(doc, "formula_pretty", "")),
            energy_above_hull=getattr(doc, "energy_above_hull", None),
            band_gap=getattr(doc, "band_gap", None),
            crystal_system=crystal_system,
            spacegroup=spacegroup,
        )


@dataclass(frozen=True)
class PhaseCandidate:
    """Richer summary used by possible-phase batch export."""

    material_id: str
    formula: str
    energy_above_hull: float | None
    is_stable: bool | None
    theoretical: bool | None
    space_group: str
    space_group_number: int | None
    crystal_system: str
    deprecated: bool | None = None
    queried_chemsys: str = ""

    @classmethod
    def from_doc(cls, doc: object, queried_chemsys: str = "") -> "PhaseCandidate":
        symmetry = _value(doc, "symmetry")
        space_group = ""
        space_group_number: int | None = None
        crystal_system = ""
        if symmetry is not None:
            crystal_system = _clean_text(_value(symmetry, "crystal_system", ""))
            space_group = _clean_text(_value(symmetry, "symbol", "") or "")
            number = _value(symmetry, "number", None)
            try:
                space_group_number = int(number) if number is not None else None
            except (TypeError, ValueError):
                space_group_number = None

        e_hull = _value(doc, "energy_above_hull", None)
        try:
            e_hull_f = float(e_hull) if e_hull is not None else None
        except (TypeError, ValueError):
            e_hull_f = None

        return cls(
            material_id=str(_value(doc, "material_id", "") or "").lower(),
            formula=str(_value(doc, "formula_pretty", "") or ""),
            energy_above_hull=e_hull_f,
            is_stable=_value(doc, "is_stable", None),
            theoretical=_value(doc, "theoretical", None),
            space_group=space_group,
            space_group_number=space_group_number,
            crystal_system=crystal_system,
            deprecated=_value(doc, "deprecated", None),
            queried_chemsys=queried_chemsys,
        )


@dataclass(frozen=True)
class DownloadResult:
    """Result for one attempted CIF download."""

    material_id: str
    ok: bool
    path: Path | None = None
    error: str = ""
    formula: str = ""
    elasticity_found: bool | None = None
    elasticity_path: Path | None = None
    elasticity_error: str = ""
    elasticity_status: str = ""
    elasticity_source: str = ""


@dataclass(frozen=True)
class SuccessfulCif:
    """A CIF file that can be paired with Materials Project metadata."""

    material_id: str
    formula: str
    path: Path


@dataclass(frozen=True)
class ElasticityArtifact:
    """Export status for one Materials Project elasticity lookup."""

    material_id: str
    found: bool
    path: Path
    error: str = ""
    status: str = ""
    source: str = "materials_project"


def parse_mpids(text: str) -> tuple[list[str], list[str]]:
    """Parse comma/space/newline separated MP IDs and return valid/invalid lists."""

    raw_items = re.split(r"[\s,;，；]+", text.strip())
    seen: set[str] = set()
    valid: list[str] = []
    invalid: list[str] = []

    for item in raw_items:
        if not item:
            continue
        normalized = item.lower()
        if MPID_RE.match(normalized):
            if normalized not in seen:
                valid.append(normalized)
                seen.add(normalized)
        else:
            invalid.append(item)

    return valid, invalid


def sanitize_filename_part(value: str, fallback: str) -> str:
    """Return a Windows-safe filename component."""

    value = SAFE_NAME_RE.sub("_", value.strip())
    value = value.strip("._ ")
    # Collapse repeated underscores from symbol sanitizing (e.g. P6_3/mmc → P6_3_mmc).
    value = re.sub(r"_+", "_", value)
    return value or fallback


def format_ehull_token(energy_above_hull: float) -> str:
    """Filename token for E_hull (eV/atom), e.g. ehull0 / ehull0p010 / ehull1p983."""

    if abs(float(energy_above_hull)) < 5e-7:
        return "ehull0"
    text = f"{float(energy_above_hull):.3f}"
    text = text.replace("-", "m").replace(".", "p")
    return f"ehull{text}"


def parse_spacegroup_display(spacegroup: str) -> tuple[str, int | None]:
    """Parse GUI-style 'Fm-3m (225)' or bare 'Fm-3m' into symbol + number."""

    text = (spacegroup or "").strip()
    if not text:
        return "", None
    match = re.match(r"^(.*?)\s*\((\d+)\)\s*$", text)
    if match:
        symbol = match.group(1).strip()
        try:
            return symbol, int(match.group(2))
        except ValueError:
            return symbol, None
    return text, None


@dataclass(frozen=True)
class CifNameMeta:
    """Optional metadata used to build human-distinguishable CIF filenames."""

    formula: str = ""
    space_group: str = ""
    space_group_number: int | None = None
    energy_above_hull: float | None = None
    is_stable: bool | None = None
    structure_type: str = ""
    structure_type_rule: str = ""

    @classmethod
    def from_phase_candidate(cls, cand: PhaseCandidate) -> "CifNameMeta":
        st = infer_structure_type_detailed(
            cand.formula, cand.space_group, cand.space_group_number
        )
        return cls(
            formula=cand.formula,
            space_group=cand.space_group,
            space_group_number=cand.space_group_number,
            energy_above_hull=cand.energy_above_hull,
            is_stable=cand.is_stable,
            structure_type=st.type,
            structure_type_rule=st.rule,
        )

    @classmethod
    def from_material_summary(cls, summary: MaterialSummary) -> "CifNameMeta":
        symbol, number = parse_spacegroup_display(summary.spacegroup)
        st = infer_structure_type_detailed(summary.formula, symbol, number)
        return cls(
            formula=summary.formula,
            space_group=symbol,
            space_group_number=number,
            energy_above_hull=summary.energy_above_hull,
            is_stable=(
                summary.energy_above_hull is not None
                and abs(float(summary.energy_above_hull)) < 5e-7
            ),
            structure_type=st.type,
            structure_type_rule=st.rule,
        )


def build_cif_filename(
    material_id: str,
    formula: str,
    *,
    space_group: str = "",
    space_group_number: int | None = None,
    energy_above_hull: float | None = None,
    is_stable: bool | None = None,
    structure_type: str = "",
) -> str:
    """Scheme B: mp-id first, then formula / structure type / SG / e_hull / stable.

    Examples:
      mp-134_Al_FCC_sg225_Fm-3m_ehull0_stable.cif
      mp-54_Co_HCP_sg194_P6_3_mmc_ehull0p025.cif
      mp-xxxx_Ni3Al_L12_sg221_Pm-3m_ehull0_stable.cif
    """

    mpid = str(material_id).strip().lower() or "mp-unknown"
    formula_safe = sanitize_filename_part(formula, "structure")
    parts = [mpid, formula_safe]

    stype = (structure_type or "").strip()
    if not stype:
        stype = infer_structure_type(formula, space_group, space_group_number)
    stype = sanitize_filename_part(stype, "") if stype else ""
    if stype:
        parts.append(stype)

    if space_group_number is not None:
        try:
            parts.append(f"sg{int(space_group_number)}")
        except (TypeError, ValueError):
            pass

    sg_symbol = sanitize_filename_part(space_group, "") if space_group else ""
    if sg_symbol:
        parts.append(sg_symbol)

    if energy_above_hull is not None:
        try:
            parts.append(format_ehull_token(float(energy_above_hull)))
        except (TypeError, ValueError):
            pass

    if is_stable is True:
        parts.append("stable")

    return "_".join(parts) + ".cif"


def _spacegroup_from_structure(structure: object) -> tuple[str, int | None]:
    """Best-effort SG from a pymatgen Structure when API meta is missing."""

    try:
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

        sga = SpacegroupAnalyzer(structure, symprec=0.1)  # type: ignore[arg-type]
        symbol = str(sga.get_space_group_symbol() or "")
        number = sga.get_space_group_number()
        try:
            number_i = int(number) if number is not None else None
        except (TypeError, ValueError):
            number_i = None
        return symbol, number_i
    except Exception:
        return "", None


def _value(obj: object, name: str, default: Any = None) -> Any:
    """Read a field from either a dict-like document or an object model."""

    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _json_scalar(value: object) -> object:
    """Convert common API scalar wrappers into JSON-friendly values."""

    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        value = enum_value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _matrix(value: object) -> list[list[float | str | None]] | None:
    """Return a plain nested-list matrix suitable for CSV/JSON export."""

    if value is None:
        return None

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        value = tolist()

    try:
        rows = list(value)  # type: ignore[arg-type]
    except TypeError:
        return None

    matrix: list[list[float | str | None]] = []
    for row in rows:
        row_tolist = getattr(row, "tolist", None)
        if callable(row_tolist):
            row = row_tolist()
        try:
            values = list(row)  # type: ignore[arg-type]
        except TypeError:
            return None

        converted_row: list[float | str | None] = []
        for item in values:
            scalar = _json_scalar(item)
            if scalar is None or isinstance(scalar, (int, float)):
                converted_row.append(scalar)
            else:
                try:
                    converted_row.append(float(scalar))
                except (TypeError, ValueError):
                    converted_row.append(str(scalar))
        matrix.append(converted_row)

    return matrix


def _tensor_matrix(doc: object, field: str) -> list[list[float | str | None]] | None:
    tensor = _value(doc, "elastic_tensor")
    return _matrix(_value(tensor, field))


def _modulus_dict(doc: object, field: str) -> dict[str, object] | None:
    modulus = _value(doc, field)
    if modulus is None:
        return None
    return {
        "voigt": _json_scalar(_value(modulus, "voigt")),
        "reuss": _json_scalar(_value(modulus, "reuss")),
        "vrh": _json_scalar(_value(modulus, "vrh")),
    }


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    return value


def _flatten_cij(matrix: list[list[float | str | None]] | None) -> dict[str, object]:
    values = {label: "" for label in CIJ_LABELS}
    if matrix is None:
        return values

    for row_index in range(min(6, len(matrix))):
        row = matrix[row_index]
        for col_index in range(min(6, len(row))):
            values[f"C{row_index + 1}{col_index + 1}_GPa"] = _csv_value(row[col_index])
    return values


def _mp_material_url(material_id: str) -> str:
    mid = str(material_id or "").strip().lower()
    return f"https://next-gen.materialsproject.org/materials/{mid}"


def _build_elasticity_provenance(
    download: SuccessfulCif,
    *,
    status: str,
    cij_basis: str,
    fitting_method: object,
    state: object,
    numerical: bool,
) -> dict[str, object]:
    """Explicit provenance so Cij is never a black-box number."""

    base: dict[str, object] = {
        "provider": "Materials Project",
        "api": "materials/elasticity",
        "source_label": ELASTICITY_SOURCE,
        "material_id": download.material_id,
        "paired_cif": download.path.name,
        "methodology_url": ELASTICITY_METHODOLOGY_URL,
        "mp_material_url": _mp_material_url(download.material_id),
        "status": status,
        "numerical_cij": numerical,
        "not_experimental": True,
        "disclaimer": ELASTICITY_DISCLAIMER,
    }
    if numerical:
        base.update(
            {
                "nature_of_data": "DFT_calculated",
                "cij_basis": cij_basis,
                "units": "GPa",
                "orientation_note": (
                    "IEEE elastic tensor is aligned with the Materials Project "
                    "conventional standard cell; PhaseScout CIF export uses "
                    "conventional_unit_cell=True by default."
                ),
                "fitting_method": fitting_method,
                "state": state,
            }
        )
    else:
        base.update(
            {
                "nature_of_data": "none",
                "fallback": (
                    "No numerical Cij from MP. See elasticity_web_search.csv / "
                    "elasticity_web_hits.jsonl for literature hints only — "
                    "tensors are not auto-parsed from papers."
                ),
            }
        )
    return base


def _build_elasticity_payload(
    download: SuccessfulCif,
    doc: object | None,
    status: str,
    error: str = "",
) -> dict[str, object]:
    raw = _tensor_matrix(doc, "raw") if doc is not None else None
    ieee_format = _tensor_matrix(doc, "ieee_format") if doc is not None else None
    formula = _clean_text(_value(doc, "formula_pretty")) if doc is not None else ""
    cij_basis = "ieee_format" if ieee_format else ("raw" if raw else "")
    numerical = status == "ok" and bool(cij_basis)
    fitting_method = _json_scalar(_value(doc, "fitting_method")) if doc is not None else None
    state = _json_scalar(_value(doc, "state")) if doc is not None else None
    stiffness = ieee_format or raw

    payload: dict[str, object] = {
        "schema": PHASESCOUT_ELASTICITY_SCHEMA,
        "material_id": download.material_id,
        "formula": formula or download.formula,
        "cif_filename": download.path.name,
        "source": ELASTICITY_SOURCE,
        "status": status,
        "error": error,
        "cij_basis": cij_basis,
        "units": {
            "elastic_tensor": "GPa",
            "bulk_modulus": "GPa",
            "shear_modulus": "GPa",
            "compliance_tensor": "TPa^-1",
        },
        "elastic_tensor": {"raw": raw, "ieee_format": ieee_format} if doc is not None else None,
        "bulk_modulus": _modulus_dict(doc, "bulk_modulus") if doc is not None else None,
        "shear_modulus": _modulus_dict(doc, "shear_modulus") if doc is not None else None,
        "poisson_ratio": _json_scalar(_value(doc, "homogeneous_poisson")) if doc is not None else None,
        "universal_anisotropy": _json_scalar(_value(doc, "universal_anisotropy")) if doc is not None else None,
        "fitting_method": fitting_method,
        "state": state,
        "provenance": _build_elasticity_provenance(
            download,
            status=status,
            cij_basis=cij_basis,
            fitting_method=fitting_method,
            state=state,
            numerical=numerical,
        ),
    }
    # Downstream CIF2Peaks contract: flat 6x6 + explicit frame (same as ieee when present).
    if numerical and stiffness is not None:
        payload["stiffness_GPa"] = stiffness
        payload["cif2peaks"] = {
            "schema": PHASESCOUT_ELASTICITY_SCHEMA,
            "stiffness_GPa": stiffness,
            "coordinate_frame": CIF2PEAKS_COORDINATE_FRAME,
            "paired_cif": download.path.name,
            "auto_load_hint": (
                "Place this JSON next to the CIF (stem_elasticity.json). "
                "CIF2Peaks auto-loads it when you add the CIF folder."
            ),
        }
        if isinstance(payload["provenance"], dict):
            payload["provenance"] = {
                **payload["provenance"],
                "coordinate_frame": CIF2PEAKS_COORDINATE_FRAME,
            }
    return payload


def _payload_to_csv_row(payload: dict[str, object], json_path: Path) -> dict[str, object]:
    elastic_tensor = payload.get("elastic_tensor")
    tensor_data = elastic_tensor if isinstance(elastic_tensor, dict) else {}
    ieee = tensor_data.get("ieee_format") if isinstance(tensor_data, dict) else None
    raw = tensor_data.get("raw") if isinstance(tensor_data, dict) else None
    matrix = ieee or raw

    bulk = payload.get("bulk_modulus")
    bulk = bulk if isinstance(bulk, dict) else {}
    shear = payload.get("shear_modulus")
    shear = shear if isinstance(shear, dict) else {}
    prov = payload.get("provenance")
    prov = prov if isinstance(prov, dict) else {}

    row: dict[str, object] = {
        "material_id": payload.get("material_id", ""),
        "formula": payload.get("formula", ""),
        "cif_filename": payload.get("cif_filename", ""),
        "status": payload.get("status", ""),
        "provider": prov.get("provider", "Materials Project"),
        "nature_of_data": prov.get("nature_of_data", ""),
        "numerical_cij": prov.get("numerical_cij", ""),
        "methodology_url": prov.get("methodology_url", ELASTICITY_METHODOLOGY_URL),
        "mp_material_url": prov.get("mp_material_url", ""),
        "paired_cif": prov.get("paired_cif", payload.get("cif_filename", "")),
        "disclaimer_short": ELASTICITY_DISCLAIMER_SHORT,
        "cij_basis": payload.get("cij_basis", ""),
        **_flatten_cij(matrix),  # type: ignore[arg-type]
        "K_Voigt_GPa": _csv_value(bulk.get("voigt")),
        "K_Reuss_GPa": _csv_value(bulk.get("reuss")),
        "K_VRH_GPa": _csv_value(bulk.get("vrh")),
        "G_Voigt_GPa": _csv_value(shear.get("voigt")),
        "G_Reuss_GPa": _csv_value(shear.get("reuss")),
        "G_VRH_GPa": _csv_value(shear.get("vrh")),
        "poisson_ratio": _csv_value(payload.get("poisson_ratio")),
        "universal_anisotropy": _csv_value(payload.get("universal_anisotropy")),
        "fitting_method": _csv_value(payload.get("fitting_method")),
        "state": _csv_value(payload.get("state")),
        "json_filename": json_path.name,
        "error": payload.get("error", ""),
    }
    return row


def write_cij_provenance_readme(output_dir: Path, *, n_ok: int, n_missing: int) -> Path:
    """Batch-level Cij provenance note (anti black-box)."""

    path = output_dir / "Cij_PROVENANCE.txt"
    text = f"""Cij / elasticity provenance (PhaseScout)
========================================

Provider: Materials Project (materials/elasticity API)
Nature:   DFT-calculated elastic tensors (NOT experimental handbook Cij)
Docs:     {ELASTICITY_METHODOLOGY_URL}

This batch
----------
Numerical Cij (status=ok): {n_ok}
Missing / no tensor:       {n_missing}

Where to look
-------------
- Per-material JSON:  {{cif_stem}}_elasticity.json  → field "provenance"
- Table:              elasticity_index.csv           → nature_of_data, methodology_url, mp_material_url
- Literature hints:   elasticity_web_search.csv / elasticity_web_hits.jsonl
                      (OpenAlex/web ONLY when MP has no tensor; numerical_cij=false)

Orientation
-----------
Preferred tensor basis: ieee_format (GPa), consistent with MP conventional standard cell.
PhaseScout CIF download defaults to conventional_unit_cell=True.
Downstream label: materials_project_ieee_conventional

Downstream: CIF2Peaks
---------------------
Drag this folder into CIF2Peaks (or `cif2peaks <this_folder> -o out.xlsx`).
CIF2Peaks auto-loads each {{stem}}_elasticity.json next to the CIF
(status=ok only) and fills hkl-normal Young's modulus columns.
Machine map: cif2peaks_manifest.json
No need to paste 6x6 matrices by hand.
Disable with CIF2Peaks flag: --no-auto-elastic
Some MP tensors may fail positive-definite checks in CIF2Peaks (invalid_elastic_constants);
peak tables still export; moduli stay blank for those phases.

How to cite / check
-------------------
1. Record material_id (mp-xxxx) and the paired CIF filename.
2. Open mp_material_url from the JSON provenance or elasticity_index.csv.
3. Read MP elasticity methodology page above.
4. Do NOT treat literature hits as extracted Cij matrices.

Disclaimer
----------
{ELASTICITY_DISCLAIMER}
"""
    path.write_text(text, encoding="utf-8")
    return path


class MaterialsProjectService:
    """Thin wrapper around mp-api for GUI use."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()
        if not self.api_key:
            raise ValueError("API key is empty.")
        if MPRester is None:
            raise RuntimeError("mp-api is not installed. Run: pip install -r requirements.txt")

    def search_chemsys(self, chemsys: str, max_results: int = 100) -> list[MaterialSummary]:
        chemsys = chemsys.strip()
        if not chemsys:
            raise ValueError("Chemical system is empty.")
        if max_results < 1:
            raise ValueError("max_results must be at least 1.")

        fields = [
            "material_id",
            "formula_pretty",
            "energy_above_hull",
            "band_gap",
            "symmetry",
        ]

        with MPRester(self.api_key) as mpr:
            try:
                docs = mpr.materials.summary.search(
                    chemsys=chemsys,
                    fields=fields,
                    chunk_size=max_results,
                    num_chunks=1,
                )
            except TypeError:
                docs = mpr.materials.summary.search(chemsys=chemsys, fields=fields)

        summaries = [MaterialSummary.from_doc(doc) for doc in docs]
        return summaries[:max_results]

    def search_chemsys_phases(
        self,
        chemsys: str,
        *,
        max_results: int | None = None,
        exclude_deprecated: bool = True,
        e_hull_max: float | None = None,
    ) -> list[PhaseCandidate]:
        """Search one chemical system for possible-phase cataloging."""

        chemsys = chemsys.strip()
        if not chemsys:
            raise ValueError("Chemical system is empty.")

        fields = [
            "material_id",
            "formula_pretty",
            "energy_above_hull",
            "is_stable",
            "theoretical",
            "symmetry",
            "deprecated",
        ]

        kwargs: dict[str, Any] = {
            "chemsys": chemsys,
            "fields": fields,
        }
        if exclude_deprecated:
            kwargs["deprecated"] = False
        if max_results is not None and max_results > 0:
            kwargs["chunk_size"] = max_results
            kwargs["num_chunks"] = 1

        with MPRester(self.api_key) as mpr:
            try:
                docs = mpr.materials.summary.search(**kwargs)
            except TypeError:
                # Older mp-api may not accept deprecated / chunk kwargs
                docs = mpr.materials.summary.search(chemsys=chemsys, fields=fields)

        candidates: list[PhaseCandidate] = []
        for doc in docs:
            cand = PhaseCandidate.from_doc(doc, queried_chemsys=chemsys)
            if not cand.material_id:
                continue
            if exclude_deprecated and cand.deprecated is True:
                continue
            if e_hull_max is not None and cand.energy_above_hull is not None:
                if cand.energy_above_hull > e_hull_max:
                    continue
            candidates.append(cand)
            if max_results is not None and len(candidates) >= max_results:
                break
        return candidates

    def download_cifs(
        self,
        material_ids: Iterable[str],
        output_dir: Path,
        conventional_unit_cell: bool = True,
        include_elasticity: bool = False,
        name_meta: dict[str, CifNameMeta] | None = None,
    ) -> list[DownloadResult]:
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[DownloadResult] = []
        successful_downloads: list[SuccessfulCif] = []
        meta_by_id: dict[str, CifNameMeta] = {
            str(k).strip().lower(): v for k, v in (name_meta or {}).items()
        }

        with MPRester(self.api_key) as mpr:
            for material_id in material_ids:
                mpid = str(material_id).strip().lower()
                if not mpid:
                    continue

                try:
                    structure = mpr.get_structure_by_material_id(
                        mpid,
                        final=True,
                        conventional_unit_cell=conventional_unit_cell,
                    )
                    if structure is None:
                        results.append(DownloadResult(material_id=mpid, ok=False, error="No structure returned."))
                        continue

                    meta = meta_by_id.get(mpid, CifNameMeta())
                    structure_formula = str(structure.composition.reduced_formula or "")
                    formula = meta.formula or structure_formula or "structure"
                    formula_safe = sanitize_filename_part(formula, "structure")

                    sg_symbol = meta.space_group
                    sg_number = meta.space_group_number
                    if not sg_symbol and sg_number is None:
                        sg_symbol, sg_number = _spacegroup_from_structure(structure)

                    st = (
                        StructureTypeResult(
                            meta.structure_type, meta.structure_type_rule
                        )
                        if meta.structure_type
                        else infer_structure_type_detailed(formula, sg_symbol, sg_number)
                    )
                    if not st.type:
                        st = infer_structure_type_detailed(formula, sg_symbol, sg_number)
                    filename = build_cif_filename(
                        mpid,
                        formula_safe,
                        space_group=sg_symbol,
                        space_group_number=sg_number,
                        energy_above_hull=meta.energy_above_hull,
                        is_stable=meta.is_stable,
                        structure_type=st.type,
                    )
                    path = output_dir / filename
                    structure.to(fmt="cif", filename=str(path))
                    results.append(
                        DownloadResult(
                            material_id=mpid,
                            ok=True,
                            path=path,
                            formula=formula_safe,
                        )
                    )
                    successful_downloads.append(
                        SuccessfulCif(material_id=mpid, formula=formula_safe, path=path)
                    )
                except Exception as exc:  # keep batch downloads going
                    results.append(DownloadResult(material_id=mpid, ok=False, error=str(exc)))

            if include_elasticity and successful_downloads:
                artifacts = self._export_elasticity(mpr, successful_downloads, output_dir)
                results = [
                    replace(
                        result,
                        elasticity_found=artifacts[result.material_id].found,
                        elasticity_path=artifacts[result.material_id].path,
                        elasticity_error=artifacts[result.material_id].error,
                        elasticity_status=artifacts[result.material_id].status,
                        elasticity_source=artifacts[result.material_id].source,
                    )
                    if result.ok and result.material_id in artifacts
                    else result
                    for result in results
                ]

        return results

    def _export_elasticity(
        self,
        mpr: object,
        downloads: list[SuccessfulCif],
        output_dir: Path,
    ) -> dict[str, ElasticityArtifact]:
        material_ids = [download.material_id for download in downloads]
        docs_by_id: dict[str, object] = {}
        query_error = ""

        try:
            docs = mpr.materials.elasticity.search(  # type: ignore[attr-defined]
                material_ids=material_ids,
                fields=ELASTICITY_FIELDS,
                all_fields=False,
                chunk_size=min(1000, max(1, len(material_ids))),
                num_chunks=None,
            )
            docs_by_id = {
                str(_value(doc, "material_id", "")).lower(): doc
                for doc in docs
                if _value(doc, "material_id", "")
            }
        except Exception as exc:
            query_error = str(exc)

        csv_rows: list[dict[str, object]] = []
        artifacts: dict[str, ElasticityArtifact] = {}

        for download in downloads:
            doc = docs_by_id.get(download.material_id)
            if query_error:
                status = "elasticity_query_failed"
                error = query_error
            elif doc is None:
                status = "no_elasticity_data"
                error = "No elasticity document returned."
            else:
                has_tensor = _tensor_matrix(doc, "ieee_format") or _tensor_matrix(doc, "raw")
                status = "ok" if has_tensor else "no_elastic_tensor"
                error = "" if has_tensor else "Elasticity document has no elastic tensor."

            payload = _build_elasticity_payload(download, doc, status=status, error=error)
            json_path = output_dir / f"{download.path.stem}_elasticity.json"
            json_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            csv_rows.append(_payload_to_csv_row(payload, json_path))
            artifacts[download.material_id] = ElasticityArtifact(
                material_id=download.material_id,
                found=status == "ok",
                path=json_path,
                error=error,
                status=status,
                source="materials_project",
            )

        index_path = output_dir / "elasticity_index.csv"
        fieldnames = [
            "material_id",
            "formula",
            "cif_filename",
            "status",
            "provider",
            "nature_of_data",
            "numerical_cij",
            "methodology_url",
            "mp_material_url",
            "paired_cif",
            "disclaimer_short",
            "cij_basis",
            *CIJ_LABELS,
            "K_Voigt_GPa",
            "K_Reuss_GPa",
            "K_VRH_GPa",
            "G_Voigt_GPa",
            "G_Reuss_GPa",
            "G_VRH_GPa",
            "poisson_ratio",
            "universal_anisotropy",
            "fitting_method",
            "state",
            "json_filename",
            "error",
        ]
        with index_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)

        n_ok = sum(1 for a in artifacts.values() if a.found)
        n_missing = len(artifacts) - n_ok
        write_cij_provenance_readme(output_dir, n_ok=n_ok, n_missing=n_missing)
        write_cif2peaks_manifest(output_dir, downloads, artifacts)

        return artifacts


def write_cif2peaks_manifest(
    output_dir: Path,
    downloads: list[SuccessfulCif],
    artifacts: dict[str, ElasticityArtifact],
) -> Path:
    """Machine-readable CIF↔Cij map for CIF2Peaks / agents."""

    rows: list[dict[str, object]] = []
    for download in downloads:
        art = artifacts.get(download.material_id)
        numerical = bool(art and art.found)
        json_name = art.path.name if art and art.path else f"{download.path.stem}_elasticity.json"
        rows.append(
            {
                "material_id": download.material_id,
                "cif": download.path.name,
                "elasticity_json": json_name,
                "numerical_cij": numerical,
                "elasticity_status": art.status if art else "",
                "formula": download.formula,
            }
        )
    path = output_dir / "cif2peaks_manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema": "phasescout_cif2peaks_manifest_v1",
                "pairing": "Match CIF to {stem}_elasticity.json in the same folder; "
                "CIF2Peaks auto-loads when you open this directory.",
                "items": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path
