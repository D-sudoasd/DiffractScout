"""Optional Materials Project provider implemented through mp-api."""

from __future__ import annotations

import math
from pathlib import Path
import tempfile
from typing import Any, Sequence

from ..elasticity import MP_CONVENTIONAL_CIF_FRAME, MP_IEEE_CONVENTIONAL_FRAME
from ..models import CandidateRecord, DownloadArtifact
from ..structure_types import infer_structure_type
from ..utils import slugify, utc_now_iso, write_json

ELASTICITY_METHODOLOGY_URL = (
    "https://docs.materialsproject.org/methodology/materials-methodology/elasticity"
)


def _value(obj: object, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _plain(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return _plain(enum_value)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _plain(item())
        except Exception:
            pass
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _plain(tolist())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    try:
        return [_plain(item) for item in value]  # type: ignore[arg-type]
    except TypeError:
        return str(value)


def _matrix(value: object) -> list[list[float]] | None:
    plain = _plain(value)
    if not isinstance(plain, list) or len(plain) != 6:
        return None
    output: list[list[float]] = []
    try:
        for row in plain:
            if not isinstance(row, list) or len(row) != 6:
                return None
            converted = [float(item) for item in row]
            if not all(math.isfinite(item) for item in converted):
                return None
            output.append(converted)
    except (TypeError, ValueError):
        return None
    return output


def _symmetry_fields(doc: object) -> tuple[str, int | None, str]:
    symmetry = _value(doc, "symmetry")
    symbol = str(_value(symmetry, "symbol", "") or "")
    number_raw = _value(symmetry, "number")
    try:
        number = int(number_raw) if number_raw is not None else None
    except (TypeError, ValueError):
        number = None
    crystal_system = str(_value(symmetry, "crystal_system", "") or "")
    return symbol, number, crystal_system


def _candidate_from_doc(doc: object, chemsys: str) -> CandidateRecord:
    material_id = str(_value(doc, "material_id", "") or "").lower()
    formula = str(_value(doc, "formula_pretty", "") or "")
    symbol, number, crystal_system = _symmetry_fields(doc)
    e_hull_raw = _value(doc, "energy_above_hull")
    try:
        e_hull = float(e_hull_raw) if e_hull_raw is not None else None
    except (TypeError, ValueError):
        e_hull = None
    if e_hull is not None and not math.isfinite(e_hull):
        e_hull = None
    structure_type = infer_structure_type(formula, symbol, number)
    return CandidateRecord(
        material_id=material_id,
        formula=formula,
        energy_above_hull_eV_atom=e_hull,
        is_stable=_value(doc, "is_stable"),
        theoretical=_value(doc, "theoretical"),
        space_group=symbol,
        space_group_number=number,
        crystal_system=crystal_system,
        deprecated=_value(doc, "deprecated"),
        queried_chemsys=chemsys,
        source_provider="Materials Project",
        source_url=f"https://materialsproject.org/materials/{material_id}" if material_id else "",
        structure_type=structure_type.name,
        structure_type_rule=structure_type.rule,
    )


def _candidate_filename(candidate: CandidateRecord) -> str:
    parts = [candidate.material_id or "mp-unknown", slugify(candidate.formula, "structure")]
    if candidate.structure_type:
        parts.append(slugify(candidate.structure_type, ""))
    if candidate.space_group_number is not None:
        parts.append(f"sg{candidate.space_group_number}")
    if candidate.space_group:
        parts.append(slugify(candidate.space_group, ""))
    if candidate.energy_above_hull_eV_atom is not None:
        value = candidate.energy_above_hull_eV_atom
        token = "0" if abs(value) < 5e-7 else f"{value:.3f}".replace("-", "m").replace(".", "p")
        parts.append(f"ehull{token}")
    if candidate.is_stable is True:
        parts.append("stable")
    return "_".join(part for part in parts if part) + ".cif"


class MaterialsProjectProvider:
    name = "Materials Project"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()
        if not self.api_key:
            raise ValueError("Materials Project API key is empty.")
        try:
            from mp_api.client import MPRester  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Materials Project support is optional. Install with: pip install 'diffractscout[mp]'"
            ) from exc
        self._mpr_cls = MPRester
        self._metadata: dict[str, object] = {
            "provider": self.name,
            "client": "mp-api",
            "queried_at_utc": None,
            "database_version": None,
        }

    def metadata(self) -> dict[str, object]:
        return dict(self._metadata)

    def search_material_ids(self, material_ids: Sequence[str]) -> list[CandidateRecord]:
        """Resolve explicit Materials Project IDs to full summary records."""

        requested = [str(item).strip().lower() for item in material_ids if str(item).strip()]
        if not requested:
            return []
        fields = [
            "material_id",
            "formula_pretty",
            "energy_above_hull",
            "is_stable",
            "theoretical",
            "symmetry",
            "deprecated",
        ]
        with self._mpr_cls(self.api_key) as mpr:
            self._capture_metadata(mpr)
            docs = mpr.materials.summary.search(material_ids=requested, fields=fields)
        by_id = {
            candidate.material_id: candidate
            for candidate in (
                _candidate_from_doc(doc, "explicit_material_id") for doc in docs
            )
            if candidate.material_id
        }
        return [by_id[item] for item in requested if item in by_id]

    def search_subsystem(
        self,
        chemsys: str,
        *,
        max_results: int | None = None,
        e_hull_max_eV_atom: float | None = None,
        exclude_deprecated: bool = True,
    ) -> list[CandidateRecord]:
        fields = [
            "material_id",
            "formula_pretty",
            "energy_above_hull",
            "is_stable",
            "theoretical",
            "symmetry",
            "deprecated",
        ]
        kwargs: dict[str, Any] = {"chemsys": chemsys, "fields": fields}
        if exclude_deprecated:
            kwargs["deprecated"] = False
        if e_hull_max_eV_atom is not None:
            # Filter before applying the page limit; otherwise a locally filtered
            # first page can omit qualifying candidates from later pages.
            kwargs["energy_above_hull"] = (0.0, e_hull_max_eV_atom)
        if max_results is not None and max_results > 0:
            kwargs.update({"chunk_size": max_results, "num_chunks": 1})

        with self._mpr_cls(self.api_key) as mpr:
            self._capture_metadata(mpr)
            try:
                docs = mpr.materials.summary.search(**kwargs)
            except TypeError:
                docs = mpr.materials.summary.search(chemsys=chemsys, fields=fields)

        output: list[CandidateRecord] = []
        for doc in docs:
            candidate = _candidate_from_doc(doc, chemsys)
            if not candidate.material_id:
                continue
            if exclude_deprecated and candidate.deprecated is True:
                continue
            if e_hull_max_eV_atom is not None:
                energy = candidate.energy_above_hull_eV_atom
                if energy is None or energy > e_hull_max_eV_atom:
                    continue
            output.append(candidate)
            if max_results is not None and len(output) >= max_results:
                break
        return output

    def _capture_metadata(self, mpr: object) -> None:
        self._metadata["queried_at_utc"] = utc_now_iso()
        try:
            self._metadata["database_version"] = mpr.get_database_version()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _elasticity_documents(
        self, mpr: object, material_ids: list[str]
    ) -> tuple[dict[str, object], str]:
        if not material_ids:
            return {}, ""
        fields = [
            "material_id",
            "formula_pretty",
            "elastic_tensor",
            "bulk_modulus",
            "shear_modulus",
            "homogeneous_poisson",
            "universal_anisotropy",
            "fitting_method",
            "state",
        ]
        try:
            docs = mpr.materials.elasticity.search(  # type: ignore[attr-defined]
                material_ids=material_ids,
                fields=fields,
                all_fields=False,
                chunk_size=min(1000, max(1, len(material_ids))),
                num_chunks=None,
            )
        except TypeError:
            try:
                docs = mpr.materials.elasticity.search(  # type: ignore[attr-defined]
                    material_ids=material_ids,
                    fields=fields,
                )
            except Exception as exc:
                return {}, str(exc)
        except Exception as exc:
            return {}, str(exc)
        return (
            {
                str(_value(doc, "material_id", "") or "").lower(): doc
                for doc in docs
                if _value(doc, "material_id", "")
            },
            "",
        )

    def _write_elasticity(
        self,
        candidate: CandidateRecord,
        cif_path: Path,
        document: object | None,
        *,
        conventional_unit_cell: bool,
        query_error: str = "",
        return_status: bool = False,
    ) -> Path | tuple[Path, str, str]:
        tensor = _value(document, "elastic_tensor") if document is not None else None
        ieee = _matrix(_value(tensor, "ieee_format"))
        raw = _matrix(_value(tensor, "raw"))
        # Materials Project documents the raw/POSCAR-format tensor as consistent
        # with the downloadable conventional-standard CIF. The IEEE tensor can
        # differ by a rotation and is retained for provenance, but is not used
        # for hkl-resolved calculations without that rotation.
        stiffness = raw if conventional_unit_cell else None
        if query_error:
            status = "elasticity_query_failed"
            coordinate_frame = ""
            error = query_error
        elif document is None:
            status = "no_elasticity_data"
            coordinate_frame = ""
            error = "No elasticity document was returned for this material."
        elif stiffness is not None:
            status = "ok"
            coordinate_frame = MP_CONVENTIONAL_CIF_FRAME
            error = ""
        elif ieee is not None:
            status = "frame_transform_required"
            coordinate_frame = MP_IEEE_CONVENTIONAL_FRAME
            error = (
                "Only an IEEE-oriented tensor was returned; an explicit rotation is required "
                "before hkl-resolved properties can be evaluated."
            )
        else:
            status = "no_elastic_tensor"
            coordinate_frame = ""
            error = "The elasticity document contains no usable 6x6 tensor."
        payload: dict[str, object] = {
            "schema": "diffractscout_elasticity_v1",
            "material_id": candidate.material_id,
            "formula": candidate.formula,
            "cif_filename": cif_path.name,
            "status": status,
            "error": error,
            "units": {"elastic_tensor": "GPa"},
            "elastic_tensor": {"ieee_format": ieee, "raw": raw} if document is not None else None,
            "bulk_modulus": _plain(_value(document, "bulk_modulus")) if document is not None else None,
            "shear_modulus": _plain(_value(document, "shear_modulus")) if document is not None else None,
            "poisson_ratio": _plain(_value(document, "homogeneous_poisson")) if document is not None else None,
            "universal_anisotropy": _plain(_value(document, "universal_anisotropy")) if document is not None else None,
            "fitting_method": _plain(_value(document, "fitting_method")) if document is not None else None,
            "state": _plain(_value(document, "state")) if document is not None else None,
            "provenance": {
                "provider": "Materials Project",
                "api": "materials/elasticity",
                "material_id": candidate.material_id,
                "paired_cif": cif_path.name,
                "methodology_url": ELASTICITY_METHODOLOGY_URL,
                "source_url": candidate.source_url,
                "nature_of_data": "DFT_calculated" if (raw is not None or ieee is not None) else "none",
                "numerical_cij": raw is not None or ieee is not None,
                "query_error": query_error,
                "usable_for_hkl_modulus": stiffness is not None,
                "not_experimental": True,
                "coordinate_frame": coordinate_frame,
            },
        }
        if stiffness is not None:
            payload["stiffness_GPa"] = stiffness
            payload["diffractscout"] = {
                "stiffness_GPa": stiffness,
                "coordinate_frame": coordinate_frame,
                "paired_cif": cif_path.name,
            }
        path = write_json(cif_path.with_name(f"{cif_path.stem}_elasticity.json"), payload)
        return (path, status, error) if return_status else path

    def download_candidates(
        self,
        candidates: Sequence[CandidateRecord],
        output_dir: Path,
        *,
        conventional_unit_cell: bool = True,
        include_elasticity: bool = True,
    ) -> list[DownloadArtifact]:
        if include_elasticity and not conventional_unit_cell:
            raise ValueError(
                "Materials Project elastic tensors are coupled automatically only to the "
                "conventional-standard CIF. Disable elasticity when requesting primitive cells."
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[DownloadArtifact] = []
        successful: list[tuple[CandidateRecord, Path]] = []
        with self._mpr_cls(self.api_key) as mpr:
            self._capture_metadata(mpr)
            for candidate in candidates:
                try:
                    structure = mpr.get_structure_by_material_id(
                        candidate.material_id,
                        final=True,
                        conventional_unit_cell=conventional_unit_cell,
                    )
                    if structure is None:
                        raise RuntimeError("No structure returned by Materials Project.")
                    path = output_dir / _candidate_filename(candidate)
                    temporary_name = ""
                    try:
                        with tempfile.NamedTemporaryFile(
                            mode="w", suffix=".cif", prefix=f".{path.stem}_", dir=output_dir, delete=False
                        ) as handle:
                            temporary_name = handle.name
                        structure.to(fmt="cif", filename=temporary_name)
                        Path(temporary_name).replace(path)
                    finally:
                        if temporary_name:
                            Path(temporary_name).unlink(missing_ok=True)
                    successful.append((candidate, path))
                    results.append(
                        DownloadArtifact(
                            candidate=candidate,
                            cif_path=path,
                            status="ok",
                            provider_metadata=self.metadata(),
                        )
                    )
                except Exception as exc:
                    results.append(
                        DownloadArtifact(
                            candidate=candidate,
                            cif_path=None,
                            status="failed",
                            error=str(exc),
                            provider_metadata=self.metadata(),
                        )
                    )

            if include_elasticity:
                documents, elasticity_query_error = self._elasticity_documents(
                    mpr, [candidate.material_id for candidate, _path in successful]
                )
            else:
                documents, elasticity_query_error = {}, ""

        elasticity_by_id: dict[str, tuple[Path, str, str]] = {}
        if include_elasticity:
            for candidate, path in successful:
                elasticity_by_id[candidate.material_id] = self._write_elasticity(
                    candidate,
                    path,
                    documents.get(candidate.material_id),
                    conventional_unit_cell=conventional_unit_cell,
                    query_error=elasticity_query_error,
                    return_status=True,
                )  # type: ignore[assignment]
        return [
            DownloadArtifact(
                candidate=item.candidate,
                cif_path=item.cif_path,
                elasticity_path=(elasticity_by_id[item.candidate.material_id][0] if item.candidate.material_id in elasticity_by_id else None),
                status=item.status,
                error=item.error,
                elasticity_status=(
                    elasticity_by_id[item.candidate.material_id][1]
                    if item.candidate.material_id in elasticity_by_id
                    else "not_requested"
                    if not include_elasticity and item.status == "ok"
                    else ""
                ),
                elasticity_error=(elasticity_by_id[item.candidate.material_id][2] if item.candidate.material_id in elasticity_by_id else ""),
                provider_metadata=item.provider_metadata,
            )
            for item in results
        ]
