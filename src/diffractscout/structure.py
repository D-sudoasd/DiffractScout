"""CIF loading and non-destructive structural validation."""

from __future__ import annotations

import math
import re
import warnings as warning_control
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
RHOMBOHEDRAL_SPACE_GROUP_NUMBERS = frozenset(
    {146, 148, 155, 160, 161, 166, 167}
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


def _space_group_setting(symbol: str) -> str | None:
    match = re.search(r":\s*([HR])\s*$", str(symbol).upper())
    return match.group(1) if match else None


def _is_rhombohedral_family_symbol(symbol: str) -> bool:
    return bool(re.match(r"^R(?:\s|-|\d)", str(symbol).strip(), flags=re.IGNORECASE))


def _close_metric(left: float, right: float, *, tolerance: float = 1e-5) -> bool:
    scale = max(abs(float(left)), abs(float(right)), 1.0)
    return abs(float(left) - float(right)) <= tolerance * scale


def _rhombohedral_setting_from_cell(cell: gemmi.UnitCell) -> str | None:
    """Infer an R-group setting only from an unambiguous cell metric."""

    lengths = (float(cell.a), float(cell.b), float(cell.c))
    angles = (float(cell.alpha), float(cell.beta), float(cell.gamma))
    if not all(math.isfinite(value) for value in (*lengths, *angles)):
        return None
    hexagonal = (
        _close_metric(lengths[0], lengths[1])
        and _close_metric(angles[0], 90.0)
        and _close_metric(angles[1], 90.0)
        and _close_metric(angles[2], 120.0)
    )
    if hexagonal:
        return "H"
    rhombohedral = (
        _close_metric(lengths[0], lengths[1])
        and _close_metric(lengths[1], lengths[2])
        and _close_metric(angles[0], angles[1])
        and _close_metric(angles[1], angles[2])
        and not _close_metric(angles[0], 90.0)
    )
    return "R" if rhombohedral else None


def _find_number_space_group(number: int, cell: gemmi.UnitCell) -> tuple[gemmi.SpaceGroup, str]:
    default = gemmi.find_spacegroup_by_number(number)
    if default is None:
        raise ValueError(f"Invalid International Tables space-group number: {number}.")
    default_symbol = default.xhm()
    if number not in RHOMBOHEDRAL_SPACE_GROUP_NUMBERS and not default_symbol.upper().startswith("R "):
        return default, "cif_number"
    setting = _rhombohedral_setting_from_cell(cell)
    if setting is None:
        raise ValueError(
            "Number-only rhombohedral space-group declaration cannot be resolved: "
            f"cell metric does not distinguish hexagonal (H) from rhombohedral (R) setting "
            f"for No. {number}. Provide an explicit space-group symbol with setting."
        )
    base_symbol = default_symbol.split(":", 1)[0]
    resolved = _find_space_group_by_name(f"{base_symbol}:{setting}")
    if resolved is None:
        raise ValueError(
            f"Could not resolve space-group No. {number} in explicit {setting} setting."
        )
    return resolved, f"cif_number_metric_{setting}"


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
        declared_setting = _space_group_setting(declared_symbol)
        if _is_rhombohedral_family_symbol(declared_symbol) and declared_setting is None:
            # Gemmi resolves an unqualified R symbol to its H setting by
            # default.  That default is not safe for a CIF whose cell is in R
            # axes, so derive the setting from the metric only when it is
            # unambiguous; otherwise fail closed.
            unqualified = _find_space_group_by_name(declared_symbol)
            if unqualified is not None:
                if (
                    declared_number is not None
                    and int(unqualified.number) != declared_number
                ):
                    raise ValueError(
                        f"CIF symbol {declared_symbol!r} resolves to No. "
                        f"{unqualified.number}, but the declared number is "
                        f"{declared_number}."
                    )
                number = int(unqualified.number)
                resolved, metric_source = _find_number_space_group(number, small.cell)
                source = f"cif_symbol_metric_{metric_source.rsplit('_', 1)[-1]}"
            else:
                warnings.append(
                    f"Unrecognized space-group symbol {declared_symbol!r} from cif_symbol."
                )
        else:
            resolved = _find_space_group_by_name(declared_symbol)
            if resolved is not None:
                source = "cif_symbol"
            else:
                warnings.append(f"Unrecognized space-group symbol {declared_symbol!r} from cif_symbol.")

    if resolved is None and declared_number is not None:
        try:
            resolved, source = _find_number_space_group(declared_number, small.cell)
        except RuntimeError:
            # A declared number is an explicit crystallographic contract.  An
            # unresolved R/H setting must fail closed rather than silently
            # becoming P1 or Gemmi's default H setting.
            raise ValueError(
                f"Could not resolve declared International Tables space-group number "
                f"{declared_number} from the CIF cell metric."
            ) from None

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
        "space_group_setting": (
            _space_group_setting(resolved.xhm())
        ),
    }
    return resolved, list(dict.fromkeys(warnings)), metadata


