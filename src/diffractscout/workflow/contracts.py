"""Strict workflow requests and local, side-effect-free execution planning.

Planning deliberately never constructs a provider or calls an execution helper.
The existing scientific validators remain the authority for numerical settings.
"""

from __future__ import annotations

import copy
import importlib.util
import math
import os
import types
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, Mapping, Union, get_args, get_origin, get_type_hints

from ..models import AnalysisSettings, DiscoverySettings, ElasticTensor

REQUEST_SCHEMA = "diffractscout_workflow_v1"
WORKFLOWS = ("analyze", "discover", "run", "prepare", "prepare_analyze", "fetch", "adapt")
EXPORT_DEFAULTS = {"include_excel": True, "template": "full"}
EXECUTION_DEFAULTS = {
    "recursive": True,
    "overwrite": False,
    "conventional_unit_cell": True,
    "confirm_above": 200,
    "authorize_large_download": False,
    "max_attempts": 3,
}
_CHEMISTRY = ("nominal", "weight_percent", "atomic_percent")
_PREPARATION_DEFAULTS = {
    "nominal": "", "weight_percent": "", "atomic_percent": "", "host": "",
    "phases": None, "templates": {}, "parameter_file": None, "phase_parameters": None,
    "offline": False, "max_subsystems": 64, "max_prototype_attempts": 8,
    "preview_wavelength_A": 1.5406,
}
_ADAPTATION_DEFAULTS = {
    "nominal": "", "weight_percent": "", "atomic_percent": "", "citation": "",
    "a": None, "b": None, "c": None, "alpha": None, "beta": None, "gamma": None,
    "fract": {},
}
_SECRET_KEYS = {"api_key", "mp_api_key", "apikey", "password", "token", "access_token",
                "secret", "credentials", "authorization"}


