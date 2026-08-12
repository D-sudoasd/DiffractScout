"""CIF loading and non-destructive structural validation."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import gemmi
import numpy as np

from .models import StructureRecord
from .utils import sha256_file

# CODATA 2018 Avogadro constant; density uses Å³ → cm³ via 1e-24.
AVOGADRO_PER_MOL = 6.02214076e23

CELL_TAGS = (
    "_cell_length_a",
    "_cell_length_b",
    "_cell_length_c",
    "_cell_angle_alpha",
    "_cell_angle_beta",
    "_cell_angle_gamma",
)
SPACE_GROUP_SYMBOL_TAGS = (
    "_space_group_name_H-M_alt",
    "_symmetry_space_group_name_H-M",
)
SPACE_GROUP_NUMBER_TAGS = (
    "_space_group_IT_number",
    "_symmetry_Int_Tables_number",
)
SOURCE_IDENTIFIER_TAGS = (
    "_database_code_ICSD",
    "_cod_database_code",
    "_database_code_depnum_ccdc_archive",
    "_audit_block_doi",
)


def _clean_cif_value(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().strip("'\"")


def _known(block: gemmi.cif.Block, tag: str) -> bool:
    value = _clean_cif_value(block.find_value(tag))
    return value not in {"", "?", "."}


def _first_known(block: gemmi.cif.Block, tags: Iterable[str]) -> str:
    for tag in tags:
        value = _clean_cif_value(block.find_value(tag))
        if value not in {"", "?", "."}:
            return value
    return ""


def _parse_cif_int(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    try:
        return int(float(text.split("(", 1)[0]))
    except ValueError:
        return None


def _is_structure_block(block: gemmi.cif.Block) -> bool:
    if not all(_known(block, tag) for tag in CELL_TAGS):
        return False
    x = block.find_loop("_atom_site_fract_x")
    y = block.find_loop("_atom_site_fract_y")
    z = block.find_loop("_atom_site_fract_z")
    return min(len(x), len(y), len(z)) > 0


def select_structure_block(document: gemmi.cif.Document) -> gemmi.cif.Block:
    candidates = [block for block in document if _is_structure_block(block)]
    if not candidates:
        raise ValueError("CIF contains no block with complete cell parameters and fractional atom coordinates.")
    for preferred in ("standardized_unitcell", "conventional", "published_cell"):
        for block in candidates:
            if preferred in block.name.lower():
                return block
    return candidates[0]


def _find_space_group_by_name(symbol: str) -> gemmi.SpaceGroup | None:
    if not symbol:
        return None
    try:
        return gemmi.find_spacegroup_by_name(symbol)
    except (RuntimeError, ValueError):
        return None


def _resolve_space_group(
    small: gemmi.SmallStructure,
    block: gemmi.cif.Block,
) -> tuple[gemmi.SpaceGroup, list[str], dict[str, object]]:
    """Resolve the CIF space group without silently treating unknown declarations as P1."""

    warnings: list[str] = []
    small_symbol = str(small.spacegroup_hm or "").strip()
    declared_symbol = _first_known(block, SPACE_GROUP_SYMBOL_TAGS)
    declared_number_text = _first_known(block, SPACE_GROUP_NUMBER_TAGS)
    declared_number = _parse_cif_int(declared_number_text)

    resolved: gemmi.SpaceGroup | None = None
    source = ""
    # Explicit CIF declarations take precedence over parser defaults. This is
    # important for files that provide only an International Tables number,
    # where a parser may otherwise expose a placeholder P1 symbol.
    if declared_symbol:
        resolved = _find_space_group_by_name(declared_symbol)
        if resolved is not None:
            source = "cif_symbol"
        else:
            warnings.append(f"Unrecognized space-group symbol {declared_symbol!r} from cif_symbol.")

    if resolved is None and declared_number is not None:
        try:
            resolved = gemmi.find_spacegroup_by_number(declared_number)
            source = "cif_number"
        except (RuntimeError, ValueError):
            warnings.append(f"Invalid International Tables space-group number: {declared_number}.")

    if resolved is None and small_symbol:
        resolved = _find_space_group_by_name(small_symbol)
        if resolved is not None:
            source = "gemmi_small_structure"
        else:
            warnings.append(
                f"Unrecognized space-group symbol {small_symbol!r} from gemmi_small_structure."
            )

    if resolved is None:
        resolved = gemmi.find_spacegroup_by_number(1)
        source = "explicit_P1_fallback"
        warnings.append(
            "No recognized space-group declaration was available; the CIF is interpreted in P1. "
            "Systematic absences and multiplicities require independent verification."
        )

    if declared_number is not None and int(resolved.number) != declared_number:
        warnings.append(
            f"CIF space-group number {declared_number} conflicts with the resolved symbol "
            f"{resolved.xhm()} (No. {resolved.number})."
        )
    declared_group = _find_space_group_by_name(declared_symbol)
    if declared_group is not None and int(declared_group.number) != int(resolved.number):
        warnings.append(
            f"CIF symbol {declared_symbol!r} and the resolved group {resolved.xhm()} refer to different numbers."
        )

    metadata: dict[str, object] = {
        "space_group_resolution_source": source,
        "space_group_symbol_from_small_structure": small_symbol or None,
        "space_group_symbol_from_cif": declared_symbol or None,
        "space_group_number_from_cif": declared_number,
    }
    return resolved, list(dict.fromkeys(warnings)), metadata


def _formula_from_expanded_sites(sites: Iterable[gemmi.SmallStructure.Site]) -> str:
    counts: dict[str, float] = defaultdict(float)
    for site in sites:
        symbol = site.element.name
        if symbol and site.occ > 0:
            counts[symbol] += float(site.occ)
    if not counts:
        return "unknown"

    values = list(counts.values())
    rounded = [round(value) for value in values]
    if all(abs(value - integer) < 1e-6 for value, integer in zip(values, rounded, strict=True)):
        integers = [int(value) for value in rounded]
        divisor = 0
        for value in integers:
            divisor = math.gcd(divisor, value)
        divisor = max(divisor, 1)
        counts = {key: value / divisor for key, value in counts.items()}

    def format_amount(value: float) -> str:
        if abs(value - 1.0) < 1e-8:
            return ""
        if abs(value - round(value)) < 1e-8:
            return str(int(round(value)))
        return f"{value:.4g}"

    return "".join(f"{symbol}{format_amount(amount)}" for symbol, amount in counts.items())


def _formula_from_block(block: gemmi.cif.Block, expanded_sites: list[gemmi.SmallStructure.Site]) -> str:
    for tag in ("_chemical_formula_sum", "_chemical_formula_structural"):
        value = _clean_cif_value(block.find_value(tag))
        if value not in {"", "?", "."}:
            return value.replace(" ", "")
    return _formula_from_expanded_sites(expanded_sites)


def _spglib_crosscheck(
    small: gemmi.SmallStructure,
    declared_number: int,
) -> tuple[int | None, str | None, str]:
    try:
        import spglib  # type: ignore[import-not-found]
    except ImportError:
        return None, None, "not_available"

    sites = list(small.get_all_unit_cell_sites())
    lattice = np.asarray(small.cell.orth.mat, dtype=float).T
    positions = np.asarray([[site.fract.x, site.fract.y, site.fract.z] for site in sites], dtype=float)
    atomic_numbers = np.asarray([site.element.atomic_number for site in sites], dtype=int)
    dataset = spglib.get_symmetry_dataset((lattice, positions, atomic_numbers), symprec=1e-3)
    if dataset is None:
        return None, None, "failed"
    number = int(dataset.number)
    symbol = str(dataset.international)
    status = "match" if number == declared_number else "mismatch"
    return number, symbol, status


def unit_cell_formula_weight_g_mol(small: gemmi.SmallStructure) -> float | None:
    """Sum elemental atomic weights × occupancy over expanded unit-cell sites.

    Uses ``gemmi.Element.weight`` (IUPAC conventional atomic weights). Returns
    None when no occupied sites contribute a finite mass.
    """

    total = 0.0
    counted = False
    for site in small.get_all_unit_cell_sites():
        occ = float(site.occ)
        if occ <= 0:
            continue
        try:
            mass = float(site.element.weight)
        except Exception:
            return None
        if not math.isfinite(mass) or mass <= 0:
            return None
        total += occ * mass
        counted = True
    if not counted or not math.isfinite(total) or total <= 0:
        return None
    return float(total)


def density_g_cm3(formula_weight_g_mol: float, volume_A3: float) -> float | None:
    """Crystallographic density ρ = M / (N_A · V) with V in cm³ from Å³."""

    if not math.isfinite(formula_weight_g_mol) or formula_weight_g_mol <= 0:
        return None
    if not math.isfinite(volume_A3) or volume_A3 <= 0:
        return None
    # V_cm3 = V_A3 * 1e-24; ρ = M / (N_A * V_cm3) = M * 1e24 / (N_A * V_A3)
    return float(formula_weight_g_mol * 1.0e24 / (AVOGADRO_PER_MOL * volume_A3))


def structure_mass_metadata(structure: StructureRecord) -> dict[str, float | None]:
    """Return unit-cell formula weight and density for analysis metadata."""

    small = structure.small_structure
    volume = float(small.cell.volume) if small is not None else float("nan")
    formula_weight = unit_cell_formula_weight_g_mol(small) if small is not None else None
    density = (
        density_g_cm3(formula_weight, volume)
        if formula_weight is not None and math.isfinite(volume)
        else None
    )
    return {
        "cell_volume_A3": float(volume) if math.isfinite(volume) else None,
        "formula_weight_g_mol": formula_weight,
        "density_g_cm3": density,
    }


def load_structure(cif_path: str | Path) -> StructureRecord:
    path = Path(cif_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"CIF file not found: {path}")

    try:
        document = gemmi.cif.read_file(str(path))
    except Exception as exc:
        raise ValueError(f"Gemmi could not read CIF {path.name}: {exc}") from exc
    block = select_structure_block(document)
    try:
        small = gemmi.make_small_structure_from_block(block)
        structure_factor_small = gemmi.make_small_structure_from_block(block)
    except Exception as exc:
        raise ValueError(f"Gemmi could not parse a crystal structure from {path.name}: {exc}") from exc

    cell = small.cell
    values = (cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma)
    if any(not np.isfinite(value) for value in values) or min(cell.a, cell.b, cell.c) <= 0:
        raise ValueError(f"CIF has invalid unit-cell parameters: {values}")
    if any(angle <= 0 or angle >= 180 for angle in (cell.alpha, cell.beta, cell.gamma)):
        raise ValueError(f"CIF has invalid unit-cell angles: {(cell.alpha, cell.beta, cell.gamma)}")
    if not np.isfinite(float(cell.volume)) or float(cell.volume) <= 0:
        raise ValueError("CIF unit-cell volume is non-positive or non-finite.")

    space_group, warnings, space_group_metadata = _resolve_space_group(small, block)
    # Keep both independent structures in the same resolved setting. The second
    # object is modified only for Gemmi's crystallographic occupancy convention.
    small.spacegroup_hm = space_group.xhm()
    structure_factor_small.spacegroup_hm = space_group.xhm()

    asymmetric_sites = list(small.sites)
    if not asymmetric_sites:
        raise ValueError("CIF contains no atomic sites after parsing.")
    expanded_sites = list(small.get_all_unit_cell_sites())
    partial = any(abs(float(site.occ) - 1.0) > 1e-8 for site in asymmetric_sites)

    # Gemmi's small-structure structure-factor calculator expects
    # crystallographic occupancies, which account for special-position
    # multiplicity. The original CIF occupancies are retained in ``small`` for
    # validation and composition reporting.
    try:
        structure_factor_small.change_occupancies_to_crystallographic()
    except Exception as exc:
        raise ValueError(f"Could not convert CIF occupancies for structure-factor calculation: {exc}") from exc

    if partial:
        warnings.append(
            "Partial occupancies are included in the kinematic structure-factor calculation; "
            "reported intensities represent the average CIF structure."
        )

    detected_number, detected_symbol, crosscheck = _spglib_crosscheck(small, int(space_group.number))
    if crosscheck == "mismatch":
        warnings.append(
            f"spglib detected {detected_symbol} (No. {detected_number}) while the resolved CIF/Gemmi "
            f"setting is {space_group.xhm()} (No. {space_group.number})."
        )
    elif crosscheck == "failed":
        warnings.append("spglib symmetry cross-check did not return a dataset.")
    elif crosscheck == "not_available":
        warnings.append("spglib is unavailable; independent symmetry cross-check was skipped.")

    source_metadata: dict[str, object] = {
        **space_group_metadata,
        "symmetry_crosscheck": crosscheck,
        "detected_space_group_symbol": detected_symbol,
        "detected_space_group_number": detected_number,
    }
    source_identifiers = {
        tag: value
        for tag in SOURCE_IDENTIFIER_TAGS
        if (value := _first_known(block, (tag,)))
    }
    if source_identifiers:
        source_metadata["cif_source_identifiers"] = source_identifiers

    mp_match = re.search(r"(mp-\d+)", path.name, flags=re.IGNORECASE)
    if mp_match:
        material_id = mp_match.group(1).lower()
        source_metadata.update(
            {
                "material_id": material_id,
                "material_url": f"https://materialsproject.org/materials/{material_id}",
            }
        )

    return StructureRecord(
        cif_path=path,
        cif_sha256=sha256_file(path),
        data_block=block.name,
        formula=_formula_from_block(block, expanded_sites),
        cell_parameters=tuple(float(value) for value in values),
        space_group_symbol=space_group.xhm(),
        space_group_number=int(space_group.number),
        site_count_asymmetric=len(asymmetric_sites),
        site_count_unit_cell=len(expanded_sites),
        has_partial_occupancy=partial,
        warnings=list(dict.fromkeys(warnings)),
        source_metadata=source_metadata,
        small_structure=small,
        structure_factor_structure=structure_factor_small,
        space_group_object=space_group,
    )