def _resolved_space_group_reparse_needed(
    block: gemmi.cif.Block,
) -> bool:
    """Return whether Gemmi must reparse after resolving the CIF declaration.

    Gemmi's parser can retain an IT number without attaching the corresponding
    operations to ``SmallStructure``.  It also defaults an unqualified R
    symbol to its H setting.  Both cases require an explicit canonical symbol
    before site expansion or crystallographic occupancy conversion.
    """

    declared_symbol = _first_known(block, SPACE_GROUP_SYMBOL_TAGS)
    if not declared_symbol:
        return True
    if _is_rhombohedral_family_symbol(declared_symbol) and _space_group_setting(
        declared_symbol
    ) is None:
        return True
    # An unrecognised symbol can leave Gemmi's parser with no operations even
    # when a valid IT number is also present; rebuild from the resolved number.
    return _find_space_group_by_name(declared_symbol) is None


def _reparse_with_resolved_space_group(
    block: gemmi.cif.Block,
    space_group: gemmi.SpaceGroup,
) -> tuple[gemmi.SmallStructure, gemmi.SmallStructure]:
    """Rebuild both Gemmi structures with the authoritative H-M setting."""

    try:
        # ``Block.as_string`` gives us an isolated copy, so provenance tags in
        # the original block remain the exact values supplied by the CIF.
        resolved_block = gemmi.cif.read_string(block.as_string()).sole_block()
        canonical_symbol = space_group.xhm()
        for tag in SPACE_GROUP_SYMBOL_TAGS:
            resolved_block.set_pair(tag, canonical_symbol)
        for tag in SPACE_GROUP_NUMBER_TAGS:
            resolved_block.set_pair(tag, str(int(space_group.number)))
        small = gemmi.make_small_structure_from_block(resolved_block)
        structure_factor_small = gemmi.make_small_structure_from_block(resolved_block)
    except Exception as exc:
        raise ValueError(
            "Gemmi could not reparse the CIF with resolved space-group "
            f"symbol {space_group.xhm()!r}: {exc}"
        ) from exc
    return small, structure_factor_small


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


def _validate_raw_occupancies(block: gemmi.cif.Block) -> None:
    """Reject unknown/non-finite/out-of-range CIF occupancies before Gemmi defaults them."""

    column = block.find_loop("_atom_site_occupancy")
    if column is None:
        return
    for index in range(len(column)):
        raw = _clean_cif_value(column[index])
        if raw in {"", "?", "."}:
            raise ValueError(
                f"CIF atom-site occupancy at row {index + 1} is unknown ({raw or 'empty'}); "
                "provide a finite value in [0, 1]."
            )
        token = raw.split("(", 1)[0].strip()
        if "(" in raw and not re.fullmatch(
            r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?\(\d+\)",
            raw,
        ):
            raise ValueError(
                f"CIF atom-site occupancy at row {index + 1} is malformed: {raw!r}."
            )
        try:
            occupancy = float(token)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"CIF atom-site occupancy at row {index + 1} is not numeric: {raw!r}."
            ) from exc
        if not math.isfinite(occupancy):
            raise ValueError(
                f"CIF atom-site occupancy at row {index + 1} is non-finite: {raw!r}."
            )
        if not 0.0 <= occupancy <= 1.0:
            raise ValueError(
                f"CIF atom-site occupancy at row {index + 1} is outside [0, 1]: {raw!r}."
            )


