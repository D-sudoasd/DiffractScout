import builtins
import json
import math
from pathlib import Path

import pytest

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


def test_missing_materials_project_dependency_explains_both_install_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def fail_mp_api(name: str, *args: object, **kwargs: object) -> object:
        if name == "mp_api.client":
            raise ImportError("simulated missing mp-api")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_mp_api)
    with pytest.raises(RuntimeError) as exc_info:
        MaterialsProjectProvider("test-key")

    message = str(exc_info.value)
    assert 'python -m pip install "diffractscout[mp]"' in message
    assert 'python -m pip install -e ".[mp]"' in message


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


def test_candidate_filename_is_one_safe_basename_for_hostile_material_id() -> None:
    candidate = CandidateRecord(
        material_id="../../outside\\candidate",
        formula="Al/O",
        source_provider="Materials Project",
    )
    filename = _candidate_filename(candidate)
    assert Path(filename).name == filename
    assert ".." not in filename
    assert "/" not in filename and "\\" not in filename


def test_matrix_conversion() -> None:
    matrix = [[float(i == j) for j in range(6)] for i in range(6)]
    assert _matrix(matrix) == matrix
    assert _matrix([[1, 2]]) is None
    assert _matrix([[float(i == j) for j in range(7)] for i in range(7)]) is None
    matrix[0][0] = math.nan
    assert _matrix(matrix) is None


def test_subsystem_query_filters_energy_before_page_limit() -> None:
    calls: list[dict[str, object]] = []

    class SummaryEndpoint:
        def search(self, **kwargs: object) -> list[dict[str, object]]:
            calls.append(kwargs)
            return [
                {
                    "material_id": "mp-1",
                    "formula_pretty": "Al",
                    "energy_above_hull": 0.02,
                    "deprecated": False,
                },
                {
                    "material_id": "mp-unknown",
                    "formula_pretty": "Al",
                    "energy_above_hull": None,
                    "deprecated": False,
                },
                {
                    "material_id": "mp-negative",
                    "formula_pretty": "Al",
                    "energy_above_hull": -0.01,
                    "deprecated": False,
                },
            ]

    class Materials:
        summary = SummaryEndpoint()

    class Client:
        materials = Materials()

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get_database_version(self) -> str:
            return "test"

    provider = _provider_without_client()
    provider.api_key = "test"
    provider._mpr_cls = lambda _api_key: Client()
    provider._metadata = {}

    candidates = provider.search_subsystem("Al", max_results=5, e_hull_max_eV_atom=0.05)

    assert [candidate.material_id for candidate in candidates] == ["mp-1"]
    assert calls[0]["energy_above_hull"] == (0.0, 0.05)
    assert calls[0]["chunk_size"] == 5
    assert calls[0]["num_chunks"] == 1


def test_database_version_prefers_new_client_attribute() -> None:
    provider = _provider_without_client()
    provider._metadata = {}

    class Client:
        db_version = "2026.08"

        def get_database_version(self) -> str:
            raise AssertionError("legacy method should not be preferred")

    provider._capture_metadata(Client())
    assert provider._metadata["database_version"] == "2026.08"


def test_summary_search_typeerror_fallback_reapplies_filters_locally() -> None:
    calls: list[dict[str, object]] = []

    class SummaryEndpoint:
        def search(self, **kwargs: object) -> list[dict[str, object]]:
            calls.append(kwargs)
            if len(calls) < 4:
                raise TypeError("legacy client does not accept optional keyword")
            return [
                {
                    "material_id": "mp-good",
                    "formula_pretty": "Al",
                    "energy_above_hull": 0.01,
                    "deprecated": False,
                },
                {
                    "material_id": "mp-old",
                    "formula_pretty": "Al",
                    "energy_above_hull": 0.01,
                    "deprecated": True,
                },
                {
                    "material_id": "mp-high",
                    "formula_pretty": "Al",
                    "energy_above_hull": 0.2,
                    "deprecated": False,
                },
            ]

    class Materials:
        summary = SummaryEndpoint()

    class Client:
        materials = Materials()

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    provider = _provider_without_client()
    provider.api_key = "test"
    provider._mpr_cls = lambda _api_key: Client()
    provider._metadata = {}
    candidates = provider.search_subsystem(
        "Al",
        max_results=1,
        e_hull_max_eV_atom=0.05,
        exclude_deprecated=True,
    )
    assert [candidate.material_id for candidate in candidates] == ["mp-good"]
    assert len(calls) == 4
    assert provider._metadata.get("compatibility_fallback")


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

    assert payload["status"] == "frame_transform_required"
    assert payload["stiffness_GPa"] == raw
    assert payload["diffractscout"]["coordinate_frame"] == MP_CONVENTIONAL_CIF_FRAME
    assert payload["provenance"]["usable_for_hkl_modulus"] is False
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


def test_elasticity_query_failure_is_distinct_from_missing_data(tmp_path: Path) -> None:
    provider = _provider_without_client()

    class ElasticityEndpoint:
        def search(self, **_kwargs: object) -> object:
            raise RuntimeError("service unavailable")

    class Materials:
        elasticity = ElasticityEndpoint()

    class Mpr:
        materials = Materials()

    documents, error = provider._elasticity_documents(Mpr(), ["mp-123"])
    assert documents == {}
    assert "service unavailable" in error

    cif_path = tmp_path / "mp-123_Al.cif"
    cif_path.write_text("data_test\n", encoding="utf-8")
    path, status, sidecar_error = provider._write_elasticity(
        _candidate(),
        cif_path,
        None,
        conventional_unit_cell=True,
        query_error=error,
        return_status=True,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert status == payload["status"] == "elasticity_query_failed"
    assert "service unavailable" in sidecar_error
