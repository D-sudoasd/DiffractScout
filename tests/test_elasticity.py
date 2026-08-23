import csv
from pathlib import Path
import shutil

import numpy as np
import pytest
import gemmi

from diffractscout.elasticity import (
    CIF_CARTESIAN_FRAME,
    MP_IEEE_CONVENTIONAL_FRAME,
    SUPPORTED_DIRECTIONAL_FRAMES,
    discover_elastic_tensor,
    elastic_tensor_from_payload,
    reciprocal_plane_normal,
    validate_elastic_tensor,
    young_modulus_hkl_normal_GPa,
)
from diffractscout.structure import load_structure


def test_reciprocal_plane_normal_uses_direct_monoclinic_cif_basis() -> None:
    normal = reciprocal_plane_normal(gemmi.UnitCell(3, 4, 5, 90, 110, 90), (1, 0, 0))
    assert normal is not None
    assert normal == pytest.approx([0.93969262, 0.0, 0.34202014], abs=1e-8)


def test_reciprocal_plane_normal_uses_direct_hexagonal_cif_basis() -> None:
    cell = gemmi.UnitCell(3, 3, 5, 90, 90, 120)
    first = reciprocal_plane_normal(cell, (1, 0, 0))
    mixed = reciprocal_plane_normal(cell, (1, 1, 0))
    assert first is not None and mixed is not None
    assert first == pytest.approx([0.8660254, 0.5, 0.0], abs=1e-8)
    assert mixed == pytest.approx([0.5, 0.8660254, 0.0], abs=1e-8)


def test_anisotropic_modulus_uses_corrected_monoclinic_normal() -> None:
    cell = gemmi.UnitCell(3, 4, 5, 90, 110, 90)
    matrix = np.diag([200.0, 100.0, 50.0, 80.0, 80.0, 80.0])
    tensor = validate_elastic_tensor(matrix)
    modulus = young_modulus_hkl_normal_GPa(tensor, cell, (1, 0, 0))
    assert modulus is not None
    # Independent reference uses the rounded direct-basis normal documented
    # by the monoclinic geometry, rather than reusing production geometry code.
    assert modulus == pytest.approx(183.033125647, rel=1e-8)


def test_isotropic_fixture_has_direction_independent_modulus(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    tensor = discover_elastic_tensor(structure.cif_path)
    assert tensor is not None
    values = [
        young_modulus_hkl_normal_GPa(tensor, structure.small_structure.cell, hkl)
        for hkl in ((1, 0, 0), (1, 1, 1), (1, 2, 3))
    ]
    assert values == pytest.approx([110.0, 110.0, 110.0], rel=1e-12)


def test_invalid_tensor_is_rejected() -> None:
    tensor = validate_elastic_tensor(np.zeros((6, 6)))
    assert tensor.status == "invalid"
    assert tensor.compliance_1_over_GPa is None


def test_nonsymmetric_tensor_is_symmetrized() -> None:
    matrix = np.eye(6) * 100
    matrix[0, 1] = 20
    tensor = validate_elastic_tensor(matrix)
    assert tensor.status == "valid_with_warnings"
    assert tensor.stiffness_GPa[0, 1] == tensor.stiffness_GPa[1, 0] == 10


def test_unrotated_ieee_tensor_does_not_emit_hkl_modulus(demo_inputs: Path) -> None:
    structure = load_structure(demo_inputs / "synthetic_fcc_al.cif")
    matrix = np.eye(6) * 100.0
    tensor = validate_elastic_tensor(matrix, coordinate_frame=MP_IEEE_CONVENTIONAL_FRAME)
    assert tensor.status == "frame_transform_required"
    assert young_modulus_hkl_normal_GPa(tensor, structure.small_structure.cell, (1, 1, 1)) is None


def test_materials_project_raw_frame_is_not_a_supported_directional_frame() -> None:
    from diffractscout.elasticity import MP_CONVENTIONAL_CIF_FRAME

    assert MP_CONVENTIONAL_CIF_FRAME not in SUPPORTED_DIRECTIONAL_FRAMES


def test_generic_json_tensor_without_coordinate_frame_fails_closed_for_nonorthogonal_cell() -> None:
    matrix = np.diag([240.0, 150.0, 90.0, 70.0, 60.0, 50.0])
    tensor = elastic_tensor_from_payload(
        {"status": "ok", "stiffness": matrix.tolist(), "unit": "GPa"}
    )

    assert tensor is not None
    assert tensor.status == "frame_transform_required"
    assert tensor.coordinate_frame == ""
    assert young_modulus_hkl_normal_GPa(
        tensor, gemmi.UnitCell(3.0, 4.0, 5.0, 90.0, 110.0, 90.0), (1, 0, 0)
    ) is None


def test_generic_json_tensor_with_explicit_cif_frame_remains_usable() -> None:
    tensor = elastic_tensor_from_payload(
        {
            "status": "ok",
            "stiffness": (np.eye(6) * 100.0).tolist(),
            "unit": "GPa",
            "coordinate_frame": CIF_CARTESIAN_FRAME,
        }
    )

    assert tensor is not None
    assert tensor.status == "valid"


def test_index_frame_transform_required_preserves_numerical_tensor(
    demo_inputs: Path, tmp_path: Path
) -> None:
    cif = tmp_path / "mp-123_Al.cif"
    shutil.copy2(demo_inputs / "synthetic_fcc_al.cif", cif)
    index = tmp_path / "elasticity_index.csv"
    fields = [
        "cif_filename",
        "status",
        "numerical_cij",
        "provider",
        "material_id",
        "coordinate_frame",
        *[f"C{i}{j}_GPa" for i in range(1, 7) for j in range(1, 7)],
    ]
    row = {
        "cif_filename": cif.name,
        "status": "frame_transform_required",
        "numerical_cij": "true",
        "provider": "Materials Project",
        "material_id": "mp-123",
        "coordinate_frame": MP_IEEE_CONVENTIONAL_FRAME,
        **{f"C{i}{j}_GPa": "100" if i == j else "0" for i in range(1, 7) for j in range(1, 7)},
    }
    with index.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)

    structure = load_structure(cif)
    tensor = discover_elastic_tensor(cif)

    assert tensor is not None
    assert tensor.status == "frame_transform_required"
    assert tensor.coordinate_frame == MP_IEEE_CONVENTIONAL_FRAME
    assert tensor.source_record_id == "mp-123"
    assert tensor.raw_payload_path == index
    assert tensor.stiffness_GPa == pytest.approx(np.eye(6) * 100.0)
    assert young_modulus_hkl_normal_GPa(
        tensor, structure.small_structure.cell, (1, 1, 1)
    ) is None


