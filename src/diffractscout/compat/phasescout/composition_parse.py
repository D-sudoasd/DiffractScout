"""Parse alloy / composition text into elements, labels, and MP-IDs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from .mp_client import MPID_RE, sanitize_filename_part

# Common engineering nicknames → unordered element set (not stoichiometry).
ALLOY_ALIASES: dict[str, tuple[str, ...]] = {
    "ti6al4v": ("Ti", "Al", "V"),
    "ti-6al-4v": ("Ti", "Al", "V"),
    "ti64": ("Ti", "Al", "V"),
    "tc4": ("Ti", "Al", "V"),
    "ti6al4vcu": ("Ti", "Al", "V", "Cu"),
    "ti-6al-4v-cu": ("Ti", "Al", "V", "Cu"),
    "ti65": ("Ti", "Al", "Sn", "Zr", "Mo", "Si"),  # common Ti65-family elements; refine if needed
    "in718": ("Ni", "Cr", "Fe", "Nb", "Mo", "Ti", "Al"),
    "ss316": ("Fe", "Cr", "Ni", "Mo"),
    "ss304": ("Fe", "Cr", "Ni"),
}

ELEMENT_TOKEN_RE = re.compile(r"\b([A-Z][a-z]?)\b")
# Ti-6Al-4V style grade tokens
GRADE_CHUNK_RE = re.compile(
    r"\b((?:[A-Z][a-z]?)(?:-?\d+(?:\.\d+)?(?:[A-Z][a-z]?)?)+)\b"
)
# Ti6Al4V compact formula
COMPACT_FORMULA_RE = re.compile(r"\b((?:[A-Z][a-z]?\d*\.?\d*){2,})\b")
# Al 6 / 6Al / Al:6 / Al=6wt%
PCT_PAIR_RE = re.compile(
    r"(?:"
    r"([A-Z][a-z]?)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:wt%|at%|mass%|%)?"
    r"|"
    r"(\d+(?:\.\d+)?)\s*(?:wt%|at%|mass%|%)?\s*([A-Z][a-z]?)"
    r")"
)
CHEMSYS_RE = re.compile(r"\b([A-Z][a-z]?(?:-[A-Z][a-z]?)+)\b")
MPID_FIND_RE = re.compile(r"\bmp-\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedComposition:
    """Normalized parse result from free-text alloy / composition input."""

    elements: tuple[str, ...]
    labels: tuple[str, ...] = ()
    mpids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    raw: str = ""

    @property
    def chemsys(self) -> str:
        return "-".join(sorted(self.elements))

    @property
    def default_label(self) -> str:
        if self.labels:
            return sanitize_filename_part(self.labels[0], "composition")
        if self.mpids and not self.elements:
            return sanitize_filename_part("_".join(self.mpids[:3]), "mpids")
        if self.elements:
            return sanitize_filename_part("".join(self.elements), "composition")
        return "composition"


def _normalize_element(symbol: str) -> str | None:
    if not symbol:
        return None
    symbol = symbol[0].upper() + symbol[1:].lower() if len(symbol) > 1 else symbol.upper()
    # Reject obvious non-elements that match the pattern in English text
    if symbol in {"Id", "In", "As", "At", "Be", "No", "If", "Or", "To", "Of"}:
        # In, As, At, Be, No are real elements — keep them.
        # Id/If/Or/To/Of are not.
        if symbol in {"Id", "If", "Or", "To", "Of"}:
            return None
    try:
        from pymatgen.core import Element

        Element(symbol)
        return symbol
    except Exception:
        # Fallback allowlist of common materials elements if pymatgen missing
        common = {
            "H", "Li", "Be", "B", "C", "N", "O", "F", "Na", "Mg", "Al", "Si", "P", "S", "Cl",
            "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
            "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb",
            "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Pb", "Bi", "La", "Ce", "Nd",
        }
        return symbol if symbol in common else None


def _elements_from_formula_string(formula: str) -> list[str]:
    formula = formula.strip()
    if not formula:
        return []
    try:
        from pymatgen.core import Composition

        comp = Composition(formula)
        return [str(el) for el in comp.elements]
    except Exception:
        # Regex fallback: Ti6Al4V / Ti-6Al-4V
        cleaned = formula.replace("-", "")
        found: list[str] = []
        for match in re.finditer(r"([A-Z][a-z]?)(\d*\.?\d*)", cleaned):
            el = _normalize_element(match.group(1))
            if el and el not in found:
                found.append(el)
        return found


def _add_elements(store: list[str], symbols: Iterable[str]) -> None:
    for raw in symbols:
        el = _normalize_element(str(raw))
        if el and el not in store:
            store.append(el)


def parse_composition_text(text: str) -> ParsedComposition:
    """
    Parse free-text composition / alloy description.

    Accepts examples:
      - Ti-Al-V / Ti-Al-V-Cu
      - Ti6Al4V, Ti-6Al-4V
      - Ti 90, Al 6, V 4 wt%
      - mp-23, mp-149
      - aliases: ti64, in718
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Composition text is empty.")

    elements: list[str] = []
    labels: list[str] = []
    notes: list[str] = []
    mpids: list[str] = []

    for m in MPID_FIND_RE.findall(raw):
        mid = m.lower()
        if mid not in mpids:
            mpids.append(mid)

    lowered = raw.lower().replace("＋", "+").replace("，", ",")
    # Alias hits on whole tokens / compact forms
    compact = re.sub(r"[\s_]+", "", lowered)
    for alias, els in ALLOY_ALIASES.items():
        alias_key = alias.replace("-", "")
        if alias in lowered or alias_key in compact:
            _add_elements(elements, els)
            labels.append(alias.replace("-", ""))
            notes.append(f"alias:{alias}")

    # Explicit chemsys tokens: Ti-Al-V
    for match in CHEMSYS_RE.finditer(raw):
        token = match.group(1)
        parts = token.split("-")
        # Skip pure numeric grades mis-read; require all parts look like elements
        parsed_parts = [_normalize_element(p) for p in parts]
        if all(parsed_parts):
            _add_elements(elements, [p for p in parsed_parts if p])
            labels.append(token.replace("-", ""))

    # Percentage pairs
    for match in PCT_PAIR_RE.finditer(raw):
        if match.group(1) and match.group(2):
            el = _normalize_element(match.group(1))
        else:
            el = _normalize_element(match.group(4) or "")
        if el:
            _add_elements(elements, [el])

    # Compact formulas and grade-like chunks
    for match in GRADE_CHUNK_RE.finditer(raw):
        token = match.group(1)
        if MPID_RE.match(token):
            continue
        els = _elements_from_formula_string(token)
        if els:
            _add_elements(elements, els)
            labels.append(re.sub(r"[^A-Za-z0-9]+", "", token))

    for match in COMPACT_FORMULA_RE.finditer(raw):
        token = match.group(1)
        if "-" in token:
            continue
        els = _elements_from_formula_string(token)
        if len(els) >= 2:
            _add_elements(elements, els)
            labels.append(token)

    # Additive elements after + / 加 / and (e.g. "Ti-6Al-4V + Cu")
    for match in re.finditer(
        r"(?:\+|＋|/|、|和|加|with)\s*([A-Z][a-z]?)(?:\b|(?=\d))",
        raw,
        flags=re.IGNORECASE,
    ):
        el = _normalize_element(match.group(1))
        if el:
            _add_elements(elements, [el])

    # Last resort: unique element tokens if still empty (e.g. "Ti Al V")
    if not elements and not mpids:
        for match in ELEMENT_TOKEN_RE.finditer(raw):
            el = _normalize_element(match.group(1))
            if el:
                _add_elements(elements, [el])

    if not elements and not mpids:
        raise ValueError(
            f"Could not parse elements or MP-IDs from: {raw!r}. "
            "Try chemsys like Ti-Al-V, formula Ti6Al4V, or mp-149."
        )

    # Prefer stable label order
    clean_labels: list[str] = []
    for lab in labels:
        lab2 = sanitize_filename_part(lab, "")
        if lab2 and lab2 not in clean_labels:
            clean_labels.append(lab2)

    return ParsedComposition(
        elements=tuple(elements),
        labels=tuple(clean_labels),
        mpids=tuple(mpids),
        notes=tuple(notes),
        raw=raw,
    )


def chemsys_subsystems(elements: Iterable[str]) -> list[str]:
    """All non-empty subsystems as alphabetical chemsys strings (MP convention)."""
    els = []
    for e in elements:
        n = _normalize_element(str(e))
        if n and n not in els:
            els.append(n)
    els_sorted = sorted(els)
    systems: list[str] = []
    for r in range(1, len(els_sorted) + 1):
        for combo in combinations(els_sorted, r):
            systems.append("-".join(combo))
    return systems


def applies_to_for_elements(
    entry_elements: Iterable[str],
    alloy_labels: dict[str, set[str]],
) -> str:
    """
    Build applies_to string: which user alloys can contain this entry's elements.

    alloy_labels maps label -> element set.
    """
    entry = {_normalize_element(str(e)) for e in entry_elements}
    entry.discard(None)
    hits = []
    for label, allowed in alloy_labels.items():
        if entry.issubset(allowed):
            hits.append(label)
    return ";".join(hits)
