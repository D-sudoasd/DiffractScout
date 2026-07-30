from pathlib import Path

import numpy as np
import pytest

from diffractscout.elasticity import (
    MP_IEEE_CONVENTIONAL_FRAME,
    discover_elastic_tensor,
    validate_elastic_tensor,
    young_modulus_hkl_normal_GPa,
)
from diffractscout.structure import load_structure


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
    assert tensor.status == "valid_with_warnings"
    assert young_modulus_hkl_normal_GPa(tensor, structure.small_structure.cell, (1, 1, 1)) is None


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


def test_compliance_matrix_is_cached() -> None:
    tensor = validate_elastic_tensor(np.eye(6) * 100.0)
    first = tensor.compliance_1_over_GPa
    second = tensor.compliance_1_over_GPa
    assert first is second