@pytest.mark.parametrize("status", ["invalid", "elasticity_query_failed"])
def test_index_explicit_failure_status_returns_invalid_tensor(
    demo_inputs: Path, tmp_path: Path, status: str
) -> None:
    cif = tmp_path / "failed-index.cif"
    shutil.copy2(demo_inputs / "synthetic_fcc_al.cif", cif)
    index = tmp_path / "elasticity_index.csv"
    with index.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["cif_filename", "status", "error"])
        writer.writeheader()
        writer.writerow(
            {
                "cif_filename": cif.name,
                "status": status,
                "error": "provider-side elasticity failure",
            }
        )

    tensor = discover_elastic_tensor(cif)

    assert tensor is not None
    assert tensor.status == "invalid"
    assert tensor.raw_payload_path == index
    assert any("provider-side elasticity failure" in warning for warning in tensor.warnings)
    assert young_modulus_hkl_normal_GPa(
        tensor, load_structure(cif).small_structure.cell, (1, 1, 1)
    ) is None


def test_index_failure_for_unmatched_cif_does_not_create_invalid_tensor(
    demo_inputs: Path, tmp_path: Path
) -> None:
    cif = tmp_path / "unmatched.cif"
    shutil.copy2(demo_inputs / "synthetic_fcc_al.cif", cif)
    index = tmp_path / "elasticity_index.csv"
    with index.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["cif_filename", "status"])
        writer.writeheader()
        writer.writerow({"cif_filename": "other.cif", "status": "invalid"})

    assert discover_elastic_tensor(cif) is None


def test_exact_sidecar_with_conflicting_pair_is_rejected(demo_inputs: Path, tmp_path: Path) -> None:
    import json
    import shutil

    cif = tmp_path / "sample.cif"
    shutil.copy2(demo_inputs / "synthetic_fcc_al.cif", cif)
    payload = json.loads((demo_inputs / "synthetic_fcc_al_elasticity.json").read_text(encoding="utf-8"))
    payload["cif_filename"] = "different.cif"
    payload["provenance"]["paired_cif"] = "different.cif"
    (tmp_path / "sample_elasticity.json").write_text(json.dumps(payload), encoding="utf-8")
    tensor = discover_elastic_tensor(cif)
    assert tensor is not None
    assert tensor.status == "invalid"
    assert any("do not match" in warning for warning in tensor.warnings)


def test_exact_sidecar_with_conflicting_material_id_is_rejected(
    demo_inputs: Path, tmp_path: Path
) -> None:
    import json
    import shutil

    cif = tmp_path / "mp-123_Al.cif"
    shutil.copy2(demo_inputs / "synthetic_fcc_al.cif", cif)
    payload = json.loads(
        (demo_inputs / "synthetic_fcc_al_elasticity.json").read_text(encoding="utf-8")
    )
    payload["cif_filename"] = cif.name
    payload["provenance"]["paired_cif"] = cif.name
    payload["provenance"]["material_id"] = "mp-999"
    payload["diffractscout"]["paired_cif"] = cif.name
    (tmp_path / "mp-123_Al_elasticity.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    tensor = discover_elastic_tensor(cif)
    assert tensor is not None
    assert tensor.status == "invalid"
    assert any("material_id" in warning for warning in tensor.warnings)


def test_compliance_matrix_is_cached() -> None:
    tensor = validate_elastic_tensor(np.eye(6) * 100.0)
    first = tensor.compliance_1_over_GPa
    second = tensor.compliance_1_over_GPa
    assert first is second


def test_generic_mpa_tensor_is_converted_to_gpa() -> None:
    payload = {
        "status": "ok",
        "stiffness": (np.eye(6) * 100_000).tolist(),
        "unit": "MPa",
    }
    tensor = elastic_tensor_from_payload(payload)
    assert tensor is not None
    assert tensor.stiffness_GPa == pytest.approx(np.eye(6) * 100.0)
    assert tensor.status == "frame_transform_required"
    assert any("Converted elastic stiffness" in warning for warning in tensor.warnings)


def test_unknown_generic_tensor_unit_is_invalid() -> None:
    tensor = elastic_tensor_from_payload(
        {"status": "ok", "stiffness": np.eye(6).tolist(), "unit": "psi"}
    )
    assert tensor is not None
    assert tensor.status == "invalid"
    assert any("Unsupported elastic stiffness unit" in warning for warning in tensor.warnings)
