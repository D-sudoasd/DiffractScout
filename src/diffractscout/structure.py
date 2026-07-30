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

CELL_TAGS = (
    "_cell_length_a",
    "_cell_length_b",
    "_cell_length_c",
    "_cell_angle_alpha",
    "_cell_angle_beta",
    "_cell_angle_gamma",
)


def _clean_cif_value(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().strip("'\"")


def _known(block: gemmi.cif.Block, tag: str) -> bool:
    value = _clean_cif_value(block.find_value(tag))
    return value not in {"", "?", "."}


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


def _space_group_from_small_structure(small: gemmi.SmallStructure) -> gemmi.SpaceGroup:
    symbol = str(small.spacegroup_hm or "").strip()
    if symbol:
        try:
            found = gemmi.find_spacegroup_by_name(symbol)
            if found is not None:
                return found
        except RuntimeError:
            pass
    return gemmi.find_spacegroup_by_number(1)


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


def load_structure(cif_path: str | Path) -> StructureRecord:
    path = Path(cif_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"CIF file not found: {path}")

    document = gemmi.cif.read_file(str(path))
    block = select_structure_block(document)
    try:
        small = gemmi.make_small_structure_from_block(block)
        structure_factor_small = gemmi.make_small_structure_from_block(block)
    except Exception as exc:
        raise ValueError(f"Gemmi could not parse a small-molecule/crystal structure from {path.name}: {exc}") from exc

    cell = small.cell
    values = (cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma)
    if any(not np.isfinite(value) for value in values) or min(cell.a, cell.b, cell.c) <= 0:
        raise ValueError(f"CIF has invalid unit-cell parameters: {values}")

    space_group = _space_group_from_small_structure(small)
    declared_symbol = space_group.xhm()
    declared_number = int(space_group.number)
    asymmetric_sites = list(small.sites)
    expanded_sites = list(small.get_all_unit_cell_sites())
    partial = any(abs(float(site.occ) - 1.0) > 1e-8 for site in asymmetric_sites)

    # Gemmi's small-molecule structure-factor calculator expects
    # crystallographic occupancies, which account for special-position
    # multiplicity. CIF atom-site occupancies are retained unchanged in
    # ``small`` for validation and composition reporting; the separate object
    # below is used only for F(hkl). Omitting this conversion multiplies the
    # amplitude by the number of symmetry operations for a special-position
    # site (48 for the origin of Fm-3m).
    structure_factor_small.change_occupancies_to_crystallographic()

    warnings: list[str] = []
    if partial:
        warnings.append(
            "Partial occupancies are included in the kinematic structure-factor calculation; "
            "reported intensities represent the average CIF structure."
        )
    if declared_number == 1 and len(expanded_sites) > len(asymmetric_sites):
        warnings.append("The CIF declares P1 but contains symmetry-expanded sites; verify the source setting.")

    detected_number, detected_symbol, crosscheck = _spglib_crosscheck(small, declared_number)
    if crosscheck == "mismatch":
        warnings.append(
            f"Optional spglib cross-check detected {detected_symbol} (No. {detected_number}) "
            f"while the CIF/Gemmi setting is {declared_symbol} (No. {declared_number})."
        )
    elif crosscheck == "failed":
        warnings.append("Optional spglib symmetry cross-check did not return a dataset.")

    source_metadata: dict[str, object] = {
        "symmetry_crosscheck": crosscheck,
        "detected_space_group_symbol": detected_symbol,
        "detected_space_group_number": detected_number,
    }
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
        space_group_symbol=declared_symbol,
        space_group_number=declared_number,
        site_count_asymmetric=len(asymmetric_sites),
        site_count_unit_cell=len(expanded_sites),
        has_partial_occupancy=partial,
        warnings=warnings,
        source_metadata=source_metadata,
        small_structure=small,
        structure_factor_structure=structure_factor_small,
        space_group_object=space_group,
    )
