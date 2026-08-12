"""Elastic-tensor validation and hkl-normal Young's modulus calculations."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable

import gemmi
import numpy as np

from .models import ElasticTensor

MP_IEEE_CONVENTIONAL_FRAME = "materials_project_ieee_conventional"
MP_CONVENTIONAL_CIF_FRAME = "materials_project_conventional_cif_cartesian"
CIF_CARTESIAN_FRAME = "crystal_cartesian_from_cif_lattice"
SUPPORTED_DIRECTIONAL_FRAMES = frozenset(
    {CIF_CARTESIAN_FRAME, MP_CONVENTIONAL_CIF_FRAME}
)

_STIFFNESS_TO_GPA = {
    "pa": 1e-9,
    "kpa": 1e-6,
    "mpa": 1e-3,
    "gpa": 1.0,
    "tpa": 1e3,
}


def _as_6x6(values: object) -> np.ndarray | None:
    if values is None:
        return None
    try:
        matrix = np.asarray(values, dtype=float)
    except (TypeError, ValueError):
        return None
    return matrix if matrix.shape == (6, 6) else None


def validate_elastic_tensor(
    matrix_GPa: Iterable[Iterable[object]] | np.ndarray,
    *,
    source_provider: str = "",
    source_record_id: str = "",
    source_url: str = "",
    methodology_url: str = "",
    nature_of_data: str = "",
    coordinate_frame: str = CIF_CARTESIAN_FRAME,
    raw_payload_path: Path | None = None,
) -> ElasticTensor:
    warnings: list[str] = []
    matrix = _as_6x6(matrix_GPa)
    if matrix is None:
        return ElasticTensor(
            stiffness_GPa=np.empty((0, 0)),
            source_provider=source_provider,
            source_record_id=source_record_id,
            source_url=source_url,
            methodology_url=methodology_url,
            nature_of_data=nature_of_data,
            coordinate_frame=coordinate_frame,
            status="invalid",
            warnings=["Elastic stiffness tensor must be a finite 6x6 matrix in GPa."],
            raw_payload_path=raw_payload_path,
        )
    if not np.all(np.isfinite(matrix)):
        return ElasticTensor(
            stiffness_GPa=matrix,
            source_provider=source_provider,
            source_record_id=source_record_id,
            source_url=source_url,
            methodology_url=methodology_url,
            nature_of_data=nature_of_data,
            coordinate_frame=coordinate_frame,
            status="invalid",
            warnings=["Elastic stiffness tensor contains non-finite values."],
            raw_payload_path=raw_payload_path,
        )
    if not np.allclose(matrix, matrix.T, rtol=1e-6, atol=1e-8):
        warnings.append("Cij was not symmetric within tolerance; the exported tensor uses (C + C^T)/2.")
        matrix = 0.5 * (matrix + matrix.T)
    try:
        condition_number = float(np.linalg.cond(matrix))
        _ = np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return ElasticTensor(
            stiffness_GPa=matrix,
            source_provider=source_provider,
            source_record_id=source_record_id,
            source_url=source_url,
            methodology_url=methodology_url,
            nature_of_data=nature_of_data,
            coordinate_frame=coordinate_frame,
            status="invalid",
            warnings=[*warnings, "Cij is singular and cannot be inverted."],
            raw_payload_path=raw_payload_path,
        )
    eigenvalues = np.linalg.eigvalsh(matrix)
    if float(np.min(eigenvalues)) <= 0:
        return ElasticTensor(
            stiffness_GPa=matrix,
            source_provider=source_provider,
            source_record_id=source_record_id,
            source_url=source_url,
            methodology_url=methodology_url,
            nature_of_data=nature_of_data,
            coordinate_frame=coordinate_frame,
            status="invalid",
            warnings=[*warnings, "Cij is not positive definite."],
            raw_payload_path=raw_payload_path,
        )
    if condition_number > 1e10:
        warnings.append(f"Cij has a high condition number ({condition_number:.3g}).")
    if nature_of_data.lower().startswith("dft") or source_provider.lower() == "materials project":
        warnings.append("Elastic constants are DFT-derived and are not experimental handbook values.")
    if coordinate_frame not in SUPPORTED_DIRECTIONAL_FRAMES:
        warnings.append(
            "The tensor coordinate frame is not directly coupled to the CIF Cartesian frame; "
            "hkl-normal modulus output is disabled until an explicit rotation is supplied."
        )
    status = "valid_with_warnings" if warnings else "valid"
    return ElasticTensor(
        stiffness_GPa=matrix,
        source_provider=source_provider,
        source_record_id=source_record_id,
        source_url=source_url,
        methodology_url=methodology_url,
        nature_of_data=nature_of_data,
        coordinate_frame=coordinate_frame,
        status=status,
        warnings=warnings,
        raw_payload_path=raw_payload_path,
    )


def reciprocal_plane_normal(cell: gemmi.UnitCell, hkl: Iterable[int]) -> np.ndarray | None:
    h, k, l = (int(value) for value in hkl)
    if h == k == l == 0:
        return None
    vector = cell.reciprocal().orthogonalize(gemmi.Fractional(h, k, l))
    direction = np.asarray([vector.x, vector.y, vector.z], dtype=float)
    norm = float(np.linalg.norm(direction))
    if not np.isfinite(norm) or norm <= 0:
        return None
    return direction / norm


def young_modulus_hkl_normal_GPa(
    tensor: ElasticTensor,
    cell: gemmi.UnitCell,
    hkl: Iterable[int],
) -> float | None:
    if tensor.coordinate_frame not in SUPPORTED_DIRECTIONAL_FRAMES:
        return None
    compliance = tensor.compliance_1_over_GPa
    if compliance is None:
        return None
    direction = reciprocal_plane_normal(cell, hkl)
    if direction is None:
        return None
    l_dir, m_dir, n_dir = (float(value) for value in direction)
    # Voigt convention: [11, 22, 33, 23, 13, 12] with engineering shear strain.
    stress_direction = np.asarray(
        [
            l_dir * l_dir,
            m_dir * m_dir,
            n_dir * n_dir,
            m_dir * n_dir,
            l_dir * n_dir,
            l_dir * m_dir,
        ],
        dtype=float,
    )
    inverse_modulus = float(stress_direction @ compliance @ stress_direction)
    if not np.isfinite(inverse_modulus) or inverse_modulus <= 0:
        return None
    return float(1.0 / inverse_modulus)


def _normalized_unit(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s_\-]+", "", text)


def _declared_stiffness_unit(payload: dict[str, Any], tensor_block: dict[str, Any] | None = None) -> str:
    """Return the best available declared stiffness unit.

    Explicit ``*_GPa`` fields are handled separately and do not call this
    helper. Generic tensor fields must carry a recognized unit or use the
    documented legacy assumption with a warning.
    """

    if tensor_block is not None:
        for key in ("unit", "units", "stiffness_unit", "elastic_tensor_unit"):
            value = tensor_block.get(key)
            if isinstance(value, str) and value.strip():
                return value
    units = payload.get("units")
    if isinstance(units, dict):
        for key in ("elastic_tensor", "stiffness", "cij", "Cij"):
            value = units.get(key)
            if isinstance(value, str) and value.strip():
                return value
    for key in ("unit", "stiffness_unit", "elastic_tensor_unit", "cij_unit"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _matrix_in_gpa(
    matrix: np.ndarray,
    unit: str,
    *,
    warnings: list[str],
) -> np.ndarray:
    normalized = _normalized_unit(unit)
    if not normalized:
        warnings.append(
            "No stiffness unit was declared for a generic tensor field; GPa was assumed for legacy compatibility."
        )
        normalized = "gpa"
    factor = _STIFFNESS_TO_GPA.get(normalized)
    if factor is None:
        supported = ", ".join(("Pa", "kPa", "MPa", "GPa", "TPa"))
        raise ValueError(
            f"Unsupported elastic stiffness unit {unit!r}; supported units are {supported}."
        )
    if factor != 1.0:
        warnings.append(f"Converted elastic stiffness from {unit} to GPa.")
    return np.asarray(matrix, dtype=float) * factor


def _matrix_from_payload(payload: dict[str, Any]) -> tuple[np.ndarray | None, str, list[str]]:
    warnings: list[str] = []
    for key in ("stiffness_GPa", "cij_GPa"):
        matrix = _as_6x6(payload.get(key))
        if matrix is not None:
            return matrix, key, warnings
    downstream = payload.get("cif2peaks") or payload.get("diffractscout")
    if isinstance(downstream, dict):
        matrix = _as_6x6(downstream.get("stiffness_GPa"))
        if matrix is not None:
            return matrix, f"{('cif2peaks' if 'cif2peaks' in payload else 'diffractscout')}.stiffness_GPa", warnings
    tensor = payload.get("elastic_tensor")
    if isinstance(tensor, dict):
        matrix = _as_6x6(tensor.get("ieee_format"))
        if matrix is not None:
            return (
                _matrix_in_gpa(
                    matrix,
                    _declared_stiffness_unit(payload, tensor),
                    warnings=warnings,
                ),
                "elastic_tensor.ieee_format",
                warnings,
            )
        matrix = _as_6x6(tensor.get("raw"))
        if matrix is not None:
            warnings.append("Using elastic_tensor.raw because ieee_format is unavailable; verify orientation against the CIF.")
            return (
                _matrix_in_gpa(
                    matrix,
                    _declared_stiffness_unit(payload, tensor),
                    warnings=warnings,
                ),
                "elastic_tensor.raw",
                warnings,
            )
    elif tensor is not None:
        matrix = _as_6x6(tensor)
        if matrix is not None:
            return (
                _matrix_in_gpa(
                    matrix,
                    _declared_stiffness_unit(payload),
                    warnings=warnings,
                ),
                "elastic_tensor",
                warnings,
            )
    for key in ("stiffness", "cij", "Cij"):
        matrix = _as_6x6(payload.get(key))
        if matrix is not None:
            return (
                _matrix_in_gpa(
                    matrix,
                    _declared_stiffness_unit(payload),
                    warnings=warnings,
                ),
                key,
                warnings,
            )
    if any(f"C{i}{j}_GPa" in payload for i in range(1, 7) for j in range(1, 7)):
        try:
            matrix = np.asarray(
                [[float(payload[f"C{i}{j}_GPa"]) for j in range(1, 7)] for i in range(1, 7)],
                dtype=float,
            )
            return matrix, "flat_Cij_GPa", warnings
        except (KeyError, TypeError, ValueError):
            pass
    return None, "", warnings


def elastic_tensor_from_payload(payload: dict[str, Any], *, path: Path | None = None) -> ElasticTensor | None:
    status = str(payload.get("status") or "").strip().lower()
    if status and status not in {
        "ok",
        "valid",
        "valid_with_warnings",
        "frame_transform_required",
    }:
        return None
    provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    if provenance.get("numerical_cij") is False:
        return None
    try:
        matrix, basis, warnings = _matrix_from_payload(payload)
    except ValueError as exc:
        return _invalid_tensor(str(exc), path=path)
    if matrix is None:
        return None

    provider = str(provenance.get("provider") or payload.get("source_provider") or payload.get("source") or "")
    record_id = str(payload.get("material_id") or provenance.get("material_id") or payload.get("source_record_id") or "")
    material_url = str(provenance.get("mp_material_url") or provenance.get("source_url") or payload.get("source_url") or "")
    methodology = str(provenance.get("methodology_url") or payload.get("methodology_url") or "")
    nature = str(provenance.get("nature_of_data") or payload.get("nature_of_data") or "")

    downstream = payload.get("diffractscout") or payload.get("cif2peaks")
    coordinate_frame = ""
    if isinstance(downstream, dict):
        coordinate_frame = str(downstream.get("coordinate_frame") or "")
    coordinate_frame = coordinate_frame or str(provenance.get("coordinate_frame") or payload.get("coordinate_frame") or "")
    if not coordinate_frame:
        if "ieee" in basis:
            coordinate_frame = MP_IEEE_CONVENTIONAL_FRAME
        elif provider.lower() == "materials project" and "raw" in basis:
            coordinate_frame = MP_CONVENTIONAL_CIF_FRAME
        else:
            coordinate_frame = CIF_CARTESIAN_FRAME

    tensor = validate_elastic_tensor(
        matrix,
        source_provider=provider,
        source_record_id=record_id,
        source_url=material_url,
        methodology_url=methodology,
        nature_of_data=nature,
        coordinate_frame=coordinate_frame,
        raw_payload_path=path,
    )
    if warnings:
        tensor.warnings = [*warnings, *tensor.warnings]
        if tensor.status == "valid":
            tensor.status = "valid_with_warnings"
    if status == "frame_transform_required":
        tensor.warnings = [
            "A numerical tensor is present, but a coordinate rotation is required before "
            "hkl-resolved properties can be evaluated.",
            *tensor.warnings,
        ]
        tensor.status = "valid_with_warnings"
    return tensor


def _invalid_tensor(message: str, *, path: Path | None = None) -> ElasticTensor:
    return ElasticTensor(
        stiffness_GPa=np.empty((0, 0)),
        status="invalid",
        warnings=[message],
        raw_payload_path=path,
    )


def _read_payload(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return None, f"Could not read elasticity sidecar {path.name}: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"Elasticity sidecar {path.name} is not valid JSON: {exc}"
    if not isinstance(decoded, dict):
        return None, f"Elasticity sidecar {path.name} must contain a JSON object."
    return decoded, ""


def load_elastic_tensor(path: str | Path) -> ElasticTensor | None:
    source = Path(path)
    payload, _error = _read_payload(source)
    return elastic_tensor_from_payload(payload, path=source) if payload is not None else None


def _declared_pair_names(payload: dict[str, Any]) -> set[str]:
    names = {
        str(payload.get("cif_filename") or "").strip().lower(),
        str(payload.get("paired_cif") or "").strip().lower(),
    }
    provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    names.add(str(provenance.get("paired_cif") or "").strip().lower())
    for key in ("cif2peaks", "diffractscout"):
        block = payload.get(key)
        if isinstance(block, dict):
            names.add(str(block.get("paired_cif") or "").strip().lower())
    names.discard("")
    return names


def _declared_material_id(payload: dict[str, Any]) -> str:
    provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    return str(payload.get("material_id") or provenance.get("material_id") or "").strip().lower()


def _cif_material_id(cif_path: Path) -> str:
    match = re.search(r"(mp-\d+)", cif_path.name, flags=re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _payload_pairing(payload: dict[str, Any], cif_path: Path) -> tuple[bool, bool, str]:
    """Return matched, has-explicit-pairing, and a human-readable mismatch reason."""

    names = _declared_pair_names(payload)
    payload_id = _declared_material_id(payload)
    cif_id = _cif_material_id(cif_path)
    has_explicit = bool(names or payload_id)
    name_match = cif_path.name.lower() in names if names else False
    id_match = bool(payload_id and cif_id and payload_id == cif_id)
    if name_match or id_match:
        return True, has_explicit, ""
    if names:
        return False, True, (
            f"Elasticity sidecar declares paired CIF(s) {sorted(names)!r}, "
            f"which do not match {cif_path.name!r}."
        )
    if payload_id and cif_id and payload_id != cif_id:
        return False, True, (
            f"Elasticity sidecar material_id {payload_id!r} does not match "
            f"the CIF identifier {cif_id!r}."
        )
    if payload_id and not cif_id:
        return False, True, (
            f"Elasticity sidecar declares material_id {payload_id!r}, while "
            f"{cif_path.name!r} has no verifiable Materials Project identifier."
        )
    return False, has_explicit, ""


def _match_payload_to_cif(payload: dict[str, Any], cif_path: Path) -> bool:
    matched, _explicit, _reason = _payload_pairing(payload, cif_path)
    return matched


def _load_from_index(index_path: Path, cif_path: Path) -> ElasticTensor | None:
    if not index_path.is_file():
        return None
    try:
        with index_path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        return _invalid_tensor(f"Could not read elasticity index {index_path.name}: {exc}", path=index_path)
    matches = [
        row
        for row in rows
        if cif_path.name.lower()
        in {
            str(row.get("cif_filename") or "").strip().lower(),
            str(row.get("paired_cif") or "").strip().lower(),
        }
    ]
    if len(matches) > 1:
        return _invalid_tensor(
            f"Elasticity index {index_path.name} contains {len(matches)} rows for {cif_path.name}; "
            "the pairing is ambiguous.",
            path=index_path,
        )
    if not matches:
        return None
    row = matches[0]
    status = str(row.get("status") or "").strip().lower()
    numerical = str(row.get("numerical_cij") or "").strip().lower()
    if status and status not in {"ok", "valid", "valid_with_warnings"}:
        return None
    if numerical in {"false", "0", "no"}:
        return None
    matrix = _as_6x6([[row.get(f"C{i}{j}_GPa", "") for j in range(1, 7)] for i in range(1, 7)])
    if matrix is None:
        return _invalid_tensor(
            f"Elasticity index row for {cif_path.name} does not contain a complete numeric 6x6 tensor.",
            path=index_path,
        )
    return validate_elastic_tensor(
        matrix,
        source_provider=str(row.get("provider") or "Materials Project"),
        source_record_id=str(row.get("material_id") or ""),
        source_url=str(row.get("mp_material_url") or row.get("source_url") or ""),
        methodology_url=str(row.get("methodology_url") or ""),
        nature_of_data=str(row.get("nature_of_data") or ""),
        coordinate_frame=str(row.get("coordinate_frame") or MP_IEEE_CONVENTIONAL_FRAME),
        raw_payload_path=index_path,
    )


def discover_elastic_tensor(cif_path: str | Path) -> ElasticTensor | None:
    path = Path(cif_path).expanduser().resolve()
    exact = path.with_name(f"{path.stem}_elasticity.json")
    if exact.is_file():
        payload, error = _read_payload(exact)
        if payload is None:
            return _invalid_tensor(error, path=exact)
        matched, explicit, reason = _payload_pairing(payload, path)
        if explicit and not matched:
            return _invalid_tensor(reason, path=exact)
        tensor = elastic_tensor_from_payload(payload, path=exact)
        if tensor is not None:
            return tensor
        status = str(payload.get("status") or "").strip().lower()
        provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
        if provenance.get("numerical_cij") is False or status in {
            "no_elasticity_data",
            "no_elastic_tensor",
            "elasticity_query_failed",
            "not_available",
        }:
            return None
        return _invalid_tensor(
            f"Elasticity sidecar {exact.name} does not contain a usable numeric 6x6 tensor.",
            path=exact,
        )

    matched: list[tuple[Path, dict[str, Any]]] = []
    for candidate in sorted(path.parent.glob("*_elasticity.json")):
        payload, _error = _read_payload(candidate)
        if payload is not None and _match_payload_to_cif(payload, path):
            matched.append((candidate, payload))
    if len(matched) > 1:
        return _invalid_tensor(
            f"Found {len(matched)} elasticity sidecars matching {path.name}; pairing is ambiguous: "
            + ", ".join(item[0].name for item in matched),
            path=None,
        )
    if len(matched) == 1:
        candidate, payload = matched[0]
        tensor = elastic_tensor_from_payload(payload, path=candidate)
        if tensor is not None:
            return tensor
        return _invalid_tensor(
            f"Matched elasticity sidecar {candidate.name} does not contain a usable numeric 6x6 tensor.",
            path=candidate,
        )

    for name in ("elasticity_index.csv", "diffractscout_elasticity.csv"):
        tensor = _load_from_index(path.parent / name, path)
        if tensor is not None:
            return tensor
    return None
