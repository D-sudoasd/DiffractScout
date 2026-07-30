"""Parse alloy names, formulas, chemical systems, and Materials Project IDs."""

from __future__ import annotations

import re
from itertools import combinations
from typing import Iterable

import gemmi

from .models import ParsedComposition
from .utils import slugify

# Aliases map to an element set only. They never imply an exact stoichiometry.
ALLOY_ALIASES: dict[str, tuple[str, ...]] = {
    "ti6al4v": ("Ti", "Al", "V"),
    "ti64": ("Ti", "Al", "V"),
    "tc4": ("Ti", "Al", "V"),
    "in718": ("Ni", "Cr", "Fe", "Nb", "Mo", "Ti", "Al"),
    "ss304": ("Fe", "Cr", "Ni"),
    "304l": ("Fe", "Cr", "Ni"),
    "ss316": ("Fe", "Cr", "Ni", "Mo"),
    "316l": ("Fe", "Cr", "Ni", "Mo"),
}

MP_ID_RE = re.compile(r"\bmp-\d+\b", re.IGNORECASE)
CHEMSYS_RE = re.compile(r"\b([A-Z][a-z]?(?:-[A-Z][a-z]?)+)\b")
FORMULA_TOKEN_RE = re.compile(r"(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?){2,}")
ELEMENT_RE = re.compile(r"([A-Z][a-z]?)")
PERCENT_PAIR_RE = re.compile(
    r"(?:([A-Z][a-z]?)\s*[:=]?\s*(\d+(?:\.\d+)?)|"
    r"(\d+(?:\.\d+)?)\s*([A-Z][a-z]?))\s*(?:wt%|at%|mass%|%)?",
    re.IGNORECASE,
)


def normalize_element(symbol: str) -> str | None:
    text = symbol.strip()
    if not text:
        return None
    text = text[0].upper() + text[1:].lower()
    try:
        element = gemmi.Element(text)
    except Exception:
        return None
    return text if element.atomic_number > 0 else None


def formula_elements(formula: str) -> tuple[str, ...]:
    """Return unique element symbols in first-appearance order."""

    elements: list[str] = []
    for symbol in ELEMENT_RE.findall(formula.replace("-", "")):
        normalized = normalize_element(symbol)
        if normalized and normalized not in elements:
            elements.append(normalized)
    return tuple(elements)


def parse_material_ids(text: str) -> tuple[list[str], list[str]]:
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[\s,;，；]+", text.strip()):
        if not item:
            continue
        normalized = item.lower()
        if re.fullmatch(r"mp-\d+", normalized):
            if normalized not in seen:
                valid.append(normalized)
                seen.add(normalized)
        elif normalized.startswith("mp-"):
            invalid.append(item)
    return valid, invalid


def _append_unique(store: list[str], values: Iterable[str]) -> None:
    for value in values:
        normalized = normalize_element(value)
        if normalized and normalized not in store:
            store.append(normalized)


def parse_composition_text(text: str) -> ParsedComposition:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Composition text is empty.")

    elements: list[str] = []
    labels: list[str] = []
    notes: list[str] = []
    material_ids = [item.lower() for item in MP_ID_RE.findall(raw)]
    material_ids = list(dict.fromkeys(material_ids))

    normalized_text = raw.lower().replace("＋", "+").replace("，", ",")
    compact = re.sub(r"[^a-z0-9]+", "", normalized_text)
    for alias, alias_elements in ALLOY_ALIASES.items():
        if alias in compact:
            _append_unique(elements, alias_elements)
            labels.append(alias)
            notes.append(f"alias_element_set_only:{alias}")

    for match in CHEMSYS_RE.finditer(raw):
        parts = match.group(1).split("-")
        normalized = [normalize_element(part) for part in parts]
        if normalized and all(normalized):
            _append_unique(elements, [item for item in normalized if item])
            labels.append(match.group(1).replace("-", ""))

    for match in PERCENT_PAIR_RE.finditer(raw):
        symbol = match.group(1) or match.group(4) or ""
        normalized = normalize_element(symbol)
        if normalized:
            _append_unique(elements, [normalized])

    # Formula/grade tokens such as Ti6Al4V. Require at least two recognized elements.
    for match in FORMULA_TOKEN_RE.finditer(raw.replace("-", "")):
        token = match.group(0)
        parsed = formula_elements(token)
        if len(parsed) >= 2:
            _append_unique(elements, parsed)
            labels.append(token)

    # Explicit additive notation, e.g. Ti-6Al-4V + Cu.
    for match in re.finditer(
        r"(?:\+|＋|/|、|和|加|with)\s*([A-Z][a-z]?)\b",
        raw,
        flags=re.IGNORECASE,
    ):
        normalized = normalize_element(match.group(1))
        if normalized:
            _append_unique(elements, [normalized])

    # Last-resort token parse for input such as "Ti Al V".
    if not elements and not material_ids:
        for token in re.findall(r"\b[A-Z][a-z]?\b", raw):
            normalized = normalize_element(token)
            if normalized:
                _append_unique(elements, [normalized])

    if not elements and not material_ids:
        raise ValueError(
            f"Could not parse elements or Materials Project IDs from {raw!r}. "
            "Use a chemical system such as Ti-Al-V, a formula/grade such as Ti6Al4V, "
            "or IDs such as mp-149."
        )

    clean_labels: list[str] = []
    for label in labels:
        cleaned = slugify(label, "")
        if cleaned and cleaned not in clean_labels:
            clean_labels.append(cleaned)

    return ParsedComposition(
        elements=tuple(elements),
        labels=tuple(clean_labels),
        material_ids=tuple(material_ids),
        notes=tuple(notes),
        raw=raw,
    )


def chemsys_subsystems(
    elements: Iterable[str],
    *,
    min_order: int = 1,
    max_order: int | None = None,
) -> list[str]:
    unique = sorted({item for raw in elements if (item := normalize_element(str(raw)))})
    if not unique:
        return []
    upper = len(unique) if max_order is None else min(len(unique), max_order)
    if min_order < 1 or upper < min_order:
        raise ValueError("Subsystem order must satisfy 1 <= min_order <= max_order.")
    return [
        "-".join(combo)
        for order in range(min_order, upper + 1)
        for combo in combinations(unique, order)
    ]
