"""Content-verified JSON/NPZ checkpoints, without executable serialization."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from ..models import ElasticTensor, PhaseAnalysis, ReflectionRecord, StructureRecord
from ..pipeline import _reject_reparse_components, _rename_directory_noreplace
from ..utils import package_versions, sha256_file, to_jsonable, write_json
from .store import read_json


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(to_jsonable(value), sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def environment() -> dict[str, Any]:
    # Version alone does not identify an editable checkout. Hash the relevant
    # Python sources, including this serializer, so changed code cannot silently
    # consume a prior numerical checkpoint under the same package version.
    package = Path(__file__).resolve().parents[1]
    names = {"diffraction.py", "structure.py", "elasticity.py", "elasticity_input.py", "models.py",
             "phase_cif.py", "cif_quality.py", "initial_cifs.py", "selection.py", "composition.py", "pipeline.py"}
    sources = {p.relative_to(package).as_posix(): sha256_file(p)
               for p in sorted(package.rglob("*.py"))
               if (p.parent == package and p.name in names) or p.parent.name in {"workflow", "providers"}}
    source_digest = sha256_file(os.sys.executable) if getattr(os.sys, "frozen", False) else fingerprint(sources)
    return {"versions": package_versions(), "source_sha256": source_digest,
            "python": os.sys.version.split()[0], "checkpoint_schema": 1}


def seal(directory: Path) -> None:
    members = []
    for path in sorted(directory.rglob("*")):
        _reject_reparse_components(path, label="checkpoint member")
        if path.is_file() and path.name != "checkpoint.json":
            members.append({"path": path.relative_to(directory).as_posix(),
                            "sha256": sha256_file(path), "size": path.stat().st_size})
    write_json(directory / "checkpoint.json", {"schema": "diffractscout_checkpoint_v1", "files": members})


def verify_checkpoint(directory: Path) -> None:
    _reject_reparse_components(directory, label="checkpoint")
    manifest = read_json(directory / "checkpoint.json")
    if manifest.get("schema") != "diffractscout_checkpoint_v1":
        raise ValueError(f"Unknown checkpoint schema: {directory}")
    seen = set()
    for entry in manifest["files"]:
        name = entry["path"]
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name in seen or name == "checkpoint.json":
            raise ValueError(f"Unsafe checkpoint member: {name}")
        seen.add(name)
        path = directory / relative
        _reject_reparse_components(path, label="checkpoint member")
        if not path.is_file() or path.stat().st_size != entry["size"] or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Checkpoint integrity failed: {path}")
    actual = set()
    for p in directory.rglob("*"):
        _reject_reparse_components(p, label="checkpoint member")
        if p.is_file() and p != directory / "checkpoint.json":
            actual.add(p.relative_to(directory).as_posix())
    if actual != seen:
        raise ValueError(f"Checkpoint members differ from manifest: {directory}")


def publish_checkpoint(destination: Path, writer) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".checkpoint-", dir=destination.parent))
    try:
        writer(staging)
        seal(staging)
        verify_checkpoint(staging)
        _rename_directory_noreplace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def save_analysis(directory: Path, analysis: PhaseAnalysis) -> None:
    payload = to_jsonable(analysis)
    payload.pop("two_theta_grid")
    payload.pop("intensity_profile")
    write_json(directory / "analysis.json", payload)
    np.savez(directory / "arrays.npz", two_theta_grid=analysis.two_theta_grid,
             intensity_profile=analysis.intensity_profile)


def tensor_from_dict(payload: dict[str, Any] | None) -> ElasticTensor | None:
    if payload is None:
        return None
    values = dict(payload)
    values["stiffness_GPa"] = np.asarray(values["stiffness_GPa"], dtype=float)
    if values.get("raw_payload_path"):
        values["raw_payload_path"] = Path(values["raw_payload_path"])
    return ElasticTensor(**values)


def load_analysis(directory: Path, *, cif_path: Path | None = None) -> PhaseAnalysis:
    verify_checkpoint(directory)
    data = read_json(directory / "analysis.json")
    structure = data.pop("structure")
    old_path = Path(structure["cif_path"])
    structure["cif_path"] = cif_path or old_path
    structure["cell_parameters"] = tuple(structure["cell_parameters"])
    result = PhaseAnalysis(
        structure=StructureRecord(**structure),
        reflections=[ReflectionRecord(**row) for row in data.pop("reflections")],
        elastic_tensor=tensor_from_dict(data.pop("elastic_tensor")),
        two_theta_grid=np.array([]), intensity_profile=np.array([]), **data,
    )
    with np.load(directory / "arrays.npz", allow_pickle=False) as arrays:
        result.two_theta_grid = arrays["two_theta_grid"]
        result.intensity_profile = arrays["intensity_profile"]
    if cif_path is not None:
        from ..pipeline import _rebind_metadata_paths
        result.structure.source_metadata = _rebind_metadata_paths(result.structure.source_metadata, old_path.parent, cif_path.parent)
        result.metadata = _rebind_metadata_paths(result.metadata, old_path.parent, cif_path.parent)
        if result.elastic_tensor and result.elastic_tensor.raw_payload_path:
            result.elastic_tensor.raw_payload_path = cif_path.parent / result.elastic_tensor.raw_payload_path.name
    return result
