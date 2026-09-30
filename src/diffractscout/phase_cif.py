"""Symmetry-prototype download and caller-supplied CIF composition edits.

``fetch_prototypes`` chooses alpha, beta, or alpha-double-prime symmetry
prototypes. ``adapt_cif`` writes a new CIF from caller-supplied composition
and cited lattice or coordinate values. Neither function reads literature,
and ``analyze``, ``discover``, and ``run`` do not call them.
"""

from __future__ import annotations

import csv
import math
import os
import re
import tempfile
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping, Sequence

import gemmi

from .composition import (
    chemsys_subsystems,
    formula_elements,
    normalize_element,
    parse_composition_text,
)
from .models import CandidateRecord
from .structure import load_structure, select_structure_block, unit_cell_formula_weight_g_mol
from .structure_types import infer_structure_type
from .utils import sha256_file

_SCAFFOLD_NAME = "cod_1523304_ti_nb_cmcm.cif"
_SCAFFOLD_SOURCE = "COD 1523304"
_SCAFFOLD_NOTE = (
    "Ti-20 at% Nb symmetry scaffold from COD 1523304. "
    "The lattice and Nb occupancy are not the target alloy."
)
_PARTIAL_OCCUPANCY_WARNING = (
    "Partial occupancies are included in the kinematic structure-factor calculation"
)
_ADAPT_COMMENT = (
    "# DiffractScout adapt: publication and database fields already in this file "
    "describe the source scaffold, not the edited composition or lattice."
)
_OCCUPANCY_QUANTUM = Decimal("0.00001")
_PERCENT_TOLERANCE = Decimal("0.05")
_SITE_OCCUPANCY_TOLERANCE = Decimal("0.02")
_INTERSTITIALS = frozenset({"H", "B", "C", "N", "O", "F", "P", "S", "Cl", "Br", "I"})
_CELL_TAGS = {
    "a": "_cell_length_a",
    "b": "_cell_length_b",
    "c": "_cell_length_c",
    "alpha": "_cell_angle_alpha",
    "beta": "_cell_angle_beta",
    "gamma": "_cell_angle_gamma",
}
_LENGTH_KEYS = ("a", "b", "c")
_ANGLE_KEYS = ("alpha", "beta", "gamma")
_FRACT_KEYS = ("x", "y", "z")
_FORMULA_TAGS = (
    "_chemical_formula_sum",
    "_chemical_formula_structural",
    "_chemical_name_systematic",
)
_DENSITY_TAGS = (
    "_exptl_crystal_density_diffrn",
    "_exptl_crystal_density_meas",
)
_INDEX_FIELDS = (
    "phase",
    "status",
    "material_id",
    "source",
    "space_group",
    "declared_symmetry",
    "formula",
    "target_composition",
    "cif",
    "note",
)
_TC4_WEIGHTS = (
    ("Ti", Decimal("90")),
    ("Al", Decimal("6")),
    ("V", Decimal("4")),
)
_NOMINAL_GRADES = {
    "tc4": _TC4_WEIGHTS,
    "ti64": _TC4_WEIGHTS,
    "ti-6al-4v": _TC4_WEIGHTS,
    "ti6al4v": _TC4_WEIGHTS,
}
_NOMINAL_NOTE = (
    "Conventional Ti-6Al-4V grade: 6 wt% Al, 4 wt% V, balance Ti. "
    "Nominal grade, not a heat analysis and not an equilibrium phase composition."
)
_PHASE_ALIASES = {
    "alpha": "alpha",
    "α": "alpha",
    "beta": "beta",
    "β": "beta",
    "alpha-double-prime": "alpha-double-prime",
    "alpha''": "alpha-double-prime",
    "a''": "alpha-double-prime",
    "α''": "alpha-double-prime",
}


@dataclass(frozen=True)
class _PhaseRule:
    number: int
    filename: str


PHASE_RULES: dict[str, _PhaseRule] = {
    "alpha": _PhaseRule(194, "alpha.cif"),
    "beta": _PhaseRule(229, "beta.cif"),
    "alpha-double-prime": _PhaseRule(63, "alpha-double-prime.cif"),
}
DEFAULT_PHASES = ("alpha", "beta", "alpha-double-prime")


@dataclass(frozen=True)
class PrototypeRecord:
    phase: str
    status: str
    material_id: str = ""
    source: str = ""
    space_group: str = ""
    declared_symmetry: str = ""
    formula: str = ""
    target_composition: bool = False
    cif_path: Path | None = None
    note: str = ""


@dataclass(frozen=True)
class FetchPrototypesResult:
    output_dir: Path
    index_path: Path
    host: str
    elements: tuple[str, ...]
    records: tuple[PrototypeRecord, ...]

    @property
    def exit_code(self) -> int:
        if any(record.status == "missing" for record in self.records):
            return 3
        if self.records and all(record.cif_path is not None for record in self.records):
            return 0
        return 2


@dataclass(frozen=True)
class AdaptResult:
    cif_path: Path
    sidecar_path: Path
    composition_basis: str
    occupancies: dict[str, str]
    citation: str
    symmetry_crosscheck: str
    space_group_symbol: str
    space_group_number: int | None
    warnings: tuple[str, ...]


@dataclass
class _SiteGroup:
    kind: str
    rows: list[dict[str, str]]
    elements: tuple[str, ...]
    fract: dict[str, str]
    values: dict[str, float]


def canonical_phase(name: str) -> str:
    """Return the canonical phase id, or raise ``ValueError``."""

    compact = re.sub(r"[\s_]+", "-", name.strip().lower())
    compact = compact.replace("′", "'").replace("’", "'").replace("″", "''")
    phase = _PHASE_ALIASES.get(compact)
    if phase is None:
        raise ValueError(f"Unknown phase {name!r}. Use alpha, beta, or alpha-double-prime.")
    return phase


def canonicalize_phases(names: Sequence[str] | None) -> tuple[str, ...]:
    if not names:
        return DEFAULT_PHASES
    output: list[str] = []
    for name in names:
        phase = canonical_phase(name)
        if phase not in output:
            output.append(phase)
    return tuple(output)


def scaffold_resource() -> Any:
    """Return the packaged COD 1523304 file, or the checkout example copy."""

    resource = files("diffractscout").joinpath("prototype_data", _SCAFFOLD_NAME)
    if resource.is_file():
        return resource
    fallback = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "inherited_cif2peaks"
        / "ti_nb_orthorhombic_cmcm_partial_occupancy.cif"
    )
    if fallback.is_file():
        return fallback
    raise FileNotFoundError("The alpha-double-prime COD 1523304 scaffold is not installed.")


