import json
from pathlib import Path

from diffractscout.elasticity import MP_CONVENTIONAL_CIF_FRAME, MP_IEEE_CONVENTIONAL_FRAME
from diffractscout.models import CandidateRecord
from diffractscout.providers.materials_project import (
    MaterialsProjectProvider,
    _candidate_filename,
    _candidate_from_doc,
    _matrix,
)


def _provider_without_client() -> MaterialsProjectProvider:
    return object.__new__(MaterialsProjectProvider)


def _candidate() -> CandidateRecord:
    return CandidateRecord(
        material_id="mp-123",
        formula="Al",
        source_provider="Materials Project",
        source_url="https://materialsproject.org/materials/mp-123",
    )


def _diagonal_matrix(value: float) -> list[list[float]]:
    return [[value if i == j else 0.0 for j in range(6)] for i in range(6)]


def test_materials_project_document_normalization() -> None:
    doc = {
        "material_id": "mp-123",
        "formula_pretty": "Ni3Al",
        "energy_above_hull": 0.01,
        "is_stable": False,
        "theoretical": True,
        "deprecated": False,
        "symmetry": {"symbol": "Pm-3m", "number": 221, "crystal_system": "Cubic"},
    }
    candidate = _candidate_from_doc(doc, "Al-Ni")
    assert candidate.material_id == "mp-123"
    assert candidate.structure_type == "L12"
    assert "mp-123" in _candidate_filename(candidate)
    assert "sg221" in _candidate_filename(candidate)


def test_matrix_conversion() -> None:
    matrix = [[float(i == j) for j in range(6)] for i in range(6)]
    assert _matrix(matrix) == matrix
    assert _matrix([[1, 2]]) is None


def test_elasticity_sidecar_prefers_raw_tensor_for_conventional_cif(tmp_path: Path) -> None:
    cif_path = tmp_path / "mp-123_Al.cif"
    cif_path.write_text("data_test\n", encoding="utf-8")
    raw = _diagonal_matrix(100.0)
    ieee = _diagonal_matrix(200.0)
    document = {
        "elastic_tensor": {"raw": raw, "ieee_format": ieee},
        "bulk_modulus": {"vrh": 50.0},
    }

    path = _provider_without_client()._write_elasticity(
        _candidate(), cif_path, document, conventional_unit_cell=True
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["status"] == "ok"
    assert payload["stiffness_GPa"] == raw
    assert payload["diffractscout"]["coordinate_frame"] == MP_CONVENTIONAL_CIF_FRAME
    assert payload["provenance"]["usable_for_hkl_modulus"] is True
    assert payload["elastic_tensor"]["ieee_format"] == ieee


def test_ieee_only_sidecar_requires_explicit_frame_transform(tmp_path: Path) -> None:
    cif_path = tmp_path / "mp-123_Al.cif"
    cif_path.write_text("data_test\n", encoding="utf-8")
    ieee = _diagonal_matrix(200.0)
    document = {"elastic_tensor": {"raw": None, "ieee_format": ieee}}

    path = _provider_without_client()._write_elasticity(
        _candidate(), cif_path, document, conventional_unit_cell=True
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["status"] == "frame_transform_required"
    assert "stiffness_GPa" not in payload
    assert payload["provenance"]["coordinate_frame"] == MP_IEEE_CONVENTIONAL_FRAME
    assert payload["provenance"]["usable_for_hkl_modulus"] is False
