"""Offline request validation and genuinely read-only workflow planning."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from diffractscout.models import AnalysisSettings, DiscoverySettings, ElasticTensor
from diffractscout.workflow import contracts
from diffractscout.workflow.contracts import WorkflowRequest, context, plan_workflow, schema


@pytest.fixture
def local_request(tmp_path):
    source = tmp_path / "inputs" / "source.CIF"
    source.parent.mkdir()
    source.write_text("data_read_only", encoding="utf-8")
    return {"workflow": "analyze", "inputs": [str(source)], "output_dir": str(tmp_path / "results")}


def codes(plan):
    return {item["code"] for item in plan["diagnostics"]}


def test_defaults_normalize_and_round_trip_without_aliasing():
    raw = {"workflow": "analyze"}
    request = WorkflowRequest.from_dict(raw)
    assert request.analysis == asdict(AnalysisSettings())
    assert request.discovery == asdict(DiscoverySettings())
    assert request.exports == {"include_excel": True, "template": "full"}
    assert request.execution["max_attempts"] == 3
    assert request.execution["confirm_above"] == 200
    assert WorkflowRequest.from_dict(request.to_dict()).to_dict() == request.to_dict()
    serialized = request.to_dict()
    serialized["analysis"]["step_deg"] = 2
    assert request.analysis["step_deg"] == 0.02
    assert raw == {"workflow": "analyze"}


@pytest.mark.parametrize("patch", [
    {"unexpected": True}, {"schema": "wrong"}, {"workflow": "unknown"},
    {"analysis": {"step_deg": True}}, {"analysis": {"include_patterns": 1}},
    {"analysis": {"step_deg": float("nan")}}, {"analysis": {"step_deg": "0.1"}},
    {"analysis": {"step_deg": 0}}, {"analysis": {"d_min_A": 5, "d_max_A": 1}},
    {"analysis": {"two_theta_max_deg": 181}}, {"analysis": {"unknown": 1}},
    {"analysis": {"profile_model": "unknown"}}, {"discovery": {"max_total": False}},
    {"discovery": {"exclude_deprecated": "false"}}, {"discovery": {"e_hull_max_eV_atom": -1}},
    {"execution": {"max_attempts": 0}}, {"execution": {"confirm_above": 1.1}},
    {"execution": {"overwrite": 0}}, {"execution": {"unknown": True}},
    {"exports": {"include_excel": "true"}}, {"exports": {"template": "unknown"}},
    {"inputs": "source.cif"}, {"inputs": [""]}, {"output_dir": ""},
    {"composition": 123}, {"submission_id": 1}, {"experiment": "unknown"},
    {"api_key": "do-not-store"}, {"preparation": {"credentials": "do-not-store"}},
    {"preparation": {"max_subsystems": 0}}, {"preparation": {"preview_wavelength_A": -1}},
    {"preparation": {"offline": "yes"}}, {"adaptation": {"a": -1, "citation": "source"}},
    {"adaptation": {"fract": {"q": 1}, "citation": "source"}},
    {"adaptation": {"fract": {"x": True}, "citation": "source"}},
    {"adaptation": {"a": 3}}, {"adaptation": {"atomic_percent": "Ti=90,O=10"}},
])
def test_invalid_requests_fail_before_output_creation(patch, tmp_path):
    with pytest.raises(ValueError):
        WorkflowRequest.from_dict({"workflow": "analyze", "output_dir": str(tmp_path / "new"), **patch})
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize(("analysis", "mode"), [
    ({"energy_keV": 100}, "energy"), ({"wavelength_A": 0.12398}, "wavelength"),
    ({"source_preset": "Custom", "wavelength_A": 1.2}, "source"),
])
def test_numeric_radiation_mode_inference(analysis, mode):
    request = WorkflowRequest.from_dict({"workflow": "analyze", "analysis": analysis})
    assert request.analysis["input_mode"] == mode


@pytest.mark.parametrize("analysis", [
    {"energy_keV": 100, "wavelength_A": 1},
    {"source_preset": "Cu Ka", "energy_keV": 100},
    {"input_mode": "source", "energy_keV": 100},
    {"input_mode": "energy", "wavelength_A": 1},
    {"input_mode": "wavelength", "energy_keV": 1},
    {"energy_keV": 0}, {"source_preset": "Custom"},
])
def test_contradictory_radiation_is_rejected(analysis):
    with pytest.raises(ValueError):
        WorkflowRequest.from_dict({"workflow": "analyze", "analysis": analysis})


def test_request_file_relative_paths_resolve_without_reads(tmp_path):
    request = WorkflowRequest.from_dict({
        "workflow": "prepare", "inputs": ["source.cif"], "output_dir": "derived",
        "preparation": {"templates": {"alpha": "template.cif"}, "parameter_file": "parameters.json"},
    }, base_dir=tmp_path)
    assert request.inputs == [str(tmp_path / "source.cif")]
    assert request.output_dir == str(tmp_path / "derived")
    assert request.preparation["templates"]["alpha"] == str(tmp_path / "template.cif")
    assert request.preparation["parameter_file"] == str(tmp_path / "parameters.json")
    assert list(tmp_path.iterdir()) == []


def test_elastic_tensor_serialization_revalidates_scientific_payload():
    tensor = ElasticTensor(np.eye(6) * 100, source_provider="caller")
    request = WorkflowRequest.from_dict({"workflow": "analyze", "elastic_overrides": {"phase": tensor}})
    assert json.loads(json.dumps(request.to_dict()))["elastic_overrides"]["phase"]["stiffness_GPa"][0][0] == 100
    request = WorkflowRequest.from_dict(request.to_dict())
    assert request.elastic_overrides["phase"]["source_provider"] == "caller"
    for bad in ({"stiffness_GPa": [[1]]}, {"stiffness_GPa": np.zeros((6, 6)).tolist()},
                {"stiffness_GPa": np.eye(6).tolist(), "unit": "Pa"}):
        with pytest.raises(ValueError):
            WorkflowRequest.from_dict({"workflow": "analyze", "elastic_overrides": {"phase": bad}})


def test_local_plan_never_writes_or_requires_mp_credentials(local_request, monkeypatch):
    monkeypatch.delenv("MP_API_KEY", raising=False)
    monkeypatch.setattr(contracts, "_available", lambda name: name not in ("mp_api", "pymatgen"))
    source = Path(local_request["inputs"][0])
    before = source.read_bytes()
    plan = plan_workflow(local_request)
    assert plan["ready"], plan["diagnostics"]
    assert plan["local_cifs"] == [str(source)]
    assert plan["estimated_queries"] == 0
    assert "mp-api" not in plan["required_dependencies"]
    assert source.read_bytes() == before
    assert not Path(local_request["output_dir"]).exists()


def test_missing_fields_and_paths_are_actionable(tmp_path):
    plan = plan_workflow({"workflow": "analyze", "inputs": [str(tmp_path / "absent.cif")]})
    assert not plan["ready"]
    assert "invalid_inputs" in codes(plan)
    for item in plan["diagnostics"]:
        assert {"code", "message", "stage", "item", "retryable", "missing_fields"} <= set(item)
    assert plan_workflow({"workflow": "analyze"})["diagnostics"][0]["missing_fields"] == ["inputs"]


def test_optional_output_uses_managed_bundle_without_creating_it(local_request):
    local_request.pop("output_dir")
    plan = plan_workflow(local_request)
    assert plan["ready"]
    assert plan["request"]["output_dir"] is None
    assert plan["parameter_sources"]["output"] == "managed per-run bundle"


def test_preparation_preserves_supported_p1_template_restoration(tmp_path):
    import gemmi
    from diffractscout.cif_quality import write_clean_model

    small = gemmi.SmallStructure()
    small.cell = gemmi.UnitCell(3.2, 3.2, 3.2, 90, 90, 90)
    small.spacegroup_hm = "P 1"
    for index, position in enumerate(((0, 0, 0), (0.5, 0.5, 0.5))):
        site = gemmi.SmallStructure.Site()
        site.element = gemmi.Element("Ti")
        site.type_symbol = "Ti"
        site.label = f"Ti{index}"
        site.fract = gemmi.Fractional(*position)
        site.occ = 1
        small.add_site(site)
    template = tmp_path / "p1.cif"
    write_clean_model(small, template, details="Synthetic test")
    before = template.read_bytes()
    plan = plan_workflow({"workflow": "prepare", "composition": "Ti", "preparation": {
        "phases": ["beta"], "templates": {"beta": str(template)}, "offline": True,
    }})
    assert plan["ready"], plan["diagnostics"]
    assert template.read_bytes() == before
    assert list(tmp_path.iterdir()) == [template]


def test_unsafe_existing_output_cannot_be_planned_for_overwrite(local_request):
    output = Path(local_request["output_dir"])
    output.mkdir()
    unrelated = output / "unrelated.txt"
    unrelated.write_text("preserve", encoding="utf-8")
    local_request["execution"] = {"overwrite": True}
    assert "unsafe_overwrite" in codes(plan_workflow(local_request))
    assert unrelated.read_text() == "preserve"


def test_input_output_separation_is_checked_without_creating_target(local_request):
    source = Path(local_request["inputs"][0])
    local_request["output_dir"] = str(source.parent)
    plan = plan_workflow(local_request)
    assert "unsafe_output" in codes(plan)
    assert source.read_text() == "data_read_only"


def test_synchrotron_never_silently_uses_laboratory_defaults(local_request):
    local_request["experiment"] = "synchrotron"
    assert "missing_radiation" in codes(plan_workflow(local_request))
    local_request["analysis"] = {"energy_keV": 100}
    assert plan_workflow(local_request)["ready"]


def test_provider_injection_and_query_estimate_are_pure(tmp_path, monkeypatch):
    class NoCallProvider:
        def __getattr__(self, name):
            raise AssertionError(f"Planner accessed provider.{name}")

    monkeypatch.delenv("MP_API_KEY", raising=False)
    monkeypatch.setattr(contracts, "_available", lambda name: name not in ("mp_api", "pymatgen"))
    raw = {"workflow": "run", "composition": "Ti-Nb-Zr", "output_dir": str(tmp_path / "new")}
    blocked = plan_workflow(raw)
    assert {"missing_credentials", "missing_dependency"} <= codes(blocked)
    plan = plan_workflow(raw, provider=NoCallProvider())
    assert plan["ready"], plan["diagnostics"]
    assert plan["estimated_queries"] == 7
    assert not (tmp_path / "new").exists()
    raw["discovery"] = {"max_subsystems": 3}
    assert "query_limit" in codes(plan_workflow(raw, provider=NoCallProvider()))


def test_preparation_reuses_phase_parameter_validation(tmp_path):
    raw = {"workflow": "prepare", "composition": "Ti", "output_dir": str(tmp_path / "new"),
           "preparation": {"offline": True, "phases": ["beta"]}}
    assert plan_workflow(raw)["ready"]
    raw["preparation"]["phase_parameters"] = {"beta": {"lattice": {"a": 3.3}}}
    with pytest.raises(ValueError, match="citation"):
        WorkflowRequest.from_dict(raw)
    raw["preparation"]["phase_parameters"]["beta"]["citation"] = "caller supplied value"
    assert plan_workflow(raw)["ready"]
    assert not (tmp_path / "new").exists()


def test_missing_preparation_files_block_without_writes(tmp_path):
    raw = {"workflow": "prepare", "composition": "Ti", "output_dir": str(tmp_path / "new"),
           "preparation": {"templates": {"beta": str(tmp_path / "missing.cif")}}}
    assert "invalid_preparation" in codes(plan_workflow(raw))
    raw["preparation"] = {"parameter_file": str(tmp_path / "missing.json")}
    assert "invalid_preparation" in codes(plan_workflow(raw))
    assert not (tmp_path / "new").exists()


def test_schema_has_precise_nested_types_and_defaults():
    document = schema()
    assert document["additionalProperties"] is False
    properties = document["properties"]
    assert properties["schema"]["const"] == "diffractscout_workflow_v1"
    assert properties["execution"]["properties"]["overwrite"]["type"] == "boolean"
    assert properties["execution"]["properties"]["max_attempts"]["default"] == 3
    assert properties["analysis"]["properties"]["energy_keV"]["anyOf"] == [{"type": "number"}, {"type": "null"}]
    assert properties["preparation"]["properties"]["templates"]["additionalProperties"]["type"] == "string"
    assert properties["exports"]["properties"]["template"]["enum"] == ["full", "peak_table"]
    json.dumps(document, allow_nan=False)
    with pytest.raises(ValueError):
        schema("unknown")


def test_context_contains_only_credential_presence(monkeypatch):
    monkeypatch.setenv("MP_API_KEY", "sentinel-sensitive-value")
    capability = context()
    assert capability["credentials"]["configured"] is True
    assert "sentinel-sensitive-value" not in json.dumps(capability)
    assert capability["planning"] == {"network": False, "writes": False}