def select_prototype(
    candidates: Sequence[CandidateRecord],
    *,
    phase: str,
    elements: Sequence[str],
    host: str,
) -> CandidateRecord | None:
    """Choose one symmetry prototype, or ``None`` when the family is absent.

    An elemental prototype of ``host`` outranks a lower-energy multielement
    candidate. Alpha additionally excludes D0_19 and C14. Omega is space
    group 191, so it cannot enter the alpha family. A formula element outside
    ``elements`` excludes the candidate; that is what keeps oxides out of an
    oxygen-free alloy.
    """

    eligible = rank_prototypes(candidates, phase=phase, elements=elements, host=host)
    return eligible[0] if eligible else None


def rank_prototypes(candidates: Sequence[CandidateRecord], *, phase: str, elements: Sequence[str], host: str) -> list[CandidateRecord]:
    """Metadata shortlist; each candidate still requires an atom-level check."""
    phase_name = canonical_phase(phase)
    allowed = _element_set(elements)
    host_symbol = _required_element(host)
    if host_symbol not in allowed:
        raise ValueError(f"Host element {host_symbol} is not in the requested composition.")
    eligible = [
        candidate
        for candidate in candidates
        if _eligible(candidate, phase=phase_name, elements=allowed, host=host_symbol)
    ]
    return sorted(eligible, key=lambda candidate: _rank_key(candidate, host_symbol))


def resolve_occupancies(
    *,
    nominal: str = "",
    weight_percent: str = "",
    atomic_percent: str = "",
) -> tuple[str, str, dict[str, Decimal]]:
    """Return ``(basis, note, occupancies)`` summing exactly to 1.

    Each fraction is rounded to five decimal places. The residual needed to
    make the sum exact is added to the last element in input order.
    """

    sources = {
        "nominal_grade": nominal.strip(),
        "weight_percent": weight_percent.strip(),
        "atomic_percent": atomic_percent.strip(),
    }
    chosen = [name for name, value in sources.items() if value]
    if len(chosen) != 1:
        raise ValueError("Provide exactly one of nominal, weight percent, or atomic percent.")
    basis = chosen[0]
    if basis == "nominal_grade":
        pairs = _nominal_pairs(sources[basis])
        note = _NOMINAL_NOTE
        occupancies = _occupancies_from_amounts(pairs, atomic=False)
    elif basis == "weight_percent":
        pairs = _parse_amount_assignments(sources[basis])
        note = (
            "Caller-supplied weight percent. This records the supplied composition, "
            "not a heat analysis or an equilibrium phase composition."
        )
        occupancies = _occupancies_from_amounts(pairs, atomic=False)
    else:
        pairs = _parse_amount_assignments(sources[basis])
        note = (
            "Caller-supplied atomic percent. This records the supplied composition, "
            "not a heat analysis or an equilibrium phase composition."
        )
        occupancies = _occupancies_from_amounts(pairs, atomic=True)
    return basis, note, occupancies


def parse_template_assignments(items: Sequence[str] | None) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for item in items or []:
        phase, path = _parse_template_assignment(item)
        if phase in mapping:
            raise ValueError(f"Duplicate --template for {phase}.")
        mapping[phase] = path
    return mapping


def parse_fractional_assignments(items: Sequence[str] | None) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for item in items or []:
        axis, value = _parse_fractional_assignment(item)
        if axis in mapping:
            raise ValueError(f"Fractional coordinate {axis} was given more than once.")
        mapping[axis] = value
    return mapping


def adapt_cif(
    source: str | Path,
    destination: str | Path,
    *,
    nominal: str = "",
    weight_percent: str = "",
    atomic_percent: str = "",
    a: float | None = None,
    b: float | None = None,
    c: float | None = None,
    alpha: float | None = None,
    beta: float | None = None,
    gamma: float | None = None,
    fract: Mapping[str, float] | None = None,
    citation: str = "",
) -> AdaptResult:
    """Write a derivative CIF without modifying ``source``.

    Lattice parameters and fractional coordinates that appear in the call are
    caller-supplied values and require ``citation``. Composition alone does
    not. The destination is replaced only after ``load_structure`` reports a
    matching symmetry cross-check.
    """

    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"CIF file not found: {source_path}")
    if destination_path.suffix.lower() != ".cif":
        raise ValueError("adapt output must use a .cif suffix.")
    if destination_path.exists() and destination_path.is_dir():
        raise ValueError("adapt output must be a .cif file, not a directory.")
    sidecar_path = destination_path.with_name(destination_path.stem + ".adapt.json")
    if _same_path(source_path, destination_path) or _same_path(source_path, sidecar_path):
        raise ValueError("adapt refuses to overwrite the source CIF.")
    if destination_path.exists():
        raise FileExistsError(f"Refusing to overwrite {destination_path}.")
    if sidecar_path.exists():
        raise FileExistsError(f"Refusing to overwrite {sidecar_path}.")

    basis, composition_note, occupancies = resolve_occupancies(
        nominal=nominal,
        weight_percent=weight_percent,
        atomic_percent=atomic_percent,
    )
    if set(occupancies) & _INTERSTITIALS:
        raise ValueError("adapt composition describes the substitutional metal sublattice; interstitial percentages cannot be substituted onto metal sites.")
    citation_text = _flatten_citation(citation)
    lattice = {
        "a": a,
        "b": b,
        "c": c,
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
    }
    coordinates = {str(axis): float(value) for axis, value in dict(fract or {}).items()}
    _validate_requested_cell(lattice)
    lattice, implied_axes = _symmetry_constrained_lattice(source_path, lattice)
    _validate_requested_coordinates(coordinates)
    if (any(value is not None for value in lattice.values()) or coordinates) and not citation_text:
        raise ValueError(
            "Pass --citation when changing a lattice parameter or fractional coordinate."
        )

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    cif_descriptor, cif_name = tempfile.mkstemp(prefix=f".{destination_path.stem}-", suffix=".tmp", dir=destination_path.parent)
    os.close(cif_descriptor)
    json_descriptor, json_name = tempfile.mkstemp(prefix=f".{sidecar_path.stem}-", suffix=".tmp", dir=sidecar_path.parent)
    os.close(json_descriptor)
    temp_cif = Path(cif_name)
    temp_json = Path(json_name)
    moved_cif = False
    output_hash = ""
    source_hash = sha256_file(source_path)
    try:
        edit = _write_adapted_cif(
            source_path,
            temp_cif,
            occupancies=occupancies,
            lattice=lattice,
            coordinates=coordinates,
            citation=citation_text,
        )
        loaded = _validated_structure(
            temp_cif,
            expected_elements=set(occupancies) | set(edit["interstitials_preserved"]),
        )
        if sha256_file(source_path) != source_hash:
            raise ValueError("Source CIF changed during adaptation; no output was published.")
        output_hash = sha256_file(temp_cif)
        payload = {
            "schema": "diffractscout_adapt_v1",
            "source_cif": str(source_path),
            "source_sha256": source_hash,
            "output_cif": destination_path.name,
            "output_sha256": output_hash,
            "composition_basis": basis,
            "composition_note": composition_note,
            "citation": citation_text or None,
            "occupancies": {element: _occupancy_token(value) for element, value in occupancies.items()},
            "lattice_edits": edit["lattice_edits"],
            "lattice_axes_implied_by_symmetry": implied_axes,
            "lattice_unchanged": edit["lattice_unchanged"],
            "coordinate_edits": edit["coordinate_edits"],
            "coordinates_unchanged": edit["coordinates_unchanged"],
            "interstitials_preserved": edit["interstitials_preserved"],
            "symmetry_crosscheck": loaded.source_metadata.get("symmetry_crosscheck"),
            "space_group_symbol": loaded.space_group_symbol,
            "space_group_number": loaded.space_group_number,
            "warnings": list(loaded.warnings),
        }
        _write_json(temp_json, payload)
        _publish_new_file(temp_cif, destination_path)
        moved_cif = True
        _publish_new_file(temp_json, sidecar_path)
    except Exception:
        temp_cif.unlink(missing_ok=True)
        temp_json.unlink(missing_ok=True)
        if moved_cif and destination_path.is_file() and sha256_file(destination_path) == output_hash:
            destination_path.unlink(missing_ok=True)
        raise
    finally:
        temp_cif.unlink(missing_ok=True)
        temp_json.unlink(missing_ok=True)

    occupancy_text = {element: _occupancy_token(value) for element, value in occupancies.items()}
    return AdaptResult(
        cif_path=destination_path,
        sidecar_path=sidecar_path,
        composition_basis=basis,
        occupancies=occupancy_text,
        citation=citation_text,
        symmetry_crosscheck=str(loaded.source_metadata.get("symmetry_crosscheck") or ""),
        space_group_symbol=loaded.space_group_symbol,
        space_group_number=loaded.space_group_number,
        warnings=tuple(loaded.warnings),
    )


