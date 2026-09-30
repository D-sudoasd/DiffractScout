"""Validate substitutional phase prototypes and restore explicit P1 symmetry.

This module creates derived models only. It never edits source CIFs or assigns
a phase from experimental data. Chemical species are retained during the
spglib search, including coincident mixed-occupancy sites.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import warnings

import gemmi
import numpy as np
import spglib

from .structure import load_structure, unit_cell_formula_weight_g_mol

PHASE_NUMBERS = {"alpha": 194, "beta": 229, "alpha-double-prime": 63}
PHASE_MULTIPLICITIES = {"alpha": 2, "beta": 2, "alpha-double-prime": 4}
SYMMETRY_TOLERANCE_A = 1e-3
INTERSTITIALS = frozenset({"H", "B", "C", "N", "O", "F", "P", "S", "Cl", "Br", "I"})


def _spglib_cell(small: gemmi.SmallStructure) -> tuple[tuple, dict[int, tuple]]:
    """Group periodic coincident atoms by their complete occupancy fingerprint."""
    groups: list[tuple[np.ndarray, dict[str, float]]] = []
    for site in small.get_all_unit_cell_sites():
        if site.element.name in INTERSTITIALS:
            raise ValueError(
                "A substitutional metal prototype cannot contain interstitial elements."
            )
        position = np.asarray([site.fract.x, site.fract.y, site.fract.z]) % 1.0
        for previous, amounts in groups:
            delta = position - previous
            if np.max(np.abs(delta - np.rint(delta))) < 1e-4:
                amounts[site.element.name] = amounts.get(site.element.name, 0.0) + site.occ
                break
        else:
            groups.append((position, {site.element.name: float(site.occ)}))
    if not groups:
        raise ValueError("Prototype contains no occupied metal sites.")
    fingerprints: dict[tuple, int] = {}
    types: list[int] = []
    for _position, amounts in groups:
        if abs(sum(amounts.values()) - 1.0) > 1e-5:
            raise ValueError(
                "Every prototype metal site must have occupancy sum 1 without vacancies."
            )
        fingerprint = tuple(
            sorted((element, round(value, 8)) for element, value in amounts.items())
        )
        types.append(fingerprints.setdefault(fingerprint, len(fingerprints) + 1))
    cell = (
        np.asarray(small.cell.orth.mat, dtype=float).T,
        np.asarray([position for position, _ in groups]),
        np.asarray(types, dtype=int),
    )
    return cell, {number: fingerprint for fingerprint, number in fingerprints.items()}


def _dataset(cell: tuple):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Set OLD_ERROR_HANDLING to false and catch the errors directly.",
            category=DeprecationWarning,
            module=r"spglib(?:\..*)?",
        )
        dataset = spglib.get_symmetry_dataset(cell, symprec=SYMMETRY_TOLERANCE_A)
    if dataset is None:
        raise ValueError("spglib could not determine the prototype symmetry.")
    return dataset


def _check_topology(dataset, phase: str) -> None:
    if int(dataset.number) != PHASE_NUMBERS[phase]:
        raise ValueError(
            f"{phase} requires space group {PHASE_NUMBERS[phase]}, "
            f"but the atoms give {dataset.international} ({dataset.number})."
        )
    # One fully occupied orbit distinguishes the parent substitutional lattice
    # from ordered compounds that happen to share its space-group number.
    if len(set(dataset.equivalent_atoms)) != 1:
        raise ValueError(
            f"{phase} requires one substitutional metal orbit; this structure has several."
        )
    if len(dataset.std_positions) != PHASE_MULTIPLICITIES[phase]:
        raise ValueError(
            f"{phase} has the wrong number of metal sites in the standard conventional cell."
        )
    if phase == "alpha-double-prime" and set(dataset.wyckoffs) != {"c"}:
        raise ValueError("alpha-double-prime requires the Cmcm 4c metal orbit.")


def validate_phase_model(path: str | Path, phase: str, *, host: str = "") -> Any:
    """Validate declared symmetry, chemistry and the parent metal topology."""
    loaded = load_structure(path)
    if loaded.space_group_number != PHASE_NUMBERS[phase]:
        raise ValueError(f"Declared space group does not match the requested {phase} family.")
    if loaded.source_metadata.get("symmetry_crosscheck") != "match":
        raise ValueError("Prototype does not pass the independent symmetry cross-check.")
    unexpected = [
        warning
        for warning in loaded.warnings
        if not warning.startswith("Partial occupancies are included")
    ]
    if unexpected:
        raise ValueError("Prototype structure warnings: " + "; ".join(unexpected))
    cell, fingerprints = _spglib_cell(loaded.small_structure)
    _check_topology(_dataset(cell), phase)
    present = {element for fingerprint in fingerprints.values() for element, _ in fingerprint}
    if host and host not in present:
        raise ValueError(f"The prototype does not contain host {host}.")
    return loaded


def write_clean_model(small: gemmi.SmallStructure, destination: Path, *, details: str) -> None:
    """Write an explicit-symmetry average model without inherited measurement tags.

    Formula amounts describe the occupied conventional cell, with Z=1. This
    makes formula, multiplicities and cell mass consistent for mixed sites.
    """
    group = gemmi.find_spacegroup_by_name(small.spacegroup_hm)
    if group is None:
        raise ValueError("A model needs an explicit recognized space group.")
    document = gemmi.cif.Document()
    block = document.add_new_block("diffractscout_initial_model")
    block.set_pair(
        "_audit_creation_method", gemmi.cif.quote("DiffractScout derived starting model")
    )
    block.set_pair("_audit_update_record", gemmi.cif.quote(details))
    block.set_pair("_space_group_name_H-M_alt", gemmi.cif.quote(group.xhm()))
    block.set_pair("_space_group_name_Hall", gemmi.cif.quote(group.hall))
    block.set_pair("_space_group_IT_number", str(group.number))
    cell = small.cell
    for key in ("a", "b", "c"):
        block.set_pair(f"_cell_length_{key}", format(getattr(cell, key), ".10g"))
    for key in ("alpha", "beta", "gamma"):
        block.set_pair(f"_cell_angle_{key}", format(getattr(cell, key), ".10g"))
    block.set_pair("_cell_volume", format(cell.volume, ".10g"))
    totals: dict[str, float] = defaultdict(float)
    for site in small.get_all_unit_cell_sites():
        totals[site.element.name] += site.occ
    formula = " ".join(f"{element}{amount:.8g}" for element, amount in sorted(totals.items()))
    block.set_pair("_chemical_formula_sum", gemmi.cif.quote(formula))
    block.set_pair("_cell_formula_units_Z", "1")
    mass = unit_cell_formula_weight_g_mol(small)
    if mass is not None:
        block.set_pair("_chemical_formula_weight", format(mass, ".10g"))
    operations = block.init_loop("_space_group_symop_", ["id", "operation_xyz"])
    for index, operation in enumerate(group.operations(), start=1):
        operations.add_row([str(index), gemmi.cif.quote(operation.triplet())])
    atoms = block.init_loop(
        "_atom_site_",
        ["label", "type_symbol", "fract_x", "fract_y", "fract_z", "occupancy", "U_iso_or_equiv"],
    )
    for index, site in enumerate(small.sites, start=1):
        atoms.add_row(
            [
                f"{site.element.name}{index}",
                site.element.name,
                *[format(value, ".10g") for value in (site.fract.x, site.fract.y, site.fract.z)],
                format(site.occ, ".8g"),
                format(site.u_iso, ".8g"),
            ]
        )
    document.write_file(str(destination))


def normalize_prototype(source: Path, destination: Path, phase: str, *, host: str = "") -> dict:
    """Preserve a valid prototype or derive a checked conventional CIF from P1.

    P1 restoration requires chemically resolved atoms to independently give
    the requested family and its single orbit. A wrong non-P1 declaration is
    rejected. Original bytes remain in the caller's source archive.
    """
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if source == destination:
        raise ValueError("Prototype normalization refuses to overwrite the source CIF.")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}.")
    loaded = load_structure(source)
    cell, fingerprints = _spglib_cell(loaded.small_structure)
    dataset = _dataset(cell)
    _check_topology(dataset, phase)
    restored = loaded.space_group_number == 1 and int(dataset.number) != 1
    if restored:
        standard_cell = (dataset.std_lattice, dataset.std_positions, dataset.std_types)
        standard = _dataset(standard_cell)
        _check_topology(standard, phase)
        lengths = [float(np.linalg.norm(vector)) for vector in dataset.std_lattice]
        angles = []
        for first, second in ((1, 2), (0, 2), (0, 1)):
            cosine = np.dot(dataset.std_lattice[first], dataset.std_lattice[second]) / (
                lengths[first] * lengths[second]
            )
            angles.append(float(np.degrees(np.arccos(np.clip(cosine, -1, 1)))))
        small = gemmi.SmallStructure()
        small.cell = gemmi.UnitCell(*lengths, *angles)
        small.spacegroup_hm = gemmi.find_spacegroup_by_number(PHASE_NUMBERS[phase]).xhm()
        for orbit in sorted(set(standard.equivalent_atoms)):
            index = list(standard.equivalent_atoms).index(orbit)
            for element, occupancy in fingerprints[int(dataset.std_types[index])]:
                site = gemmi.SmallStructure.Site()
                site.element = gemmi.Element(element)
                site.type_symbol = element
                site.label = f"{element}{len(small.sites) + 1}"
                site.occ = occupancy
                site.fract = gemmi.Fractional(
                    *[float(value) for value in dataset.std_positions[index]]
                )
                small.add_site(site)
        write_clean_model(
            small,
            destination,
            details="Symmetry restored from fully enumerated P1 atoms using spglib; source CIF archived separately. Source lattice is a prototype, not a target-alloy measurement.",
        )
    else:
        destination.write_bytes(source.read_bytes())
    validated = validate_phase_model(destination, phase, host=host)
    return {
        "symmetry_restored_from_p1": restored,
        "symprec_A": SYMMETRY_TOLERANCE_A,
        "source_space_group": loaded.space_group_number,
        "validated_space_group": PHASE_NUMBERS[phase],
        "metal_orbits": 1,
        "conventional_metal_site_count": PHASE_MULTIPLICITIES[phase],
        "source_cell_parameters": loaded.cell_parameters,
        "prototype_cell_parameters": validated.cell_parameters,
        "standardization": {
            "transformation_matrix": dataset.transformation_matrix.tolist(),
            "origin_shift": dataset.origin_shift.tolist(),
            "std_rotation_matrix": dataset.std_rotation_matrix.tolist(),
        }
        if restored
        else None,
    }
