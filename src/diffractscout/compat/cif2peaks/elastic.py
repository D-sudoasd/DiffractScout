from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

from .hkl import plane_hkl_for_normal


ElasticStatus = str
DEFAULT_ELASTIC_COORDINATE_FRAME = "crystal_cartesian_from_cif_lattice"
# PhaseScout / Materials Project IEEE tensors with conventional-cell CIFs
MATERIALS_PROJECT_IEEE_CONVENTIONAL_FRAME = "materials_project_ieee_conventional"


def _as_stiffness_matrix(values: Iterable[Iterable[object]]) -> np.ndarray:
    matrix = np.asarray([[float(value) for value in row] for row in values], dtype=float)
    if matrix.shape != (6, 6):
        raise ValueError(f"Cij matrix must be 6x6, got {matrix.shape}.")
    return matrix


def hkl_normal_direction(lattice: Any, hkl: Iterable[object]) -> np.ndarray | None:
    h, k, ell = plane_hkl_for_normal(hkl)
    reciprocal_matrix = np.asarray(lattice.reciprocal_lattice.matrix, dtype=float)
    normal = h * reciprocal_matrix[0] + k * reciprocal_matrix[1] + ell * reciprocal_matrix[2]
    norm = float(np.linalg.norm(normal))
    if not np.isfinite(norm) or norm <= 0.0:
        return None
    return normal / norm


@dataclass
class ElasticConstants:
    stiffness_GPa: tuple[tuple[float, ...], ...]
    unit: str = "GPa"
    source: str = ""
    coordinate_frame: str = DEFAULT_ELASTIC_COORDINATE_FRAME
    warnings: list[str] = field(default_factory=list)
    status: ElasticStatus = "valid"

    @classmethod
    def from_cubic(
        cls,
        *,
        c11_GPa: float,
        c12_GPa: float,
        c44_GPa: float,
        source: str = "",
        coordinate_frame: str = DEFAULT_ELASTIC_COORDINATE_FRAME,
    ) -> ElasticConstants:
        matrix = np.zeros((6, 6), dtype=float)
        matrix[0, 0] = matrix[1, 1] = matrix[2, 2] = float(c11_GPa)
        matrix[0, 1] = matrix[0, 2] = matrix[1, 0] = float(c12_GPa)
        matrix[1, 2] = matrix[2, 0] = matrix[2, 1] = float(c12_GPa)
        matrix[3, 3] = matrix[4, 4] = matrix[5, 5] = float(c44_GPa)
        return cls.from_matrix(matrix, source=source, coordinate_frame=coordinate_frame)

    @classmethod
    def from_matrix(
        cls,
        matrix_GPa: Iterable[Iterable[object]],
        *,
        source: str = "",
        unit: str = "GPa",
        coordinate_frame: str = DEFAULT_ELASTIC_COORDINATE_FRAME,
    ) -> ElasticConstants:
        warnings: list[str] = []
        status: ElasticStatus = "valid"
        try:
            matrix = _as_stiffness_matrix(matrix_GPa)
        except Exception as exc:
            return cls(
                tuple(tuple() for _ in range(6)),
                unit=unit,
                source=source,
                coordinate_frame=coordinate_frame,
                warnings=[str(exc)],
                status="invalid_elastic_constants",
            )

        if unit != "GPa":
            warnings.append(f"Elastic constants unit is {unit}; calculations assume GPa.")
        if not np.all(np.isfinite(matrix)):
            return cls(
                _matrix_to_tuple(matrix),
                unit=unit,
                source=source,
                coordinate_frame=coordinate_frame,
                warnings=["Cij matrix contains non-finite values."],
                status="invalid_elastic_constants",
            )
        if not np.allclose(matrix, matrix.T, rtol=1e-6, atol=1e-8):
            warnings.append("Cij matrix is not symmetric; using the symmetrized matrix.")
            matrix = 0.5 * (matrix + matrix.T)

        try:
            _ = np.linalg.inv(matrix)
        except np.linalg.LinAlgError:
            return cls(
                _matrix_to_tuple(matrix),
                unit=unit,
                source=source,
                coordinate_frame=coordinate_frame,
                warnings=[*warnings, "Cij matrix is singular and cannot be inverted."],
                status="invalid_elastic_constants",
            )

        eigenvalues = np.linalg.eigvalsh(matrix)
        if np.min(eigenvalues) <= 0.0:
            return cls(
                _matrix_to_tuple(matrix),
                unit=unit,
                source=source,
                coordinate_frame=coordinate_frame,
                warnings=[*warnings, "Cij matrix is not positive definite."],
                status="invalid_elastic_constants",
            )

        if warnings:
            status = "valid_with_warnings"
        return cls(
            _matrix_to_tuple(matrix),
            unit=unit,
            source=source,
            coordinate_frame=coordinate_frame,
            warnings=warnings,
            status=status,
        )

    @property
    def stiffness_matrix_GPa(self) -> np.ndarray:
        return np.asarray(self.stiffness_GPa, dtype=float)

    @property
    def compliance_matrix_1_over_GPa(self) -> np.ndarray | None:
        if self.status == "invalid_elastic_constants":
            return None
        try:
            return np.linalg.inv(self.stiffness_matrix_GPa)
        except np.linalg.LinAlgError:
            return None

    def young_modulus_hkl_normal_GPa(self, lattice: Any, hkl: Iterable[object]) -> float | None:
        compliance = self.compliance_matrix_1_over_GPa
        if compliance is None:
            return None
        direction = hkl_normal_direction(lattice, hkl)
        if direction is None:
            return None
        l_dir, m_dir, n_dir = (float(value) for value in direction)
        stress_vector = np.asarray(
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
        inverse_modulus = float(stress_vector @ compliance @ stress_vector)
        if not np.isfinite(inverse_modulus) or inverse_modulus <= 0.0:
            return None
        return 1.0 / inverse_modulus


def _matrix_to_tuple(matrix: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in matrix)
