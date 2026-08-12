"""Miller and Miller–Bravais index helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


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
    """Return the three-index plane used for reciprocal-lattice normals.

    Four-index Miller–Bravais planes must satisfy ``i = -(h + k)``.
    """

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


def miller_bravais_i(h: int, k: int) -> int:
    """Return the Miller–Bravais basal index ``i = -(h + k)``."""

    return -(int(h) + int(k))


def _uses_miller_bravais(crystal_system: str) -> bool:
    text = crystal_system.casefold()
    return "hex" in text or "trigonal" in text


def uses_miller_bravais(space_group: Any) -> bool:
    """True when the space group's crystal system is hexagonal or trigonal."""

    if space_group is None:
        return False
    try:
        system = str(space_group.crystal_system_str())
    except Exception:
        return False
    return _uses_miller_bravais(system)


def family_label_hkl(
    h: int,
    k: int,
    l: int,  # noqa: E741 - conventional Miller index name
    *,
    use_four_index: bool = False,
    i: int | None = None,
) -> str:
    """Curly-brace family label; optional Miller–Bravais four-index form."""

    h_i, k_i, l_i = int(h), int(k), int(l)
    if use_four_index:
        index_i = miller_bravais_i(h_i, k_i) if i is None else int(i)
        return "{" + f"{h_i} {k_i} {index_i} {l_i}" + "}"
    return "{" + f"{h_i} {k_i} {l_i}" + "}"


def label_hkl_for_crystal_system(
    h: int,
    k: int,
    l: int,  # noqa: E741 - conventional Miller index name
    crystal_system: str,
) -> tuple[str, int | None]:
    """Return a display label and optional Miller–Bravais ``i``.

    Hexagonal and trigonal systems (``crystal_system`` lowercased contains
    ``hex`` or ``trigonal``) use four-index Miller–Bravais labels such as
    ``(1 0 -1 0)``. Other systems use three-index ``(h k l)``.
    """

    h_i, k_i, l_i = int(h), int(k), int(l)
    if _uses_miller_bravais(crystal_system):
        i = miller_bravais_i(h_i, k_i)
        return format_hkl((h_i, k_i, i, l_i)), i
    return format_hkl((h_i, k_i, l_i)), None