def _publish_new_file(temporary: Path, destination: Path) -> None:
    """Reuse the bundle's platform no-replace primitive for a derived file."""
    from .pipeline import _rename_directory_noreplace

    _rename_directory_noreplace(temporary, destination)


def _symmetry_constrained_lattice(source: Path, lattice: Mapping[str, float | None]) -> tuple[dict[str, float | None], list[str]]:
    """Tie conventional symmetry-equivalent axes without inventing a length."""
    block = select_structure_block(gemmi.cif.read_file(str(source)))
    small = gemmi.make_small_structure_from_block(block)
    group = gemmi.find_spacegroup_by_name(_hm_symbol(block))
    if group is None and _it_number(block):
        group = gemmi.find_spacegroup_by_number(int(_it_number(block)))
    axes: tuple[str, ...] = ()
    if group is not None:
        number = group.number
        if 195 <= number <= 230:
            axes = ("a", "b", "c")
        elif 75 <= number <= 142 or 168 <= number <= 194:
            axes = ("a", "b")
        elif 143 <= number <= 167 and abs(small.cell.gamma - 120) < 1e-5:
            axes = ("a", "b")
    output = dict(lattice)
    supplied = [float(output[axis]) for axis in axes if output[axis] is not None]
    if supplied and any(not math.isclose(value, supplied[0], rel_tol=1e-8, abs_tol=1e-8) for value in supplied):
        raise ValueError(f"Space group {group.xhm()} requires equal cell axes {', '.join(axes)}.")
    implied = []
    if supplied:
        for axis in axes:
            if output[axis] is None:
                output[axis] = supplied[0]
                implied.append(axis)
    return output, implied


