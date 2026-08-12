"""Pure helpers for user-supplied elastic stiffness (Cij) tensors.

Ported from CIF2Peaks GUI parsing helpers without any Tk dependency.
All matrices are validated through :func:`validate_elastic_tensor`.
"""

from __future__ import annotations

import re
from typing import Iterable

import numpy as np

from .elasticity import validate_elastic_tensor
from .models import ElasticTensor

_SOURCE_PROVIDER = "user_input"
_TOKEN_SPLIT = re.compile(r"[\s,;|]+")


def parse_cubic_cij(
    c11: float,
    c12: float,
    c44: float,
    source: str = "",
) -> ElasticTensor:
    """Build a cubic Voigt stiffness matrix from C11, C12, C44 (GPa)."""

    c11_f = float(c11)
    c12_f = float(c12)
    c44_f = float(c44)
    matrix = [
        [c11_f, c12_f, c12_f, 0.0, 0.0, 0.0],
        [c12_f, c11_f, c12_f, 0.0, 0.0, 0.0],
        [c12_f, c12_f, c11_f, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, c44_f, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, c44_f, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, c44_f],
    ]
    return validate_elastic_tensor(
        matrix,
        source_provider=_SOURCE_PROVIDER,
        source_record_id=str(source or ""),
        nature_of_data=str(source or "user_input"),
    )


def parse_cij_matrix_6x6(
    values: Iterable[Iterable[object]] | np.ndarray,
) -> ElasticTensor:
    """Validate a full 6×6 Voigt stiffness matrix in GPa."""

    return validate_elastic_tensor(
        values,
        source_provider=_SOURCE_PROVIDER,
        nature_of_data="user_input",
    )


def parse_cij_paste_text(text: str) -> list[list[float]]:
    """Parse a pasted 6×6 Cij block into a nested list of floats.

    Accepts whitespace-, comma-, semicolon-, or pipe-separated tokens (36 values).
    """

    tokens = [token for token in _TOKEN_SPLIT.split(str(text).strip()) if token]
    if len(tokens) != 36:
        raise ValueError(
            f"Expected 36 numeric values for a 6x6 Cij matrix, got {len(tokens)}."
        )
    try:
        numbers = [float(token) for token in tokens]
    except ValueError as exc:
        raise ValueError("Cij paste text must contain only numeric values.") from exc
    return [numbers[row * 6 : (row + 1) * 6] for row in range(6)]


def format_cij_matrix(tensor: ElasticTensor) -> str:
    """Format a validated stiffness matrix as a readable 6-line string."""

    matrix = np.asarray(tensor.stiffness_GPa, dtype=float)
    if matrix.shape != (6, 6):
        raise ValueError("format_cij_matrix requires a 6x6 stiffness matrix.")
    lines: list[str] = []
    for row in matrix:
        lines.append("  ".join(f"{float(value):.6g}" for value in row))
    return "\n".join(lines)
