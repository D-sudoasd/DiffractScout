"""Heuristic metallurgy structure-type tags for CIF filenames (default, detailed)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StructureTypeResult:
    """Inferred structure family + short rule string for phase_index transparency."""

    type: str = ""
    rule: str = ""


def _composition_amount_ratio(formula: str) -> tuple[int, tuple[float, ...]] | None:
    text = (formula or "").strip()
    if not text:
        return None
    try:
        from pymatgen.core import Composition

        amounts = sorted(float(v) for v in Composition(text).get_el_amt_dict().values())
    except Exception:
        return None
    if not amounts:
        return None
    return len(amounts), tuple(amounts)


def _is_near_ratio(
    amounts: tuple[float, ...], target: tuple[float, ...], tol: float = 0.08
) -> bool:
    if len(amounts) != len(target):
        return False
    if any(a <= 0 or t <= 0 for a, t in zip(amounts, target)):
        return False
    scale = amounts[0] / target[0]
    if scale <= 0:
        return False
    return all(
        abs(a - t * scale) <= tol * max(t * scale, 1e-9) for a, t in zip(amounts, target)
    )


def infer_structure_type_detailed(
    formula: str = "",
    space_group: str = "",
    space_group_number: int | None = None,
) -> StructureTypeResult:
    """Detailed default structure-family tag (ASCII) + explainable rule.

    Returns empty type when unknown — do not invent.
    """

    try:
        number = int(space_group_number) if space_group_number is not None else None
    except (TypeError, ValueError):
        number = None

    sg = (space_group or "").replace(" ", "")
    sg_l = sg.lower().replace("−", "-")

    def _has(*needles: str) -> bool:
        return any(n.lower() in sg_l for n in needles)

    stoich = _composition_amount_ratio(formula)
    n_el = stoich[0] if stoich else 0
    amounts = stoich[1] if stoich else ()
    is_elem = n_el == 1
    is_bin = n_el == 2
    ratio_3_1 = is_bin and _is_near_ratio(amounts, (1.0, 3.0))
    ratio_1_1 = is_bin and _is_near_ratio(amounts, (1.0, 1.0))
    ratio_1_2 = is_bin and _is_near_ratio(amounts, (1.0, 2.0))

    # --- Ordered / specialty before generic families ---

    # Pm-3m (221): L12 then B2
    if number == 221 or _has("Pm-3m", "Pm3m"):
        if ratio_3_1:
            return StructureTypeResult("L12", "sg221+binary_3:1→L12")
        if ratio_1_1:
            return StructureTypeResult("B2", "sg221+binary_1:1→B2")
        return StructureTypeResult("", "sg221+stoich_unmatched")

    # L10
    if number == 123 or _has("P4/mmm", "P4mmm"):
        if ratio_1_1:
            return StructureTypeResult("L10", "sg123+binary_1:1→L10")
        return StructureTypeResult("", "sg123+stoich_unmatched")

    # A15
    if number == 223 or _has("Pm-3n", "Pm3n"):
        return StructureTypeResult("A15", "sg223→A15")

    # C15 Laves
    if number == 227 or _has("Fd-3m", "Fd3m"):
        if ratio_1_2:
            return StructureTypeResult("C15", "sg227+binary_1:2→C15")
        return StructureTypeResult("", "sg227+not_AB2")

    # Sigma
    if number == 136 or _has("P4_2/mnm", "P42/mnm", "P4_2mnm"):
        return StructureTypeResult("SIGMA", "sg136→SIGMA")

    # Chi (weak)
    if number == 217 or _has("I-43m", "I43m"):
        return StructureTypeResult("CHI", "sg217→CHI")

    # Mu (weak) — R-3m often also other phases; only tag multi-element
    if number == 166 or _has("R-3m", "R3m"):
        if n_el >= 2:
            return StructureTypeResult("MU", "sg166+multielement→MU")
        return StructureTypeResult("", "sg166+element_skip")

    # BCT-like I4/mmm (139) for simple cases
    if number == 139 or _has("I4/mmm", "I4mmm"):
        if is_elem or ratio_1_1:
            return StructureTypeResult("BCT", "sg139+simple→BCT")
        return StructureTypeResult("BCT", "sg139→BCT")

    # Fm-3m (225): DO3 (binary 3:1) before generic FCC
    if number == 225 or _has("Fm-3m", "Fm3m"):
        if is_elem:
            return StructureTypeResult("FCC", "sg225+element→FCC")
        if ratio_3_1:
            return StructureTypeResult("DO3", "sg225+binary_3:1→DO3")
        return StructureTypeResult("FCC", "sg225→FCC")

    # Im-3m (229)
    if number == 229 or _has("Im-3m", "Im3m"):
        return StructureTypeResult("BCC", "sg229→BCC")

    # P6_3/mmc (194): D019 / C14 / HCP
    if number == 194 or _has("P6_3/mmc", "P63/mmc", "P6_3mmc"):
        if is_elem:
            return StructureTypeResult("HCP", "sg194+element→HCP")
        if ratio_3_1:
            return StructureTypeResult("D019", "sg194+binary_3:1→D019")
        if ratio_1_2:
            return StructureTypeResult("C14", "sg194+binary_1:2→C14")
        return StructureTypeResult("HCP", "sg194→HCP")

    return StructureTypeResult("", "unknown_sg")


def infer_structure_type(
    formula: str = "",
    space_group: str = "",
    space_group_number: int | None = None,
) -> str:
    """Back-compat: type token only."""

    return infer_structure_type_detailed(
        formula, space_group, space_group_number
    ).type
