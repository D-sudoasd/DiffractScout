"""Explainable, conservative structure-family tags for metallurgy workflows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StructureTypeResult:
    name: str = ""
    rule: str = ""


def _amounts(formula: str) -> tuple[float, ...]:
    import re

    values: list[float] = []
    for _symbol, amount in re.findall(r"([A-Z][a-z]?)(\d*\.?\d*)", formula or ""):
        values.append(float(amount) if amount else 1.0)
    return tuple(sorted(values))


def _near_ratio(values: tuple[float, ...], target: tuple[float, ...], tolerance: float = 0.08) -> bool:
    if len(values) != len(target) or not values:
        return False
    scale = values[0] / target[0]
    return all(abs(value - scale * expected) <= tolerance * max(scale * expected, 1e-12) for value, expected in zip(values, target, strict=True))


def infer_structure_type(
    formula: str = "",
    space_group: str = "",
    space_group_number: int | None = None,
) -> StructureTypeResult:
    """Return an empty name for ambiguous cases; the rule remains auditable."""

    try:
        number = int(space_group_number) if space_group_number is not None else None
    except (TypeError, ValueError):
        number = None
    symbol = (space_group or "").replace(" ", "").replace("−", "-").lower()
    amounts = _amounts(formula)
    n_elements = len(amounts)
    elemental = n_elements == 1
    binary = n_elements == 2
    ratio_31 = binary and _near_ratio(amounts, (1.0, 3.0))
    ratio_11 = binary and _near_ratio(amounts, (1.0, 1.0))
    ratio_12 = binary and _near_ratio(amounts, (1.0, 2.0))

    def has(*tokens: str) -> bool:
        return any(token.lower() in symbol for token in tokens)

    if number == 221 or has("pm-3m", "pm3m"):
        if ratio_31:
            return StructureTypeResult("L12", "sg221+binary_3:1")
        if ratio_11:
            return StructureTypeResult("B2", "sg221+binary_1:1")
        return StructureTypeResult("", "sg221+stoichiometry_ambiguous")
    if number == 123 or has("p4/mmm", "p4mmm"):
        return StructureTypeResult("L10", "sg123+binary_1:1") if ratio_11 else StructureTypeResult("", "sg123+stoichiometry_ambiguous")
    if number == 223 or has("pm-3n", "pm3n"):
        return StructureTypeResult("A15", "sg223")
    if number == 227 or has("fd-3m", "fd3m"):
        return StructureTypeResult("C15", "sg227+binary_1:2") if ratio_12 else StructureTypeResult("", "sg227+not_AB2")
    if number == 136 or has("p4_2/mnm", "p42/mnm"):
        return StructureTypeResult("SIGMA", "sg136")
    if number == 217 or has("i-43m", "i43m"):
        return StructureTypeResult("CHI", "sg217")
    if number == 166 or has("r-3m", "r3m"):
        return StructureTypeResult("MU", "sg166+multielement") if n_elements >= 2 else StructureTypeResult("", "sg166+elemental")
    if number == 139 or has("i4/mmm", "i4mmm"):
        return StructureTypeResult("BCT", "sg139")
    if number == 225 or has("fm-3m", "fm3m"):
        if elemental:
            return StructureTypeResult("FCC", "sg225+elemental")
        if ratio_31:
            return StructureTypeResult("DO3", "sg225+binary_3:1")
        return StructureTypeResult("FCC-like", "sg225")
    if number == 229 or has("im-3m", "im3m"):
        return StructureTypeResult("BCC", "sg229")
    if number == 194 or has("p6_3/mmc", "p63/mmc"):
        if elemental:
            return StructureTypeResult("HCP", "sg194+elemental")
        if ratio_31:
            return StructureTypeResult("D019", "sg194+binary_3:1")
        if ratio_12:
            return StructureTypeResult("C14", "sg194+binary_1:2")
        return StructureTypeResult("HCP-like", "sg194")
    return StructureTypeResult("", "no_conservative_rule")