def _validate_raw_fractional_coordinates(block: gemmi.cif.Block) -> None:
    """Reject unknown or non-finite fractional coordinates before Gemmi parses them.

    Gemmi's native structure builder is not a safe boundary for CIF values such
    as ``?`` or ``nan``.  Validate the raw loop tokens first so malformed input
    produces a normal Python exception instead of entering native code with an
    invalid coordinate.
    """

    columns = {
        axis: block.find_loop(f"_atom_site_fract_{axis}")
        for axis in ("x", "y", "z")
    }
    lengths = {axis: len(column) for axis, column in columns.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(
            "CIF atom-site fractional coordinate columns have inconsistent row counts: "
            f"{lengths}."
        )
    row_count = next(iter(lengths.values()), 0)
    if row_count == 0:
        raise ValueError("CIF contains no complete fractional coordinate rows.")

    numeric_with_uncertainty = re.compile(
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?(?:\(\d+\))?$"
    )
    for index in range(row_count):
        for axis, column in columns.items():
            raw = _clean_cif_value(column[index])
            if raw in {"", "?", "."}:
                raise ValueError(
                    f"CIF atom-site fractional coordinate {axis} at row {index + 1} "
                    f"is unknown ({raw or 'empty'}); provide a finite numeric value."
                )
            token = raw.split("(", 1)[0].strip()
            try:
                coordinate = float(token)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"CIF atom-site fractional coordinate {axis} at row {index + 1} "
                    f"is not numeric: {raw!r}."
                ) from exc
            if not math.isfinite(coordinate):
                raise ValueError(
                    f"CIF atom-site fractional coordinate {axis} at row {index + 1} "
                    f"is non-finite: {raw!r}."
                )
            if not numeric_with_uncertainty.fullmatch(raw):
                raise ValueError(
                    f"CIF atom-site fractional coordinate {axis} at row {index + 1} "
                    f"is malformed: {raw!r}."
                )


def _dataset_value(dataset: object, name: str) -> object:
    if isinstance(dataset, dict):
        return dataset.get(name)
    return getattr(dataset, name, None)


def _spglib_crosscheck(
    small: gemmi.SmallStructure,
    declared_number: int,
    declared_symbol: str = "",
) -> tuple[int | None, str | None, str]:
    try:
        import spglib  # type: ignore[import-not-found]
    except ImportError:
        return None, None, "not_available"

    try:
        sites = list(small.get_all_unit_cell_sites())
        lattice = np.asarray(small.cell.orth.mat, dtype=float).T
        positions = np.asarray(
            [[site.fract.x, site.fract.y, site.fract.z] for site in sites],
            dtype=float,
        )
        atomic_numbers = np.asarray(
            [site.element.atomic_number for site in sites], dtype=int
        )
        with warning_control.catch_warnings():
            # spglib 2.7 warns before its 2.8 exception-mode transition. The
            # cross-check already handles failure explicitly, so suppress only
            # that upstream compatibility warning and keep all other warnings.
            warning_control.filterwarnings(
                "ignore",
                message="Set OLD_ERROR_HANDLING to false and catch the errors directly.",
                category=DeprecationWarning,
                module=r"spglib(?:\..*)?",
            )
            dataset = spglib.get_symmetry_dataset(
                (lattice, positions, atomic_numbers), symprec=1e-3
            )
    except Exception:
        return None, None, "failed"
    if dataset is None:
        return None, None, "failed"
    try:
        number_raw = _dataset_value(dataset, "number")
        symbol_raw = _dataset_value(dataset, "international")
        if number_raw is None or symbol_raw is None:
            return None, None, "failed"
        number = int(number_raw)
        symbol = str(symbol_raw)
        declared_upper = str(declared_symbol or "").strip().upper()
        declared_setting = (
            declared_upper.rsplit(":", 1)[-1]
            if ":" in declared_upper and declared_upper.rsplit(":", 1)[-1] in {"H", "R"}
            else ""
        )
        # spglib commonly reports an R-family international symbol without a
        # setting suffix; its ``choice`` field can describe the transformed
        # basis rather than Gemmi's CIF H/R declaration.  Compare settings
        # only when spglib states one explicitly, avoiding a false mismatch
        # for an otherwise authoritative R/H CIF.
        detected_setting = (
            symbol.upper().rsplit(":", 1)[-1]
            if ":" in symbol.upper() and symbol.upper().rsplit(":", 1)[-1] in {"H", "R"}
            else ""
        )
        setting_matches = not declared_setting or not detected_setting or declared_setting == detected_setting
    except (TypeError, ValueError, AttributeError):
        return None, None, "failed"
    status = "match" if number == declared_number and setting_matches else "mismatch"
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
    _validate_raw_occupancies(block)
    _validate_raw_fractional_coordinates(block)
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
    reparsed_with_resolved_symbol = _resolved_space_group_reparse_needed(block)
    if reparsed_with_resolved_symbol:
        small, structure_factor_small = _reparse_with_resolved_space_group(
            block, space_group
        )
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

    detected_number, detected_symbol, crosscheck = _spglib_crosscheck(
        small,
        int(space_group.number),
        space_group.xhm(),
    )
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
        "space_group_reparsed_with_resolved_symbol": reparsed_with_resolved_symbol,
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
