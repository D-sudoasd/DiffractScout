"""Freeze local sources once, before a resumable workflow begins."""
from __future__ import annotations

from pathlib import Path

from ..pipeline import _copy_local_input, _copy_local_snapshot, _lookup_elastic_override, collect_cif_paths
from ..utils import sha256_file, to_jsonable, write_json
from .checkpoints import publish_checkpoint, tensor_from_dict, verify_checkpoint
from .contracts import WorkflowRequest
from .store import read_json


def snapshot_request(root: Path, request: WorkflowRequest) -> WorkflowRequest:
    target = root / "sources"
    if not target.exists():
        def write(directory: Path) -> None:
            mapping = {"inputs": [], "templates": {}, "parameter_file": None, "elastic_overrides": {}}
            inputs_dir = directory / "inputs"
            inputs_dir.mkdir()
            overrides = {key: tensor_from_dict(value) for key, value in request.elastic_overrides.items()}
            for source in collect_cif_paths(request.inputs, recursive=request.execution["recursive"]) if request.inputs else []:
                copied, tensor = _copy_local_input(
                    source, inputs_dir, include_elasticity=request.analysis["include_elasticity"],
                    elastic_override=_lookup_elastic_override(source, overrides) if overrides else None)
                relative = copied.relative_to(directory).as_posix()
                mapping["inputs"].append(relative)
                if tensor is not None and overrides:
                    payload = to_jsonable(tensor)
                    if tensor.raw_payload_path:
                        payload["raw_payload_path"] = tensor.raw_payload_path.relative_to(directory).as_posix()
                    mapping["elastic_overrides"][relative] = payload
            template_dir = directory / "templates"
            template_dir.mkdir()
            for phase, value in request.preparation.get("templates", {}).items():
                source = Path(value)
                copied, _ = _copy_local_input(source, template_dir, include_elasticity=False)
                mapping["templates"][phase] = copied.relative_to(directory).as_posix()
            if request.preparation.get("parameter_file"):
                source = Path(request.preparation["parameter_file"])
                copied = directory / "phase_parameters.json"
                _copy_local_snapshot(source, copied, expected_digest=sha256_file(source), expected_size=source.stat().st_size)
                mapping["parameter_file"] = copied.name
            write_json(directory / "source-map.json", mapping)
        publish_checkpoint(target, write)
    verify_checkpoint(target)
    mapping = read_json(target / "source-map.json")
    payload = request.to_dict()
    payload["inputs"] = [str(target / name) for name in mapping["inputs"]]
    if mapping["templates"]:
        payload["preparation"]["templates"] = {phase: str(target / name) for phase, name in mapping["templates"].items()}
    if mapping["parameter_file"]:
        payload["preparation"]["parameter_file"] = str(target / mapping["parameter_file"])
    payload["elastic_overrides"] = {}
    for relative, tensor in mapping["elastic_overrides"].items():
        tensor = dict(tensor)
        if tensor.get("raw_payload_path"):
            tensor["raw_payload_path"] = str(target / tensor["raw_payload_path"])
        payload["elastic_overrides"][str(target / relative)] = tensor
    return WorkflowRequest.from_dict(payload)