def fetch_prototypes(
    composition: str,
    output_dir: str | Path,
    *,
    phases: Sequence[str] | None = None,
    templates: Mapping[str, str | Path] | None = None,
    template_args: Sequence[str] | None = None,
    provider: Any = None,
    api_key: str | None = None,
    max_subsystems: int = 64,
    host: str = "",
) -> FetchPrototypesResult:
    """Copy one CIF per requested phase and write ``prototype_index.csv``.

    The copied file keeps the database or scaffold contents. Target-alloy
    occupancy is always false at this step. Alpha-double-prime uses the
    packaged COD scaffold when Materials Project has no eligible hit, or when
    no API key and no provider were supplied. Alpha and beta then raise
    ``ValueError`` instead of writing an empty result.
    """

    selected = canonicalize_phases(phases)
    template_map = _template_map(templates, template_args)
    parsed = parse_composition_text(composition)
    if not parsed.elements:
        raise ValueError(
            "fetch-prototypes needs a composition that contains elements. "
            "The first parsed element is the host."
        )
    elements = parsed.elements
    host = _required_element(host) if host else elements[0]
    if host not in elements:
        raise ValueError(f"Host element {host} is not in the requested composition.")
    key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
    needs_mp = [phase for phase in selected if phase not in template_map and phase != "alpha-double-prime"]
    search_scaffold = "alpha-double-prime" in selected and "alpha-double-prime" not in template_map
    will_search = bool(needs_mp or (search_scaffold and (provider is not None or key)))
    if needs_mp and provider is None and key is None:
        raise ValueError(
            "No Materials Project API key. Pass --api-key or set MP_API_KEY. "
            "alpha and beta need Materials Project or --template. "
            "alpha-double-prime can use the packaged COD 1523304 scaffold without a key."
        )
    if will_search:
        _check_subsystem_cap(elements, max_subsystems)
    if provider is None and key and will_search:
        from .providers.materials_project import MaterialsProjectProvider

        try:
            provider = MaterialsProjectProvider(key)
        except Exception as exc:
            raise RuntimeError(_redact_provider_error(exc, key, None)) from None

    destination = Path(output_dir).expanduser().resolve()
    _reject_existing_outputs(destination, selected)
    candidates: list[CandidateRecord] = []
    if provider is not None and will_search:
        try:
            candidates = _collect_candidates(provider, elements, max_subsystems)
        except Exception as exc:
            raise RuntimeError(_redact_provider_error(exc, key, provider)) from None

    chosen: dict[str, CandidateRecord] = {}
    missing_notes: dict[str, str] = {}
    for phase in selected:
        if phase in template_map:
            continue
        hit = select_prototype(candidates, phase=phase, elements=elements, host=host)
        if hit is not None:
            chosen[phase] = hit
        elif phase != "alpha-double-prime":
            missing_notes[phase] = (
                f"No {phase} candidate in space group {PHASE_RULES[phase].number} "
                f"contains host {host} inside {'-'.join(elements)}."
            )

    destination.mkdir(parents=True, exist_ok=True)
    try:
        downloaded = _download_bytes(provider, tuple(chosen.values())) if chosen else {}
    except Exception as exc:
        raise RuntimeError(_redact_provider_error(exc, key, provider)) from None
    downloaded = {material_id: (data, _redact_provider_error(error, key, provider)) for material_id, (data, error) in downloaded.items()}
    records: list[PrototypeRecord] = []
    for phase in selected:
        if phase in template_map:
            records.append(
                _store_bytes(
                    template_map[phase].read_bytes(),
                    destination / PHASE_RULES[phase].filename,
                    phase=phase,
                    status="template",
                    material_id="",
                    origin=f"template:{template_map[phase]}",
                    space_group="",
                    formula="",
                    note=(
                        "User-supplied template. fetch-prototypes leaves its composition "
                        "and lattice unchanged."
                    ),
                    use_file_identity=True,
                )
            )
            continue
        if phase in chosen:
            candidate = chosen[phase]
            data, error = downloaded.get(
                candidate.material_id,
                (None, "Materials Project did not return this structure."),
            )
            if data is not None:
                records.append(
                    _store_bytes(
                        data,
                        destination / PHASE_RULES[phase].filename,
                        phase=phase,
                        status="downloaded",
                        material_id=candidate.material_id,
                        origin="Materials Project",
                        space_group=str(candidate.space_group_number or ""),
                        formula=candidate.formula,
                        note=_download_note(candidate, host),
                        use_file_identity=False,
                    )
                )
            else:
                records.append(_missing_record(phase, error))
            continue
        if phase == "alpha-double-prime":
            if host != "Ti":
                records.append(_missing_record(phase, "The packaged COD 1523304 scaffold is for host Ti only. Supply a suitable --template for this host."))
                continue
            records.append(
                _store_bytes(
                    _read_bytes(scaffold_resource()),
                    destination / PHASE_RULES[phase].filename,
                    phase=phase,
                    status="scaffold",
                    material_id="",
                    origin=_SCAFFOLD_SOURCE,
                    space_group="63",
                    formula="",
                    note=_scaffold_note(searched=will_search),
                    use_file_identity=True,
                )
            )
            continue
        records.append(_missing_record(phase, missing_notes.get(phase, "No prototype was selected.")))

    index_path = destination / "prototype_index.csv"
    _write_index(index_path, records)
    return FetchPrototypesResult(
        output_dir=destination,
        index_path=index_path,
        host=host,
        elements=elements,
        records=tuple(records),
    )


def _redact_provider_error(message: object, key: str | None, provider: Any) -> str:
    text = str(message)
    for secret in (key, getattr(provider, "api_key", "")):
        if isinstance(secret, str) and secret.strip():
            text = text.replace(secret.strip(), "[redacted]")
    return text


def _element_set(elements: Sequence[str]) -> frozenset[str]:
    allowed: set[str] = set()
    for raw in elements:
        symbol = _required_element(str(raw))
        allowed.add(symbol)
    if not allowed:
        raise ValueError("Composition has no elements.")
    return frozenset(allowed)


def _required_element(symbol: str) -> str:
    normalized = normalize_element(symbol)
    if normalized is None:
        raise ValueError(f"Unknown element symbol {symbol!r}.")
    return normalized


def _eligible(
    candidate: CandidateRecord,
    *,
    phase: str,
    elements: frozenset[str],
    host: str,
) -> bool:
    if candidate.deprecated is True:
        return False
    number = candidate.space_group_number
    if number is None or int(number) != PHASE_RULES[phase].number:
        return False
    present = formula_elements(candidate.formula)
    if not present or not set(present) <= elements or host not in present:
        return False
    if phase == "alpha":
        kind = infer_structure_type(
            candidate.formula,
            candidate.space_group,
            int(number),
        )
        if kind.name in {"D019", "C14"}:
            return False
    return True


def _rank_key(candidate: CandidateRecord, host: str) -> tuple[object, ...]:
    present = formula_elements(candidate.formula)
    elemental_host = 0 if present == (host,) else 1
    energy = candidate.energy_above_hull_eV_atom
    if energy is None or not math.isfinite(float(energy)):
        energy_rank: tuple[int, float] = (1, 0.0)
    else:
        energy_rank = (0, float(energy))
    return (elemental_host, energy_rank[0], energy_rank[1], candidate.material_id)


def _nominal_pairs(name: str) -> tuple[tuple[str, Decimal], ...]:
    key = name.strip().lower().replace("–", "-").replace("—", "-").replace("−", "-")
    key = re.sub(r"\s+", "", key)
    pairs = _NOMINAL_GRADES.get(key)
    if pairs is None:
        raise ValueError(
            f"Unknown nominal grade {name!r}. Supported grades: tc4, ti64, ti-6al-4v."
        )
    return pairs


def _parse_amount_assignments(text: str) -> tuple[tuple[str, Decimal], ...]:
    chunks = _assignment_chunks(text)
    if not chunks:
        raise ValueError("Composition assignment is empty.")
    pairs: list[tuple[str, Decimal]] = []
    seen: set[str] = set()
    for chunk in chunks:
        match = re.fullmatch(
            r"([A-Za-z]{1,2})\s*[=:]\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))",
            chunk.strip(),
        )
        if match is None:
            raise ValueError(f"Cannot read a composition assignment from {chunk!r}.")
        symbol = normalize_element(match.group(1))
        if symbol is None:
            raise ValueError(f"Unknown element in composition assignment {chunk!r}.")
        if symbol in seen:
            raise ValueError(f"Element {symbol} appears more than once.")
        try:
            amount = Decimal(match.group(2))
        except Exception as exc:
            raise ValueError(f"Amount for {symbol} is not numeric.") from exc
        if not amount.is_finite() or amount <= 0:
            raise ValueError(f"Amount for {symbol} must be positive.")
        seen.add(symbol)
        pairs.append((symbol, amount))
    total = sum((amount for _, amount in pairs), Decimal(0))
    if abs(total - Decimal(100)) > _PERCENT_TOLERANCE:
        raise ValueError(f"Composition percentages sum to {total}, outside 100 ± 0.05.")
    return tuple(pairs)