def _reject_credentials(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key.lower().replace("-", "_") in _SECRET_KEYS:
                raise ValueError("Credentials must be supplied at runtime, outside the request.")
            _reject_credentials(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_credentials(item)


def _object(value: Any, name: str, allowed: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys.")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"Unknown {name} option(s): {', '.join(sorted(unknown))}.")
    return copy.deepcopy(dict(value))


def _text(value: Any, name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")


def _number(value: Any, name: str, *, positive: bool = False, integer: bool = False) -> None:
    expected = int if integer else (int, float)
    if isinstance(value, bool) or not isinstance(value, expected) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite {'integer' if integer else 'number'}.")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive.")


def _matches(value: Any, annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return any(_matches(value, item) for item in get_args(annotation))
    if origin is Literal:
        return value in get_args(annotation) and isinstance(value, str)
    if annotation is type(None):
        return value is None
    if annotation is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return type(value) is annotation


def _settings(value: Any, cls: type, name: str) -> dict[str, Any]:
    payload = _object(value, name, (item.name for item in fields(cls)))
    if cls is AnalysisSettings and "input_mode" not in payload:
        numeric = [key for key in ("energy_keV", "wavelength_A") if payload.get(key) is not None]
        if len(numeric) > 1:
            raise ValueError("Supply only one of energy_keV and wavelength_A.")
        if numeric and "source_preset" not in payload:
            payload["input_mode"] = "energy" if numeric[0] == "energy_keV" else "wavelength"
    for key, annotation in get_type_hints(cls).items():
        if key in payload and not _matches(payload[key], annotation):
            raise ValueError(f"Invalid type or value for {name}.{key}.")
    settings = cls(**payload)
    if cls is AnalysisSettings:
        from ..diffraction import validate_analysis_settings
        validate_analysis_settings(settings)
    else:
        from ..selection import validate_discovery_settings
        validate_discovery_settings(settings)
    return asdict(settings)


def _path(value: str, base_dir: str | Path | None) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir).expanduser() / path
    return str(path.resolve())


def _preparation(value: Any, base_dir: str | Path | None) -> dict[str, Any]:
    from ..initial_cifs import _validate_phase_parameters
    from ..phase_cif import canonical_phase, canonicalize_phases

    payload = _object(value, "preparation", _PREPARATION_DEFAULTS)
    for key in (*_CHEMISTRY, "host"):
        if key in payload:
            _text(payload[key], f"preparation.{key}")
    if "offline" in payload and type(payload["offline"]) is not bool:
        raise ValueError("preparation.offline must be boolean.")
    for key in ("max_subsystems", "max_prototype_attempts"):
        if key in payload:
            _number(payload[key], f"preparation.{key}", integer=True, positive=True)
    if "preview_wavelength_A" in payload:
        _number(payload["preview_wavelength_A"], "preparation.preview_wavelength_A", positive=True)
    if payload.get("phases") is not None:
        if not isinstance(payload["phases"], list) or any(not isinstance(x, str) for x in payload["phases"]):
            raise ValueError("preparation.phases must be an array of phase names.")
        payload["phases"] = list(canonicalize_phases(payload["phases"]))
    if "templates" in payload:
        templates = payload["templates"]
        if not isinstance(templates, Mapping):
            raise ValueError("preparation.templates must map phase names to paths.")
        normalized = {}
        for key, path in templates.items():
            _text(key, "template phase")
            _text(path, "template path")
            if not path.strip():
                raise ValueError("Template path must not be empty.")
            phase = canonical_phase(key)
            if phase in normalized:
                raise ValueError(f"Duplicate template for {phase}.")
            normalized[phase] = _path(path, base_dir)
        payload["templates"] = normalized
    if payload.get("parameter_file") is not None:
        _text(payload["parameter_file"], "preparation.parameter_file")
        if not payload["parameter_file"].strip():
            raise ValueError("parameter_file must not be empty.")
        payload["parameter_file"] = _path(payload["parameter_file"], base_dir)
    if payload.get("phase_parameters") is not None:
        payload["phase_parameters"] = _validate_phase_parameters(payload["phase_parameters"])
    if payload.get("parameter_file") is not None and payload.get("phase_parameters") is not None:
        raise ValueError("Use parameter_file or phase_parameters, not both.")
    return payload


def _adaptation(value: Any) -> dict[str, Any]:
    from ..phase_cif import _validate_requested_cell, _validate_requested_coordinates, resolve_occupancies

    payload = _object(value, "adaptation", _ADAPTATION_DEFAULTS)
    for key in (*_CHEMISTRY, "citation"):
        if key in payload:
            _text(payload[key], f"adaptation.{key}")
    lattice = {key: payload[key] for key in ("a", "b", "c", "alpha", "beta", "gamma")
               if payload.get(key) is not None}
    for key, item in lattice.items():
        _number(item, f"adaptation.{key}")
    coordinates = _object(payload.get("fract", {}), "adaptation.fract", ("x", "y", "z"))
    for key, item in coordinates.items():
        _number(item, f"adaptation.fract.{key}")
    _validate_requested_cell(lattice)
    _validate_requested_coordinates(coordinates)
    if (lattice or coordinates) and not payload.get("citation", "").strip():
        raise ValueError("Lattice or fractional coordinate changes require a citation.")
    chemistry = {key: payload.get(key, "") for key in _CHEMISTRY}
    if any(chemistry.values()):
        from ..cif_quality import INTERSTITIALS
        _, _, occupancies = resolve_occupancies(**chemistry)
        if set(occupancies) & INTERSTITIALS:
            raise ValueError("Adaptation cannot substitute interstitial percentages onto metal sites.")
    return payload


def _elastic_overrides(value: Any, base_dir: str | Path | None) -> dict[str, Any]:
    from ..elasticity import validate_elastic_tensor
    from ..utils import to_jsonable

    if not isinstance(value, Mapping):
        raise ValueError("elastic_overrides must be an object.")
    output = {}
    tensor_fields = {item.name for item in fields(ElasticTensor)}
    for key, raw in value.items():
        _text(key, "elastic override key")
        payload = asdict(raw) if isinstance(raw, ElasticTensor) else _object(raw, "elastic tensor", tensor_fields)
        if "stiffness_GPa" not in payload:
            raise ValueError("Elastic tensor requires stiffness_GPa.")
        if payload.get("unit", "GPa") != "GPa":
            raise ValueError("stiffness_GPa must use GPa units.")
        for name in tensor_fields - {"stiffness_GPa", "warnings", "raw_payload_path"}:
            if name in payload:
                _text(payload[name], f"elastic tensor.{name}")
        if "warnings" in payload and (not isinstance(payload["warnings"], list) or any(
            not isinstance(item, str) for item in payload["warnings"]
        )):
            raise ValueError("Elastic tensor warnings must be an array of strings.")
        metadata = {name: payload[name] for name in (
            "source_provider", "source_record_id", "source_url", "methodology_url",
            "nature_of_data", "coordinate_frame",
        ) if name in payload}
        if payload.get("raw_payload_path") is not None:
            raw_path = payload["raw_payload_path"]
            if not isinstance(raw_path, (str, Path)):
                raise ValueError("raw_payload_path must be a path.")
            metadata["raw_payload_path"] = Path(_path(str(raw_path), base_dir))
        tensor = validate_elastic_tensor(payload["stiffness_GPa"], **metadata)
        if tensor.status == "invalid":
            raise ValueError("Invalid elastic tensor: " + "; ".join(tensor.warnings))
        normalized_key = _path(key, base_dir) if Path(key).is_absolute() or "/" in key or "\\" in key else key
        output[normalized_key] = to_jsonable(asdict(tensor))
    return output


@dataclass
class WorkflowRequest:
    workflow: str
    schema: str = REQUEST_SCHEMA
    name: str = ""
    inputs: list[str] = field(default_factory=list)
    composition: str = ""
    analysis: dict[str, Any] = field(default_factory=dict)
    discovery: dict[str, Any] = field(default_factory=dict)
    preparation: dict[str, Any] = field(default_factory=dict)
    adaptation: dict[str, Any] = field(default_factory=dict)
    exports: dict[str, Any] = field(default_factory=lambda: dict(EXPORT_DEFAULTS))
    execution: dict[str, Any] = field(default_factory=lambda: dict(EXECUTION_DEFAULTS))
    output_dir: str | None = None
    experiment: str = "laboratory"
    submission_id: str | None = None
    parent_run_id: str | None = None
    elastic_overrides: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any], base_dir: str | Path | None = None) -> WorkflowRequest:
        _reject_credentials(mapping)
        payload = _object(mapping, "request", (item.name for item in fields(cls)))
        if payload.get("schema", REQUEST_SCHEMA) != REQUEST_SCHEMA:
            raise ValueError(f"Request schema must be {REQUEST_SCHEMA!r}.")
        if payload.get("workflow") not in WORKFLOWS:
            raise ValueError(f"workflow must be one of {', '.join(WORKFLOWS)}.")
        for key in ("name", "composition"):
            if key in payload:
                _text(payload[key], key)
        for key in ("submission_id", "parent_run_id", "output_dir"):
            if key in payload:
                _text(payload[key], key, nullable=True)
        if payload.get("experiment", "laboratory") not in ("laboratory", "synchrotron"):
            raise ValueError("experiment must be laboratory or synchrotron.")
        inputs = payload.get("inputs", [])
        if not isinstance(inputs, list) or any(not isinstance(item, str) or not item.strip() for item in inputs):
            raise ValueError("inputs must be an array of non-empty paths.")
        payload["inputs"] = [_path(item, base_dir) for item in inputs]
        if payload.get("output_dir") is not None:
            if not payload["output_dir"].strip():
                raise ValueError("output_dir must not be empty.")
            target = Path(payload["output_dir"]).expanduser()
            if not target.is_absolute() and base_dir is not None:
                target = Path(base_dir) / target
            # Preserve reparse/symlink components for the output validator.
            payload["output_dir"] = os.path.abspath(target)
        payload["analysis"] = _settings(payload.get("analysis", {}), AnalysisSettings, "analysis")
        payload["discovery"] = _settings(payload.get("discovery", {}), DiscoverySettings, "discovery")
        payload["preparation"] = _preparation(payload.get("preparation", {}), base_dir)
        payload["adaptation"] = _adaptation(payload.get("adaptation", {}))
        exports = {**EXPORT_DEFAULTS, **_object(payload.get("exports", {}), "exports", EXPORT_DEFAULTS)}
        if type(exports["include_excel"]) is not bool:
            raise ValueError("exports.include_excel must be boolean.")
        if exports["template"] not in ("full", "peak_table"):
            raise ValueError("exports.template must be full or peak_table.")
        payload["exports"] = exports
        execution = {**EXECUTION_DEFAULTS, **_object(payload.get("execution", {}), "execution", EXECUTION_DEFAULTS)}
        for key, default in EXECUTION_DEFAULTS.items():
            if isinstance(default, bool):
                if type(execution[key]) is not bool:
                    raise ValueError(f"execution.{key} must be boolean.")
            else:
                _number(execution[key], f"execution.{key}", integer=True, positive=True)
        payload["execution"] = execution
        if execution["max_attempts"] > 3:
            raise ValueError("execution.max_attempts must be between 1 and 3.")
        payload["elastic_overrides"] = _elastic_overrides(payload.get("elastic_overrides", {}), base_dir)
        result = cls(**payload)
        result._provided_fields = {
            section: set(mapping.get(section, {})) for section in ("analysis", "discovery", "preparation", "exports", "execution")
        }
        return result

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionableDiagnostic:
    code: str
    message: str
    stage: str = "planning"
    item: str = ""
    retryable: bool = False
    missing_fields: list[str] = field(default_factory=list)
    level: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _available(module: str) -> bool:
    # Inspect the top-level spec only: dotted find_spec imports parent packages.
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _validate_preparation_template(path: str, phase: str, host: str) -> None:
    """Check either an explicit phase model or the supported P1 restoration case."""
    from ..cif_quality import _check_topology, _dataset, _spglib_cell, validate_phase_model
    from ..structure import load_structure

    loaded = load_structure(path)
    if loaded.space_group_number != 1:
        validate_phase_model(path, phase, host=host)
        return
    cell, fingerprints = _spglib_cell(loaded.small_structure)
    dataset = _dataset(cell)
    _check_topology(dataset, phase)
    _check_topology(_dataset((dataset.std_lattice, dataset.std_positions, dataset.std_types)), phase)
    present = {element for fingerprint in fingerprints.values() for element, _ in fingerprint}
    if host and host not in present:
        raise ValueError(f"The prototype does not contain host {host}.")


def context() -> dict[str, Any]:
    """Describe local capabilities without importing optional packages or networking."""
    return {
        "schema": REQUEST_SCHEMA,
        "workflows": list(WORKFLOWS),
        "request_schema": "request",
        "credentials": {"environment": "MP_API_KEY", "configured": bool(os.environ.get("MP_API_KEY", "").strip()),
                        "request_storage": False},
        "dependencies": {name: _available(module) for name, module in {
            "gemmi": "gemmi", "numpy": "numpy", "pandas": "pandas", "openpyxl": "openpyxl",
            "spglib": "spglib", "mp-api": "mp_api", "pymatgen": "pymatgen", "matplotlib": "matplotlib",
        }.items()},
        "planning": {"network": False, "writes": False},
    }


def plan_workflow(request: WorkflowRequest | Mapping[str, Any], *, provider: Any = None,
                  api_key: str | None = None) -> dict[str, Any]:
    """Validate readiness using local metadata only; injected providers are never called."""
    if api_key is not None and not isinstance(api_key, str):
        raise ValueError("Runtime api_key must be text.")
    provided = getattr(request, "_provided_fields", None)
    request = WorkflowRequest.from_dict(request.to_dict() if isinstance(request, WorkflowRequest) else request)
    provided = provided or request._provided_fields
    diagnostics: list[dict[str, Any]] = []

    def diagnostic(code: str, message: str, stage: str = "planning", item: str = "",
                   missing_fields: list[str] | None = None) -> None:
        diagnostics.append(ActionableDiagnostic(code, message, stage, item,
                                                missing_fields=missing_fields or []).to_dict())

    stages = {
        "analyze": ["analyze", "export", "verify"],
        "discover": ["discover", "export", "verify"],
        "run": ["discover", "download", "analyze", "export", "verify"],
        "prepare": ["prepare", "verify"],
        "prepare_analyze": ["prepare", "analyze", "export", "verify"],
        "fetch": ["fetch", "verify"],
        "adapt": ["adapt", "verify"],
    }[request.workflow]
    needs_analysis = "analyze" in stages
    if needs_analysis and request.experiment == "synchrotron" and not (
        request.analysis["wavelength_A"] is not None or request.analysis["energy_keV"] is not None
    ):
        diagnostic("missing_radiation", "Synchrotron analysis requires an explicit wavelength_A or energy_keV.",
                   "analyze", missing_fields=["analysis.wavelength_A", "analysis.energy_keV"])
    sources = list(request.inputs)
    local_cifs: list[str] = []
    if request.workflow in ("analyze", "adapt"):
        if not sources:
            diagnostic("missing_inputs", "Provide local CIF input paths.", request.workflow, missing_fields=["inputs"])
        else:
            from ..pipeline import collect_cif_paths
            if request.workflow == "adapt" and (len(sources) != 1 or not Path(sources[0]).is_file()):
                diagnostic("invalid_inputs", "Adapt requires exactly one local CIF file.", "adapt", "inputs")
            try:
                local_cifs = [str(path) for path in collect_cif_paths(sources, recursive=request.execution["recursive"])]
                if not local_cifs:
                    diagnostic("no_cifs", "No CIF files were found in the supplied inputs.", request.workflow, "inputs")
            except (OSError, ValueError) as exc:
                diagnostic("invalid_inputs", str(exc), request.workflow, "inputs")
    options = {**_PREPARATION_DEFAULTS, **request.preparation}
    templates = options["templates"]
    sources.extend(templates.values())
    if options["parameter_file"]:
        sources.append(options["parameter_file"])
    if request.output_dir:
        from ..pipeline import _reject_reparse_components, _validate_input_output_separation
        try:
            _reject_reparse_components(Path(request.output_dir), label="workflow output")
            _validate_input_output_separation(sources, request.output_dir)
            target = Path(request.output_dir)
            if target.exists() and (not target.is_dir() or (
                any(target.iterdir()) and not request.execution["overwrite"]
            )):
                diagnostic("output_exists", "Choose a new output directory; the target is already occupied.", item="output_dir")
            if target.exists() and request.workflow in ("prepare", "prepare_analyze"):
                diagnostic("output_exists", "Preparation requires a new output directory.", "prepare", "output_dir")
            if (target.is_dir() and any(target.iterdir()) and request.execution["overwrite"]
                    and request.workflow in ("analyze", "discover", "run")):
                from ..validation import verify_bundle
                verification = verify_bundle(target)
                if not verification["ok"]:
                    diagnostic("unsafe_overwrite", "The existing output is not an intact DiffractScout bundle.", item="output_dir")
        except (OSError, ValueError) as exc:
            diagnostic("unsafe_output", str(exc), item="output_dir")
    estimated_queries = 0
    requires_provider = request.workflow in ("discover", "run")
    parameter_sources: dict[str, Any] = {
        "analysis": {key: "request" if key in provided["analysis"] else "default" for key in request.analysis},
        "discovery": {key: "request" if key in provided["discovery"] else "default" for key in request.discovery},
        "radiation": request.analysis["input_mode"],
        "output": "request.output_dir" if request.output_dir else "managed per-run bundle",
    }
    if "input_mode" not in provided["analysis"]:
        for field_name in ("energy_keV", "wavelength_A"):
            if field_name in provided["analysis"] and request.analysis[field_name] is not None:
                parameter_sources["analysis"]["input_mode"] = "derived_from_" + field_name
    parsed = None
    if request.workflow in ("discover", "run", "prepare", "prepare_analyze", "fetch"):
        from ..composition import parse_composition_text
        try:
            parsed = parse_composition_text(request.composition)
            if not parsed.elements and not parsed.material_ids:
                diagnostic("missing_composition", "Provide a chemical composition or material IDs.",
                           request.workflow, missing_fields=["composition"])
        except ValueError as exc:
            diagnostic("invalid_composition", str(exc), request.workflow, "composition")
    if parsed is not None and request.workflow in ("discover", "run"):
        mode = request.discovery["mode"]
        if mode == "mpids_only" or (parsed.material_ids and not parsed.elements and mode == "possible_phases"):
            estimated_queries = int(bool(parsed.material_ids))
            if not parsed.material_ids:
                diagnostic("missing_material_ids", "mpids_only requires material IDs.", "discover", "composition")
        elif not parsed.elements:
            diagnostic("missing_elements", "Element-based discovery requires parsed elements.", "discover", "composition")
        else:
            count = len(parsed.elements)
            upper = min(count, request.discovery["max_subsystem_order"] or count)
            estimated_queries = (1 if mode == "single_chemsys" else sum(math.comb(count, order) for order in range(1, upper + 1)))
            if mode != "single_chemsys" and estimated_queries > request.discovery["max_subsystems"]:
                diagnostic("query_limit", "Chemical-subsystem expansion exceeds discovery.max_subsystems.", "discover", "discovery.max_subsystems")
            estimated_queries += int(bool(parsed.material_ids))
    if request.workflow in ("prepare", "prepare_analyze", "fetch"):
        from ..initial_cifs import _resolve_request, read_phase_parameters
        from ..phase_cif import canonicalize_phases
        selected = canonicalize_phases(options["phases"])
        missing = set(selected) - set(templates)
        parameters = options["phase_parameters"] or {}
        try:
            if options["parameter_file"]:
                parameters = read_phase_parameters(options["parameter_file"])
            if set(parameters) - set(selected) or set(templates) - set(selected):
                raise ValueError("Templates and phase parameters must use selected phases.")
            for path in templates.values():
                if not Path(path).is_file():
                    raise FileNotFoundError(f"Template CIF not found: {path}")
            if request.workflow != "fetch":
                elements, host, chemistry = _resolve_request(
                    request.composition, {key: options[key] for key in _CHEMISTRY}, options["host"], parameters,
                )
                parameter_sources["preparation"] = {
                    "host": host, "chemistry": chemistry,
                    "phase_parameters": options["parameter_file"] or ("request" if parameters else "prototype"),
                    "templates": dict(templates),
                }
                # Packaged fallback is defined by the current preparation implementation.
                # Availability is not a claim that arbitrary chemistry has a valid prototype.
                requires_provider = bool(missing and host != "Ti" and not options["offline"])
                if missing and options["offline"] and host != "Ti":
                    diagnostic("missing_templates", "Offline preparation requires caller templates for this host.", "prepare", "preparation.templates")
                will_query = bool(missing and not options["offline"] and (
                    provider is not None or api_key or os.environ.get("MP_API_KEY") or requires_provider
                ))
            else:
                elements = parsed.elements if parsed else ()
                if not elements:
                    raise ValueError("fetch requires a composition containing elements.")
                host = options["host"] or elements[0]
                if host not in elements:
                    raise ValueError("Host must be an element in the requested composition.")
                requires_provider = bool(missing - {"alpha-double-prime"})
                will_query = bool(missing and (requires_provider or provider is not None or api_key or os.environ.get("MP_API_KEY")))
            if will_query:
                estimated_queries = (1 << len(elements)) - 1
                if estimated_queries > options["max_subsystems"]:
                    diagnostic("query_limit", "Chemical-subsystem expansion exceeds preparation.max_subsystems.", request.workflow, "preparation.max_subsystems")
            # Supplied templates can be checked locally, with no normalization writes.
            for phase, path in templates.items():
                if request.workflow == "fetch":
                    from ..phase_cif import _read_cif_identity
                    _read_cif_identity(Path(path))
                else:
                    _validate_preparation_template(path, phase, host)
        except (OSError, ValueError) as exc:
            diagnostic("invalid_preparation", str(exc), request.workflow, "preparation")
    if request.workflow == "adapt":
        from ..phase_cif import resolve_occupancies
        try:
            resolve_occupancies(**{key: request.adaptation.get(key, "") for key in _CHEMISTRY})
        except ValueError as exc:
            diagnostic("invalid_adaptation", str(exc), "adapt", "adaptation")
    dependencies = context()["dependencies"]
    required = ["gemmi", "numpy", "spglib"]
    if needs_analysis or request.workflow == "discover":
        required.append("pandas")
        if request.exports["include_excel"]:
            required.append("openpyxl")
        if needs_analysis and request.analysis["include_figures"]:
            required.append("matplotlib")
    # Optional provider dependencies are required only for live database work.
    if requires_provider and provider is None:
        required.extend(("mp-api", "pymatgen"))
        if not (api_key or os.environ.get("MP_API_KEY", "")).strip():
            diagnostic("missing_credentials", "Materials Project credentials are required at runtime.", request.workflow,
                       missing_fields=["MP_API_KEY"])
    for dependency in required:
        if not dependencies[dependency]:
            diagnostic("missing_dependency", f"Required dependency is unavailable: {dependency}.", item=dependency)
    return {
        "ready": not diagnostics, "request": request.to_dict(), "stages": stages,
        "diagnostics": diagnostics, "estimated_queries": estimated_queries,
        "required_dependencies": required, "parameter_sources": parameter_sources,
        "local_cifs": local_cifs,
    }


def _annotation_schema(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return {"anyOf": [_annotation_schema(item) for item in get_args(annotation)]}
    if origin is Literal:
        return {"type": "string", "enum": list(get_args(annotation))}
    return {"type": {str: "string", float: "number", int: "integer", bool: "boolean", type(None): "null"}[annotation]}


def _settings_schema(cls: type) -> dict[str, Any]:
    defaults = asdict(cls())
    hints = get_type_hints(cls)
    properties = {key: {**_annotation_schema(hints[key]), "default": default} for key, default in defaults.items()}
    return {"type": "object", "additionalProperties": False, "properties": properties, "default": {}}


def schema(name: str = "request") -> dict[str, Any]:
    """Return the JSON Schema for the supported request contract."""
    if name not in ("request", REQUEST_SCHEMA):
        raise ValueError(f"Unknown schema {name!r}; use 'request'.")
    string = {"type": "string"}
    nullable_string = {"type": ["string", "null"], "default": None}
    number = {"type": "number"}
    phase_properties = {
        "lattice": {"type": "object", "additionalProperties": False, "properties": {key: number for key in ("a", "b", "c", "alpha", "beta", "gamma")}},
        "fract": {"type": "object", "additionalProperties": False, "properties": {key: number for key in ("x", "y", "z")}},
        **{key: string for key in (*_CHEMISTRY, "citation", "conditions")},
    }
    preparation_properties = {
        **{key: {"type": "string", "default": ""} for key in (*_CHEMISTRY, "host")},
        "phases": {"type": ["array", "null"], "items": string, "default": None},
        "templates": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1}, "default": {}},
        "parameter_file": nullable_string,
        "phase_parameters": {"type": ["object", "null"], "additionalProperties": {"type": "object", "additionalProperties": False, "properties": phase_properties}, "default": None},
        "offline": {"type": "boolean", "default": False},
        "max_subsystems": {"type": "integer", "minimum": 1, "default": 64},
        "max_prototype_attempts": {"type": "integer", "minimum": 1, "default": 8},
        "preview_wavelength_A": {"type": "number", "exclusiveMinimum": 0, "default": 1.5406},
    }
    adaptation_properties = {
        **{key: {"type": "string", "default": ""} for key in (*_CHEMISTRY, "citation")},
        **{key: {"type": ["number", "null"], "default": None} for key in ("a", "b", "c", "alpha", "beta", "gamma")},
        "fract": phase_properties["fract"],
    }
    tensor_properties = {key: string for key in ("source_provider", "source_record_id", "source_url", "methodology_url", "nature_of_data", "coordinate_frame", "unit", "status")}
    tensor_properties.update({
        "stiffness_GPa": {"type": "array", "minItems": 6, "maxItems": 6, "items": {"type": "array", "minItems": 6, "maxItems": 6, "items": number}},
        "warnings": {"type": "array", "items": string}, "raw_payload_path": nullable_string,
    })
    properties = {
        "schema": {"type": "string", "const": REQUEST_SCHEMA, "default": REQUEST_SCHEMA},
        "workflow": {"type": "string", "enum": list(WORKFLOWS)},
        "name": {"type": "string", "default": ""}, "composition": {"type": "string", "default": ""},
        "inputs": {"type": "array", "items": {"type": "string", "minLength": 1}, "default": []},
        "output_dir": nullable_string, "submission_id": nullable_string, "parent_run_id": nullable_string,
        "experiment": {"type": "string", "enum": ["laboratory", "synchrotron"], "default": "laboratory"},
        "analysis": _settings_schema(AnalysisSettings), "discovery": _settings_schema(DiscoverySettings),
        "preparation": {"type": "object", "additionalProperties": False, "properties": preparation_properties, "default": {}},
        "adaptation": {"type": "object", "additionalProperties": False, "properties": adaptation_properties, "default": {}},
        "exports": {"type": "object", "additionalProperties": False, "properties": {
            "include_excel": {"type": "boolean", "default": True}, "template": {"type": "string", "enum": ["full", "peak_table"], "default": "full"},
        }, "default": dict(EXPORT_DEFAULTS)},
        "execution": {"type": "object", "additionalProperties": False, "properties": {
            key: {"type": "boolean" if isinstance(default, bool) else "integer", "default": default,
                  **({} if isinstance(default, bool) else {"minimum": 1}),
                  **({"maximum": 3} if key == "max_attempts" else {})} for key, default in EXECUTION_DEFAULTS.items()
        }, "default": dict(EXECUTION_DEFAULTS)},
        "elastic_overrides": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": False, "required": ["stiffness_GPa"], "properties": tensor_properties}, "default": {}},
    }
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": REQUEST_SCHEMA,
            "type": "object", "additionalProperties": False, "required": ["workflow"], "properties": properties}
