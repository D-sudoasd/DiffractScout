from __future__ import annotations

from collections.abc import Iterable


def normalize_hkl(values: Iterable[object]) -> tuple[int, ...]:
    hkl = tuple(int(value) for value in values)
    if len(hkl) not in {3, 4}:
        raise ValueError(f"hkl must contain 3 or 4 indices, got {len(hkl)}: {hkl}")
    return hkl


def format_hkl(values: Iterable[object]) -> str:
    return f"({' '.join(str(value) for value in normalize_hkl(values))})"


def split_hkl_components(values: Iterable[object]) -> tuple[int, int, int | None, int]:
    hkl = normalize_hkl(values)
    if len(hkl) == 3:
        h, k, ell = hkl
        return h, k, None, ell
    h, k, i, ell = hkl
    return h, k, i, ell


def plane_hkl_for_normal(values: Iterable[object]) -> tuple[int, int, int]:
    hkl = normalize_hkl(values)
    if len(hkl) == 3:
        h, k, ell = hkl
        return h, k, ell
    h, k, i, ell = hkl
    if i != -(h + k):
        raise ValueError(
            f"Four-index Miller-Bravais plane hkil must satisfy i = -(h + k), got {hkl}."
        )
    return h, k, ell