def _assignment_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    for part in re.split(r"[,;]+", text.strip()):
        piece = part.strip()
        if not piece:
            continue
        if piece.count("=") + piece.count(":") > 1:
            chunks.extend(item for item in piece.split() if item)
        else:
            chunks.append(piece)
    return chunks


def _occupancies_from_amounts(
    pairs: Sequence[tuple[str, Decimal]],
    *,
    atomic: bool,
) -> dict[str, Decimal]:
    if atomic:
        moles = list(pairs)
    else:
        moles = [(element, amount / _atomic_weight(element)) for element, amount in pairs]
    total = sum((amount for _, amount in moles), Decimal(0))
    if total <= 0:
        raise ValueError("Composition amounts must be positive.")
    exact = [(element, amount / total) for element, amount in moles]
    rounded = [
        (element, value.quantize(_OCCUPANCY_QUANTUM, rounding=ROUND_HALF_UP))
        for element, value in exact
    ]
    residual = Decimal(1) - sum((value for _, value in rounded), Decimal(0))
    last_element, last_value = rounded[-1]
    rounded[-1] = (last_element, last_value + residual)
    total_rounded = sum((value for _, value in rounded), Decimal(0))
    if total_rounded != Decimal(1) or any(value <= 0 or value > 1 for _, value in rounded):
        raise ValueError("Rounded occupancies are outside (0, 1] or do not sum to 1.")
    return dict(rounded)


def _atomic_weight(symbol: str) -> Decimal:
    element = gemmi.Element(symbol)
    weight = float(element.weight)
    if element.atomic_number <= 0 or not math.isfinite(weight) or weight <= 0:
        raise ValueError(f"{symbol} has no positive atomic weight.")
    return Decimal(str(weight))


def _occupancy_token(value: Decimal) -> str:
    if value == 1:
        return "1"
    return f"{value:.5f}"


def _parse_template_assignment(text: str) -> tuple[str, Path]:
    if "=" not in text:
        raise ValueError("--template expects phase=path.")
    raw_phase, raw_path = text.split("=", 1)
    phase = canonical_phase(raw_phase)
    path = Path(raw_path.strip()).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Template CIF not found: {path}")
    return phase, path.resolve()


def _parse_fractional_assignment(text: str) -> tuple[str, float]:
    if "=" not in text:
        raise ValueError("--fract expects x=value, y=value, or z=value.")
    raw_axis, raw_value = text.split("=", 1)
    axis = raw_axis.strip().lower()
    if axis not in _FRACT_KEYS:
        raise ValueError(f"Fractional coordinate axis must be x, y, or z, not {raw_axis!r}.")
    value = _parse_float(raw_value)
    return axis, value


def _flatten_citation(citation: str) -> str:
    return re.sub(r"[\x00-\x1f]+", " ", citation).strip()


def _validate_requested_cell(lattice: Mapping[str, float | None]) -> None:
    for key in _LENGTH_KEYS:
        value = lattice.get(key)
        if value is None:
            continue
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(f"Cell length {key} must be positive and finite.")
    for key in _ANGLE_KEYS:
        value = lattice.get(key)
        if value is None:
            continue
        angle = float(value)
        if not math.isfinite(angle) or angle <= 0 or angle >= 180:
            raise ValueError(f"Cell angle {key} must lie strictly between 0 and 180 degrees.")


def _validate_requested_coordinates(coordinates: Mapping[str, float]) -> None:
    for axis, value in coordinates.items():
        if axis not in _FRACT_KEYS:
            raise ValueError(f"Fractional coordinate axis must be x, y, or z, not {axis!r}.")
        if not math.isfinite(value):
            raise ValueError(f"Fractional coordinate {axis} must be finite.")


def _write_adapted_cif(
    source: Path,
    destination: Path,
    *,
    occupancies: Mapping[str, Decimal],
    lattice: Mapping[str, float | None],
    coordinates: Mapping[str, float],
    citation: str,
) -> dict[str, Any]:
    document = gemmi.cif.read_file(str(source))
    block = select_structure_block(document)
    lattice_edits, lattice_changed = _apply_lattice(block, lattice)
    groups = _site_groups(block)
    metal_groups = [group for group in groups if group.kind == "metal"]
    if not metal_groups:
        raise ValueError("CIF has no metal site that can receive the composition.")
    _require_unique_coordinates(metal_groups, coordinates)
    tags = _output_tags(_loop_tags(block))
    rows, interstitials = _composition_rows(groups, tags, occupancies, coordinates)
    suffixes = [tag[len("_atom_site_") :] for tag in tags]
    block.init_loop("_atom_site_", suffixes)
    loop = block.find_loop("_atom_site_label").get_loop()
    for row in rows:
        loop.add_row(row)
    _update_formula_tags(block, groups, occupancies)
    if lattice_changed:
        _update_volume(block)
    for tag in _DENSITY_TAGS:
        _erase_pair(block, tag)
    document.write_file(str(destination))
    _prepend_comment(destination, citation)
    return {
        "lattice_edits": lattice_edits,
        "lattice_unchanged": [key for key in (*_LENGTH_KEYS, *_ANGLE_KEYS) if key not in lattice_edits],
        "coordinate_edits": {
            axis: format(value, ".10g") for axis, value in coordinates.items()
        },
        "coordinates_unchanged": [axis for axis in _FRACT_KEYS if axis not in coordinates],
        "interstitials_preserved": interstitials,
    }


def _apply_lattice(
    block: gemmi.cif.Block,
    lattice: Mapping[str, float | None],
) -> tuple[dict[str, dict[str, str]], bool]:
    edits: dict[str, dict[str, str]] = {}
    for key, value in lattice.items():
        if value is None:
            continue
        tag = _CELL_TAGS[key]
        previous = _required_cif_value(block, tag)
        formatted = format(float(value), ".10g")
        block.set_pair(tag, formatted)
        edits[key] = {"from": previous, "to": formatted}
    return edits, bool(edits)


