import numpy as np
import pytest

from diffractscout.elasticity_input import (
    format_cij_matrix,
    parse_cij_matrix_6x6,
    parse_cij_paste_text,
    parse_cubic_cij,
)


def test_parse_cubic_cij_builds_validated_matrix() -> None:
    tensor = parse_cubic_cij(200.0, 120.0, 40.0, source="handbook_cubic")
    assert tensor.source_provider == "user_input"
    assert tensor.status in {"valid", "valid_with_warnings"}
    expected = np.array(
        [
            [200.0, 120.0, 120.0, 0.0, 0.0, 0.0],
            [120.0, 200.0, 120.0, 0.0, 0.0, 0.0],
            [120.0, 120.0, 200.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 40.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 40.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 40.0],
        ]
    )
    assert tensor.stiffness_GPa == pytest.approx(expected)


def test_parse_cij_matrix_6x6_and_paste_roundtrip() -> None:
    matrix = parse_cij_paste_text(
        """
        200 120 120 0 0 0
        120 200 120 0 0 0
        120 120 200 0 0 0
        0 0 0 40 0 0
        0 0 0 0 40 0
        0 0 0 0 0 40
        """
    )
    assert len(matrix) == 6
    assert len(matrix[0]) == 6
    tensor = parse_cij_matrix_6x6(matrix)
    assert tensor.source_provider == "user_input"
    assert tensor.status in {"valid", "valid_with_warnings"}
    text = format_cij_matrix(tensor)
    assert "200" in text
    assert text.count("\n") == 5


def test_parse_cij_paste_text_rejects_wrong_count() -> None:
    with pytest.raises(ValueError, match="Expected 36"):
        parse_cij_paste_text("1 2 3")
