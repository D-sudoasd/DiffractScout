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
# Formula candidates may contain grouping punctuation and a multiplier after a
# closing group, for example ``(Fe,Ni)3Al``.  The full-token boundaries keep
# ordinary prose from being treated as a formula while retaining the legacy
# compact alloy-formula path after hyphens are removed.
FORMULA_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[A-Z][a-z]?(?:\d+(?:\.\d+)?)?|"
    r"\d+(?:\.\d+)?|[()[\],]"
    r")+(?![A-Za-z0-9])"
)
ELEMENT_RE = re.compile(r"([A-Z][a-z]?)")
PERCENT_PAIR_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:([A-Za-z]{1,2})\s*[:=]?\s*(\d+(?:\.\d+)?)|"
    r"(\d+(?:\.\d+)?)\s*([A-Za-z]{1,2}))\s*(?:wt%|at%|mass%|%)?",
    re.IGNORECASE,
)
_INPUT_TRANSLATION = str.maketrans(
    {
        "‐": "-",  # hyphen
        "‑": "-",  # non-breaking hyphen
        "‒": "-",  # figure dash
        "–": "-",  # en dash
        "—": "-",  # em dash
        "−": "-",  # mathematical minus
        "－": "-",  # full-width hyphen-minus
        "＋": "+",
        "，": ",",
        "；": ";",
    }
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


_ADDITIVE_SEPARATOR_RE = re.compile(r"[+/、和加]|\bwith\b", re.IGNORECASE)
_ADDITIVE_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*")


def _adjacent_additive_term(text: str, index: int, *, direction: int) -> str:
    """Return the nearest lexical term on one side of an additive separator."""

    step = 1 if direction > 0 else -1
    cursor = index if direction > 0 else index - 1
    while 0 <= cursor < len(text) and text[cursor].isspace():
        cursor += step
    if not 0 <= cursor < len(text):
        return ""
    if text[cursor] in "+/、和加":
        return ""
    if direction > 0:
        match = _ADDITIVE_TERM_RE.match(text, cursor)
        return match.group(0) if match else ""
    end = cursor + 1
    while cursor >= 0 and (text[cursor].isalnum() or text[cursor] in "-_"):
        cursor -= 1
    return text[cursor + 1 : end]


def _is_supported_additive_left(term: str) -> bool:
    """Return whether a non-slash additive left term has known semantics."""

    if normalize_element(term):
        return True
    if any(_alias_has_input_boundaries(term, alias) for alias in ALLOY_ALIASES):
        return True
    parsed = formula_elements(term)
    return len(parsed) >= 2 or (len(parsed) == 1 and bool(re.search(r"\d", term)))


def _validate_explicit_additive_syntax(text: str) -> None:
    """Reject malformed explicit separators before formula/token fallback."""

    for match in _ADDITIVE_SEPARATOR_RE.finditer(text):
        left = _adjacent_additive_term(text, match.start(), direction=-1)
        right = _adjacent_additive_term(text, match.end(), direction=1)
        separator = match.group(0)
        if not left or not right:
            raise ValueError(
                "Explicit additive composition has a missing term around "
                f"separator {separator!r} in {text!r}."
            )
        if separator == "/":
            if not normalize_element(left) or not normalize_element(right):
                raise ValueError(
                    "Explicit additive composition slash requires recognized element symbols "
                    f"on both sides: {left!r}/{right!r}."
                )
        elif not _is_supported_additive_left(left):
            raise ValueError(
                "Explicit additive composition has an unknown or unsupported left "
                f"term {left!r}; provide an element, formula, grade, or alloy alias."
            )
        elif not normalize_element(right):
            raise ValueError(
                "Explicit additive composition contains unknown element term(s) "
                f"{right!r}; every additive term must be a recognized element symbol."
            )


def _alias_has_input_boundaries(text: str, alias: str) -> bool:
    """Return whether a compact alias is standalone in the original input.

    Alloy aliases such as ``Ti-6Al-4V`` need punctuation-insensitive matching,
    but the characters immediately outside the match must still be checked in
    the original input.  This prevents a compact alias from being found inside
    a larger grade or prose token while allowing separators inside a valid
    alias.
    """

    compact_chars: list[str] = []
    original_positions: list[int] = []
    for index, char in enumerate(text):
        if char.isascii() and char.isalnum():
            compact_chars.append(char.lower())
            original_positions.append(index)
    compact = "".join(compact_chars)
    alias_start = 0
    while True:
        match_start = compact.find(alias, alias_start)
        if match_start < 0:
            return False
        match_end = match_start + len(alias) - 1
        original_start = original_positions[match_start]
        original_end = original_positions[match_end]
        before = text[original_start - 1] if original_start else ""
        after = text[original_end + 1] if original_end + 1 < len(text) else ""
        if not (
            before.isascii()
            and before.isalnum()
            or after.isascii()
            and after.isalnum()
        ):
            return True
        alias_start = match_start + 1


def _reject_embedded_alias_tokens(text: str) -> None:
    """Reject an ASCII grade/prose token that embeds a known alloy alias.

    A compact alias may cross punctuation such as the hyphens in ``Ti-6Al-4V``;
    a single larger alphanumeric token such as ``Ti640`` is different and is
    not a valid formula or grade.  Failing closed here prevents later generic
    formula/percentage fallbacks from creating an unrelated chemical system.
    """

    for token in re.findall(r"[A-Za-z0-9]+", text):
        lowered = token.lower()
        for alias in ALLOY_ALIASES:
            if lowered != alias and alias in lowered:
                raise ValueError(
                    f"Composition token {token!r} contains non-standalone alias "
                    f"{alias!r}; refusing ambiguous composition input."
                )


def _has_explicit_percent_unit(match: re.Match[str]) -> bool:
    return bool(re.search(r"(?:wt%|at%|mass%|%)\s*$", match.group(0), re.IGNORECASE))


def _percent_pair_is_unambiguous(
    text: str,
    match: re.Match[str],
) -> bool:
    """Keep unitless percentage pairs out of compact formula tokens."""

    if _has_explicit_percent_unit(match):
        return True
    if match.group(1) is not None:
        between = text[match.end(1) : match.start(2)]
        return any(char.isspace() for char in between) or ":" in between or "=" in between
    # Numeric-first pairs such as ``50Al`` are retained for compatibility.
    return True


def parse_composition_text(text: str) -> ParsedComposition:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Composition text is empty.")

    elements: list[str] = []
    labels: list[str] = []
    notes: list[str] = []
    normalized_raw = raw.translate(_INPUT_TRANSLATION)
    material_ids = [item.lower() for item in MP_ID_RE.findall(normalized_raw)]
    material_ids = list(dict.fromkeys(material_ids))

    _reject_embedded_alias_tokens(normalized_raw)
    _validate_explicit_additive_syntax(normalized_raw)

    for alias, alias_elements in ALLOY_ALIASES.items():
        if _alias_has_input_boundaries(normalized_raw, alias):
            _append_unique(elements, alias_elements)
            labels.append(alias)
            notes.append(f"alias_element_set_only:{alias}")

    # Accept a complete chemical-system expression case-insensitively while
    # keeping formula/prose token parsing conservative.
    if re.fullmatch(r"[A-Za-z]{1,2}(?:-[A-Za-z]{1,2})+", normalized_raw):
        parts = normalized_raw.split("-")
        normalized = [normalize_element(part) for part in parts]
        if normalized and all(normalized):
            _append_unique(elements, [item for item in normalized if item])
            labels.append("".join(item for item in normalized if item))

    for match in CHEMSYS_RE.finditer(normalized_raw):
        parts = match.group(1).split("-")
        normalized = [normalize_element(part) for part in parts]
        if normalized and all(normalized):
            _append_unique(elements, [item for item in normalized if item])
            labels.append(match.group(1).replace("-", ""))

    percent_matches = [
        match
        for match in PERCENT_PAIR_RE.finditer(normalized_raw)
        if _percent_pair_is_unambiguous(normalized_raw, match)
    ]
    explicit_percent_spans = [
        (match.start(), match.end())
        for match in percent_matches
        if _has_explicit_percent_unit(match)
    ]
    formula_contexts = [
        (match.start(), match.end())
        for match in FORMULA_CANDIDATE_RE.finditer(normalized_raw)
        if len(formula_elements(match.group(0))) >= 2
    ]
    for match in percent_matches:
        if any(
            start <= match.start() and match.end() <= end
            for start, end in formula_contexts
        ):
            continue
        symbol = match.group(1) or match.group(4) or ""
        normalized = normalize_element(symbol)
        if normalized:
            _append_unique(elements, [normalized])

    # Formula/grade tokens such as Ti6Al4V. Multi-element tokens are accepted;
    # a single-element token must include an explicit stoichiometric number
    # (for example C60 or O2). Alias candidates are skipped so all-uppercase
    # aliases such as IN718 cannot be reinterpreted as unrelated elements.
    for match in FORMULA_CANDIDATE_RE.finditer(normalized_raw.replace("-", "")):
        token = match.group(0)
        if any(
            match.start() < end and match.end() > start
            for start, end in explicit_percent_spans
        ):
            continue
        if re.sub(r"[^A-Za-z0-9]+", "", token).lower() in ALLOY_ALIASES:
            continue
        parsed = formula_elements(token)
        is_single_element_formula = len(parsed) == 1 and bool(re.search(r"\d", token))
        if len(parsed) >= 2 or is_single_element_formula:
            _append_unique(elements, parsed)
            labels.append(token)

    # Explicit additive notation, e.g. Fe+Ni, Fe/Ni, Fe with Ni, or Fe和Ni.
    # Capture the complete chain: a right-only match silently dropped the
    # first element, while pairwise matching would miss every other element.
    invalid_additive_terms: list[str] = []
    for match in re.finditer(
        r"(?<![A-Za-z])([A-Z][a-z]?)"
        r"(?:\s*(?:\+|/|、|和|加)\s*[A-Z][a-z]?|"
        r"\s+with\s+[A-Z][a-z]?)+\b",
        normalized_raw,
        flags=re.IGNORECASE,
    ):
        tokens = re.split(
            r"\s*(?:\+|/|、|和|加)\s*|\s+with\s+",
            match.group(0),
            flags=re.IGNORECASE,
        )
        normalized_tokens = [normalize_element(token) for token in tokens]
        if not all(normalized_tokens):
            invalid_additive_terms.extend(
                token
                for token, normalized in zip(tokens, normalized_tokens, strict=True)
                if not normalized
            )
        else:
            _append_unique(elements, tokens)

    # Preserve right-side additives when the left operand is a complete
    # formula/grade or a known alias (for example ``SS304 + Mo``).  Slash is
    # intentionally excluded here so arbitrary prose such as ``phase/phase``
    # cannot be interpreted as an additive expression.
    for match in re.finditer(
        r"(?:\+|、|和|加)\s*([A-Z][a-z]?)\b|"
        r"\s+with\s+([A-Z][a-z]?)\b",
        normalized_raw,
        flags=re.IGNORECASE,
    ):
        token = match.group(1) or match.group(2) or ""
        if normalize_element(token):
            _append_unique(elements, [token])
        else:
            invalid_additive_terms.append(token)

    if invalid_additive_terms:
        unknown_terms = ", ".join(
            repr(term) for term in dict.fromkeys(invalid_additive_terms)
        )
        raise ValueError(
            "Explicit additive composition contains unknown element term(s) "
            f"{unknown_terms}; every additive term must be a recognized element symbol."
        )

    # Last-resort token parse for input such as "Ti Al V".
    if not elements and not material_ids:
        for token in re.findall(r"\b[A-Z][a-z]?\b", normalized_raw):
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