def _loop_tags(block: gemmi.cif.Block) -> list[str]:
    column = block.find_loop("_atom_site_label")
    if len(column) == 0:
        raise ValueError("CIF has no atom-site loop.")
    loop = column.get_loop()
    tags = [str(tag) for tag in loop.tags]
    if any(not tag.startswith("_atom_site_") for tag in tags):
        raise ValueError("CIF atom-site loop contains an unexpected column.")
    return tags


def _output_tags(tags: list[str]) -> list[str]:
    output = list(tags)
    if "_atom_site_label" not in output:
        raise ValueError("CIF atom-site loop has no _atom_site_label column.")
    for axis in _FRACT_KEYS:
        if f"_atom_site_fract_{axis}" not in output:
            raise ValueError(f"CIF atom-site loop has no _atom_site_fract_{axis} column.")
    if "_atom_site_type_symbol" not in output:
        output.insert(output.index("_atom_site_label") + 1, "_atom_site_type_symbol")
    if "_atom_site_occupancy" not in output:
        output.append("_atom_site_occupancy")
    return output


def _site_groups(block: gemmi.cif.Block) -> list[_SiteGroup]:
    tags = _loop_tags(block)
    column = block.find_loop("_atom_site_label")
    loop = column.get_loop()
    grouped: dict[tuple[float, float, float], _SiteGroup] = {}
    order: list[tuple[float, float, float]] = []
    for index in range(loop.length()):
        raw = {tag: _clean_cif(loop[index, position]) for position, tag in enumerate(tags)}
        element = _element_from_row(raw)
        fract = {axis: raw.get(f"_atom_site_fract_{axis}", "") for axis in _FRACT_KEYS}
        values = {axis: _parse_float(fract[axis]) for axis in _FRACT_KEYS}
        key = tuple(round(values[axis], 4) for axis in _FRACT_KEYS)
        group = grouped.get(key)
        if group is None:
            group = _SiteGroup("metal", [], (), fract, values)
            grouped[key] = group
            order.append(key)
        group.rows.append({**raw, "_parsed_element": element})
    groups: list[_SiteGroup] = []
    for key in order:
        group = grouped[key]
        elements = tuple(dict.fromkeys(row["_parsed_element"] for row in group.rows))
        interstitial = set(elements) <= _INTERSTITIALS
        mixed = bool(set(elements) & _INTERSTITIALS) and not interstitial
        if mixed:
            raise ValueError(
                "A coordinate group mixes metal and interstitial atoms. "
                "adapt leaves interstitial clusters unchanged and will not guess which rows to replace."
            )
        group.kind = "interstitial" if interstitial else "metal"
        group.elements = elements
        groups.append(group)
    return groups


def _element_from_row(row: Mapping[str, str]) -> str:
    token = row.get("_atom_site_type_symbol") or row.get("_atom_site_label") or ""
    match = re.match(r"([A-Z][a-z]?)", token.strip())
    if match is None:
        raise ValueError(f"Cannot read an element symbol from {token!r}.")
    symbol = normalize_element(match.group(1))
    if symbol is None:
        raise ValueError(f"Unrecognized element symbol in {token!r}.")
    return symbol


def _require_unique_coordinates(groups: Sequence[_SiteGroup], coordinates: Mapping[str, float]) -> None:
    for axis in coordinates:
        seen = {format(group.values[axis], ".6f") for group in groups}
        if len(seen) > 1:
            raise ValueError(
                f"Metal sites do not share one fractional {axis}. "
                "Pass a CIF where that coordinate is already the same on every metal site."
            )


def _composition_rows(
    groups: Sequence[_SiteGroup],
    tags: Sequence[str],
    occupancies: Mapping[str, Decimal],
    coordinates: Mapping[str, float],
) -> tuple[list[list[str]], list[str]]:
    rows: list[list[str]] = []
    labels: set[str] = set()
    interstitials: list[str] = []
    site_index = 0
    for group in groups:
        if group.kind == "interstitial":
            for source in group.rows:
                values = {tag: source.get(tag, "") for tag in tags}
                if not values.get("_atom_site_type_symbol"):
                    values["_atom_site_type_symbol"] = source["_parsed_element"]
                if not values.get("_atom_site_occupancy"):
                    values["_atom_site_occupancy"] = "1"
                label = values.get("_atom_site_label", "")
                if label in labels:
                    raise ValueError(f"Adapted CIF would repeat atom label {label}.")
                labels.add(label)
                element = source["_parsed_element"]
                if element not in interstitials:
                    interstitials.append(element)
                rows.append([values[tag] for tag in tags])
            continue
        _require_full_metal_occupancy(group)
        site_index += 1
        for element, occupancy in occupancies.items():
            source = group.rows[0]
            values = {tag: source.get(tag, "") for tag in tags}
            label = f"{element}{site_index}"
            if label in labels:
                raise ValueError(f"Adapted CIF would repeat atom label {label}.")
            labels.add(label)
            values["_atom_site_label"] = label
            values["_atom_site_type_symbol"] = element
            values["_atom_site_occupancy"] = _occupancy_token(occupancy)
            for axis in _FRACT_KEYS:
                if axis in coordinates:
                    values[f"_atom_site_fract_{axis}"] = format(coordinates[axis], ".10g")
                else:
                    values[f"_atom_site_fract_{axis}"] = group.fract[axis]
            rows.append([values[tag] for tag in tags])
    return rows, interstitials


def _require_full_metal_occupancy(group: _SiteGroup) -> None:
    if "_atom_site_occupancy" not in group.rows[0] and all(
        "_atom_site_occupancy" not in row for row in group.rows
    ):
        return
    total = sum(
        (_parse_decimal(row["_atom_site_occupancy"]) for row in group.rows if row.get("_atom_site_occupancy")),
        Decimal(0),
    )
    if abs(total - Decimal(1)) > _SITE_OCCUPANCY_TOLERANCE:
        raise ValueError(
            "A metal site occupancy does not sum to 1. "
            "adapt will not replace it with a fully occupied composition."
        )


def _update_formula_tags(
    block: gemmi.cif.Block,
    groups: Sequence[_SiteGroup],
    occupancies: Mapping[str, Decimal],
) -> None:
    small = gemmi.make_small_structure_from_block(block)
    totals: dict[str, Decimal] = {}
    for site in small.get_all_unit_cell_sites():
        element = site.element.name
        totals[element] = totals.get(element, Decimal(0)) + Decimal(str(site.occ))
    metal_count = sum((value for element, value in totals.items() if element not in _INTERSTITIALS), Decimal(0))
    formula_units = int(round(metal_count))
    if formula_units <= 0 or abs(metal_count - formula_units) > Decimal("0.0001"):
        raise ValueError("Expanded metal content must be a positive integer number of occupied sites.")
    totals = {element: value / Decimal(formula_units) for element, value in totals.items()}
    formula = " ".join(
        element if _occupancy_token(amount) == "1" else f"{element}{_occupancy_token(amount)}"
        for element, amount in totals.items()
    )
    quoted = _quote_cif(formula)
    for tag in (*_FORMULA_TAGS, "_chemical_formula_moiety"):
        if tag == "_chemical_formula_sum" or _has_cif_value(block, tag):
            block.set_pair(tag, quoted)
    block.set_pair("_cell_formula_units_Z", str(formula_units))
    mass = unit_cell_formula_weight_g_mol(small)
    if mass is not None:
        block.set_pair("_chemical_formula_weight", format(mass / formula_units, ".10g"))
    # Species and labels have changed; these derived source tables cannot be
    # inherited as if they described the new model.
    for item in list(block):
        tag = item.pair[0] if item.pair else item.loop.tags[0] if item.loop else ""
        if tag.startswith(("_atom_type_", "_atom_site_aniso_", "_geom_")):
            item.erase()
    block.set_pair("_audit_creation_method", gemmi.cif.quote("DiffractScout adapt: derived starting model; inherited publication and database fields describe the source scaffold."))


def _update_volume(block: gemmi.cif.Block) -> None:
    lengths = [_required_float(block, _CELL_TAGS[key]) for key in _LENGTH_KEYS]
    angles = [_required_float(block, _CELL_TAGS[key]) for key in _ANGLE_KEYS]
    try:
        volume = float(gemmi.UnitCell(*lengths, *angles).volume)
    except Exception as exc:
        raise ValueError(f"Edited unit cell is invalid: {exc}") from exc
    if not math.isfinite(volume) or volume <= 0:
        raise ValueError("Edited unit-cell volume is not positive.")
    block.set_pair("_cell_volume", format(volume, ".10g"))


def _prepend_comment(path: Path, citation: str) -> None:
    lines = [_ADAPT_COMMENT]
    if citation:
        lines.append(f"# DiffractScout adapt citation: {citation}")
    prefix = ("\n".join(lines) + "\n").encode("utf-8")
    path.write_bytes(prefix + path.read_bytes())


def _validated_structure(path: Path, *, expected_elements: set[str]):
    try:
        loaded = load_structure(path)
    except ValueError as exc:
        raise ValueError(f"Adapted CIF failed validation and was not written: {exc}") from exc
    crosscheck = str(loaded.source_metadata.get("symmetry_crosscheck") or "")
    if crosscheck != "match":
        detected = loaded.source_metadata.get("detected_space_group_symbol") or "unavailable"
        detected_number = loaded.source_metadata.get("detected_space_group_number")
        raise ValueError(
            "Adapted CIF failed the symmetry cross-check "
            f"({loaded.space_group_symbol} No. {loaded.space_group_number}; "
            f"spglib {detected} No. {detected_number}; status {crosscheck}). "
            "The output was not written."
        )
    unexpected = [item for item in loaded.warnings if not item.startswith(_PARTIAL_OCCUPANCY_WARNING)]
    if unexpected:
        raise ValueError(
            "Adapted CIF produced an unexpected structure warning: " + "; ".join(unexpected)
        )
    actual = {str(site.element.name) for site in loaded.small_structure.sites}
    if actual != expected_elements:
        raise ValueError(
            "Adapted CIF elements are "
            f"{', '.join(sorted(actual))}; expected {', '.join(sorted(expected_elements))}."
        )
    if not math.isfinite(float(loaded.small_structure.cell.volume)) or float(loaded.small_structure.cell.volume) <= 0:
        raise ValueError("Adapted CIF volume is not positive. The output was not written.")
    return loaded


def _template_map(
    templates: Mapping[str, str | Path] | None,
    template_args: Sequence[str] | None,
) -> dict[str, Path]:
    mapping = parse_template_assignments(template_args)
    for raw_phase, raw_path in dict(templates or {}).items():
        phase = canonical_phase(str(raw_phase))
        if phase in mapping:
            raise ValueError(f"Duplicate --template for {phase}.")
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Template CIF not found: {path}")
        mapping[phase] = path.resolve()
    return mapping


def _check_subsystem_cap(elements: Sequence[str], max_subsystems: int) -> None:
    if isinstance(max_subsystems, bool) or not isinstance(max_subsystems, int) or max_subsystems < 1:
        raise ValueError("--max-subsystems must be an integer of at least 1.")
    subsystem_count = (1 << len(set(elements))) - 1
    if subsystem_count > max_subsystems:
        chemsys = "-".join(sorted(elements))
        raise ValueError(
            f"{chemsys} expands to {subsystem_count} chemical-subsystem queries, "
            f"which is above --max-subsystems {max_subsystems}. "
            "fetch-prototypes does not apply an energy-above-hull filter."
        )


def _collect_candidates(provider: Any, elements: Sequence[str], max_subsystems: int) -> list[CandidateRecord]:
    systems = chemsys_subsystems(elements)
    if len(systems) > max_subsystems:
        raise ValueError(
            f"Refusing to query {len(systems)} chemical subsystems above the limit of {max_subsystems}."
        )
    found: dict[str, CandidateRecord] = {}
    for system in systems:
        for candidate in provider.search_subsystem(
            system,
            e_hull_max_eV_atom=None,
            exclude_deprecated=True,
        ):
            if candidate.material_id and candidate.material_id not in found:
                found[candidate.material_id] = candidate
    return list(found.values())


def _download_bytes(
    provider: Any,
    candidates: Sequence[CandidateRecord],
) -> dict[str, tuple[bytes | None, str]]:
    if not candidates:
        return {}
    with tempfile.TemporaryDirectory(prefix="diffractscout_fetch_") as temporary:
        artifacts = provider.download_candidates(
            list(candidates),
            Path(temporary),
            conventional_unit_cell=True,
            include_elasticity=False,
        )
        payloads: dict[str, tuple[bytes | None, str]] = {}
        for artifact in artifacts:
            data = None
            path = artifact.cif_path
            if artifact.status == "ok" and path is not None and Path(path).is_file():
                data = Path(path).read_bytes()
            error = artifact.error or "Materials Project did not return this structure."
            payloads[artifact.candidate.material_id] = (data, error)
        return payloads


def _store_bytes(
    data: bytes,
    destination: Path,
    *,
    phase: str,
    status: str,
    material_id: str,
    origin: str,
    space_group: str,
    formula: str,
    note: str,
    use_file_identity: bool,
) -> PrototypeRecord:
    with destination.open("xb") as handle:
        handle.write(data)
    declared, number, file_formula = _read_cif_identity(destination)
    if use_file_identity:
        space_group = space_group or number
        formula = formula or file_formula
    return PrototypeRecord(
        phase=phase,
        status=status,
        material_id=material_id,
        source=origin,
        space_group=space_group,
        declared_symmetry=declared,
        formula=formula,
        target_composition=False,
        cif_path=destination,
        note=_with_symmetry_note(note, declared),
    )


def _missing_record(phase: str, note: str) -> PrototypeRecord:
    return PrototypeRecord(phase=phase, status="missing", target_composition=False, note=note)


def _download_note(candidate: CandidateRecord, host: str) -> str:
    present = formula_elements(candidate.formula)
    prefix = ""
    if present == (host,):
        prefix = f"Elemental {host} prototype in space group {candidate.space_group_number}. "
    return (
        prefix
        + f"Symmetry prototype for host {host}. "
        + "The composition and lattice are the database record, not the requested alloy."
    )


def _scaffold_note(*, searched: bool) -> str:
    if searched:
        prefix = "No eligible Cmcm (63) candidate contained the host element. "
    else:
        prefix = "Materials Project was not queried. "
    return prefix + _SCAFFOLD_NOTE


def _with_symmetry_note(note: str, declared: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9-]+", "", declared.replace("−", "-")).lower()
    if compact == "p1":
        suffix = (
            " Declared symmetry is P1. adapt requires a CIF whose Hermann-Mauguin "
            "symbol already describes the structure. Pass that file with --template."
        )
    elif not declared:
        suffix = " No Hermann-Mauguin symbol was declared."
    else:
        suffix = ""
    return (note + suffix).strip()


def _read_bytes(source: Any) -> bytes:
    reader = getattr(source, "read_bytes", None)
    if reader is None:
        return Path(source).read_bytes()
    return reader()


def _read_cif_identity(path: Path) -> tuple[str, str, str]:
    try:
        document = gemmi.cif.read_file(str(path))
        block = select_structure_block(document)
    except Exception:
        return "", "", ""
    return _hm_symbol(block), _it_number(block), _formula_text(block)


def _hm_symbol(block: gemmi.cif.Block) -> str:
    for tag in (
        "_symmetry_space_group_name_H-M",
        "_space_group_name_H-M_alt",
        "_symmetry_space_group_name_Hall",
    ):
        if _has_cif_value(block, tag):
            return _clean_cif(block.find_value(tag))
    return ""


def _it_number(block: gemmi.cif.Block) -> str:
    for tag in ("_space_group_IT_number", "_symmetry_Int_Tables_number"):
        if _has_cif_value(block, tag):
            return _clean_cif(block.find_value(tag)).split("(", 1)[0].strip()
    return ""


def _formula_text(block: gemmi.cif.Block) -> str:
    for tag in ("_chemical_formula_sum", "_chemical_formula_structural"):
        if _has_cif_value(block, tag):
            return _clean_cif(block.find_value(tag))
    return ""


def _write_index(path: Path, records: Sequence[PrototypeRecord]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_INDEX_FIELDS, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "phase": record.phase,
                    "status": record.status,
                    "material_id": record.material_id,
                    "source": record.source,
                    "space_group": record.space_group,
                    "declared_symmetry": record.declared_symmetry,
                    "formula": record.formula,
                    "target_composition": str(record.target_composition).lower(),
                    "cif": record.cif_path.name if record.cif_path is not None else "",
                    "note": record.note,
                }
            )


def _reject_existing_outputs(output_dir: Path, phases: Sequence[str]) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"Output path is not a directory: {output_dir}")
    if not output_dir.exists():
        return
    index_path = output_dir / "prototype_index.csv"
    if index_path.exists():
        raise FileExistsError(f"Refusing to overwrite {index_path}.")
    for phase in phases:
        path = output_dir / PHASE_RULES[phase].filename
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}.")


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    import json

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _clean_cif(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip().strip("'\"")


def _has_cif_value(block: gemmi.cif.Block, tag: str) -> bool:
    return _clean_cif(block.find_value(tag)) not in {"", "?", "."}


def _required_cif_value(block: gemmi.cif.Block, tag: str) -> str:
    if not _has_cif_value(block, tag):
        raise ValueError(f"CIF is missing {tag}.")
    return _clean_cif(block.find_value(tag))


def _required_float(block: gemmi.cif.Block, tag: str) -> float:
    return _parse_float(_required_cif_value(block, tag))


def _parse_float(token: str) -> float:
    text = _clean_cif(token).split("(", 1)[0].strip()
    if text in {"", "?", "."}:
        raise ValueError(f"CIF number is missing: {token!r}.")
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?/[+-]?\d+(?:\.\d+)?", text):
        numerator, denominator = text.split("/", 1)
        value = float(numerator) / float(denominator)
    else:
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError(f"CIF number is not numeric: {token!r}.") from exc
    if not math.isfinite(value):
        raise ValueError(f"CIF number is not finite: {token!r}.")
    return value


def _parse_decimal(token: str) -> Decimal:
    text = _clean_cif(token).split("(", 1)[0].strip()
    try:
        value = Decimal(text)
    except Exception as exc:
        raise ValueError(f"CIF occupancy is not numeric: {token!r}.") from exc
    if not value.is_finite() or value < 0 or value > 1:
        raise ValueError(f"CIF occupancy is outside [0, 1]: {token!r}.")
    return value


def _quote_cif(value: str) -> str:
    if value and re.fullmatch(r"[A-Za-z0-9_./+\-]+", value):
        return value
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    raise ValueError("CIF text contains both quote characters.")


def _erase_pair(block: gemmi.cif.Block, tag: str) -> None:
    if not _has_cif_value(block, tag):
        return
    block.find_pair_item(tag).erase()
