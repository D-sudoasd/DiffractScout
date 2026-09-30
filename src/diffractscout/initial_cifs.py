"""Prepare traceable, validated initial CIFs for subsequent refinement.

Literature searches remain outside the calculation package. Caller-supplied
phase parameters take precedence over bulk composition and prototype lattice
values, with each assumption retained in the delivery report.
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping, Sequence

from .cif_quality import INTERSTITIALS, normalize_prototype, validate_phase_model, write_clean_model
from .composition import chemsys_subsystems, normalize_element, parse_composition_text
from .diffraction import simulate_powder_pattern, validate_analysis_settings
from .models import AnalysisSettings, CandidateRecord
from .phase_cif import (
    adapt_cif,
    canonical_phase,
    canonicalize_phases,
    parse_template_assignments,
    rank_prototypes,
    resolve_occupancies,
)
from .structure import structure_mass_metadata
from .utils import package_versions, sha256_file, to_jsonable, utc_now_iso, write_json
from .validation import verify_bundle

_PARAMETER_SCHEMA = "diffractscout_phase_parameters_v1"
_INDEPENDENT_AXES = {"alpha": ("a", "c"), "beta": ("a",), "alpha-double-prime": ("a", "b", "c")}
_PACKAGED = {
    "alpha": (
        "cod_1522498_ti_nb_hcp.cif",
        "COD 1522498",
        "McHargue et al. (1953); Ti–2.6 at% Nb hcp scaffold.",
    ),
    "beta": (
        "cod_9008554_beta_ti.cif",
        "COD 9008554 / AMCSD 0011232",
        "Wyckoff (1963); elemental beta Ti at 1173 K. Source temperature is not the target condition.",
    ),
    "alpha-double-prime": (
        "cod_1523304_ti_nb_cmcm.cif",
        "COD 1523304",
        "Brown et al. (1964); Ti–20 at% Nb Cmcm scaffold; internal y=0.20 is inherited.",
    ),
}
_BULK_WARNING = "Bulk/nominal composition is a uniform substitutional starting assumption, not the measured composition of this phase. Equilibrium partitioning is not inferred."


@dataclass(frozen=True)
class InitialCifRecord:
    phase: str
    status: str
    cif_path: Path | None
    note: str


@dataclass(frozen=True)
class PrepareCifsResult:
    output_dir: Path
    report_path: Path
    index_path: Path
    manifest_path: Path
    records: tuple[InitialCifRecord, ...]

    @property
    def exit_code(self) -> int:
        usable = sum(record.cif_path is not None for record in self.records)
        return 0 if usable == len(self.records) and usable else 3 if usable else 2


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"Duplicate parameter key {key!r}.")
        output[key] = value
    return output


def read_phase_parameters(path: str | Path) -> dict[str, dict]:
    """Read strict JSON, rejecting unknown/duplicate keys before output creation."""
    payload = json.loads(
        Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_no_duplicate_keys
    )
    if not isinstance(payload, dict) or payload.get("schema") != _PARAMETER_SCHEMA:
        raise ValueError(f"Phase parameter file must use schema {_PARAMETER_SCHEMA!r}.")
    if set(payload) - {"schema", "phases"}:
        raise ValueError("Unknown top-level phase parameter fields.")
    return _validate_phase_parameters(payload.get("phases"))


def _validate_phase_parameters(payload: Any) -> dict[str, dict]:
    if not isinstance(payload, Mapping):
        raise ValueError("Phase parameters 'phases' must be an object.")
    output = {}
    allowed = {
        "lattice",
        "fract",
        "citation",
        "conditions",
        "nominal",
        "weight_percent",
        "atomic_percent",
    }
    for raw_phase, raw in payload.items():
        phase = canonical_phase(str(raw_phase))
        if phase in output:
            raise ValueError(f"Repeated phase {phase} through aliases.")
        if not isinstance(raw, Mapping) or set(raw) - allowed:
            raise ValueError(f"Unknown or invalid parameter fields for {phase}.")
        parameters = dict(raw)
        for field in ("citation", "conditions", "nominal", "weight_percent", "atomic_percent"):
            if field in parameters and not isinstance(parameters[field], str):
                raise ValueError(f"{phase}.{field} must be text.")
        for field, keys in (
            ("lattice", {"a", "b", "c", "alpha", "beta", "gamma"}),
            ("fract", {"x", "y", "z"}),
        ):
            values = parameters.get(field, {})
            if not isinstance(values, Mapping) or set(values) - keys:
                raise ValueError(f"Unknown {field} axes for {phase}.")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in values.values()
            ):
                raise ValueError(f"{phase}.{field} must contain numeric values.")
            # Reuse adapt's boundary checks without writing an output.
            from .phase_cif import _validate_requested_cell, _validate_requested_coordinates

            (_validate_requested_cell if field == "lattice" else _validate_requested_coordinates)(
                values
            )
        if (parameters.get("lattice") or parameters.get("fract")) and not parameters.get(
            "citation", ""
        ).strip():
            raise ValueError(f"{phase} lattice/coordinate parameters require a citation.")
        chemistry = _chemistry_options(parameters)
        if any(chemistry.values()):
            resolve_occupancies(**chemistry)
        output[phase] = parameters
    return output


def _chemistry_options(values: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: str(values.get(key, "")) for key in ("nominal", "weight_percent", "atomic_percent")
    }


def _resolve_request(
    composition: str, chemistry: dict[str, str], host: str, parameters: dict
) -> tuple[tuple[str, ...], str, dict[str, str]]:
    elements = parse_composition_text(composition).elements
    if not elements:
        raise ValueError("prepare-cifs requires a chemical system or a known alloy grade.")
    if not any(chemistry.values()):
        alias = re.sub(r"[\s–—−-]+", "", composition.lower())
        if alias in {"tc4", "ti64", "ti6al4v"}:
            chemistry["nominal"] = "tc4"
        elif len(elements) == 1:
            chemistry["atomic_percent"] = f"{elements[0]}=100"
    occupancies = {}
    if any(chemistry.values()):
        _basis, _note, occupancies = resolve_occupancies(**chemistry)
        if set(occupancies) & INTERSTITIALS:
            raise ValueError(
                "Initial CIF composition describes the substitutional metal lattice; interstitials require an explicit site model."
            )
        if set(occupancies) != set(elements):
            raise ValueError("Bulk composition elements must match the requested chemical system.")
    if host:
        host = normalize_element(host) or ""
        if host not in elements:
            raise ValueError("Host must be an element in the requested chemical system.")
    elif occupancies:
        largest = max(occupancies.values())
        dominant = [element for element, value in occupancies.items() if value == largest]
        if len(dominant) != 1:
            raise ValueError(
                "Equal major atomic fractions: specify --host to choose the parent lattice."
            )
        host = dominant[0]
    else:
        raise ValueError(
            "Provide --nominal, --wt or --at and, if needed, --host. Element names alone do not specify alloy percentages."
        )
    for phase, values in parameters.items():
        overrides = _chemistry_options(values)
        if any(overrides.values()):
            _basis, _note, fractions = resolve_occupancies(**overrides)
            if set(fractions) & INTERSTITIALS:
                raise ValueError(
                    f"{phase} interstitial composition requires an explicit site model."
                )
            if not set(fractions) <= set(elements) or host not in fractions:
                raise ValueError(
                    f"{phase} composition must contain host {host} and only requested elements."
                )
    return elements, host, chemistry


def _query_candidates(
    provider: Any,
    elements: tuple[str, ...],
    host: str,
    phases: tuple[str, ...],
    max_subsystems: int,
) -> tuple[list[CandidateRecord], list[dict]]:
    if isinstance(max_subsystems, bool) or max_subsystems <= 0:
        raise ValueError("max_subsystems must be a positive integer.")
    # Check the count before constructing the exponentially growing list.
    if (1 << len(elements)) - 1 > max_subsystems:
        raise ValueError(f"Chemical system exceeds --max-subsystems {max_subsystems}.")
    found: dict[str, CandidateRecord] = {}
    queries = []
    systems = [host, *[system for system in chemsys_subsystems(elements) if system != host]]
    for system in systems:
        if system != host and all(
            rank_prototypes(list(found.values()), phase=phase, elements=elements, host=host)
            for phase in phases
        ):
            break
        candidates = provider.search_subsystem(
            system, e_hull_max_eV_atom=None, exclude_deprecated=True
        )
        queries.append({"chemsys": system, "candidate_count": len(candidates)})
        for candidate in candidates:
            found.setdefault(candidate.material_id, candidate)
    return list(found.values()), queries


def _acquire_prototype(
    phase: str,
    staging: Path,
    *,
    template: Path | None,
    candidates: list[CandidateRecord],
    provider: Any,
    elements: tuple[str, ...],
    host: str,
    max_prototype_attempts: int,
) -> tuple[Path, dict]:
    raw_path = staging / "sources" / f"{phase}.cif"
    model_path = staging / "prototypes" / f"{phase}.cif"
    attempts: list[dict] = []
    options: list[tuple[str, Any]] = []
    shortlist = (
        rank_prototypes(candidates, phase=phase, elements=elements, host=host)
        if template is None
        else []
    )
    if template is not None:
        options.append(("template", template))
    else:
        options.extend(
            ("Materials Project", candidate) for candidate in shortlist[:max_prototype_attempts]
        )
        if host == "Ti":
            options.append(("packaged_scaffold", _PACKAGED[phase]))
    for origin, option in options:
        try:
            identity = {}
            if origin == "template":
                raw_path.write_bytes(option.read_bytes())
                identity = {
                    "source": "caller_template",
                    "source_filename": option.name,
                    "note": "Caller-supplied prototype; target lattice and site preference are not inferred.",
                }
            elif origin == "packaged_scaffold":
                filename, source, note = option
                raw_path.write_bytes(
                    files("diffractscout").joinpath("prototype_data", filename).read_bytes()
                )
                identity = {"source": source, "note": note}
            else:
                with tempfile.TemporaryDirectory(prefix="mp-prototype-") as download_dir:
                    artifacts = provider.download_candidates(
                        [option],
                        Path(download_dir),
                        conventional_unit_cell=True,
                        include_elasticity=False,
                    )
                    artifact = next(
                        (
                            item
                            for item in artifacts
                            if item.candidate.material_id == option.material_id
                            and item.status == "ok"
                            and item.cif_path is not None
                        ),
                        None,
                    )
                    if artifact is None:
                        raise ValueError("Provider did not return a usable CIF for this candidate.")
                    raw_path.write_bytes(Path(artifact.cif_path).read_bytes())
                identity = {
                    "source": "Materials Project",
                    "candidate": to_jsonable(option),
                    "note": "DFT/database parent prototype; its lattice is not a target-alloy measurement.",
                }
            audit = normalize_prototype(raw_path, model_path, phase, host=host)
            return model_path, {
                **identity,
                **audit,
                "source_cif": raw_path.relative_to(staging).as_posix(),
                "source_sha256": sha256_file(raw_path),
                "prototype_cif": model_path.relative_to(staging).as_posix(),
                "prototype_sha256": sha256_file(model_path),
                "selection_attempts": attempts,
                "shortlisted_candidate_count": len(shortlist),
                "attempted_database_candidates": sum(
                    item["source"] == "Materials Project" for item in attempts
                )
                + int(origin == "Materials Project"),
                "untried_candidate_count": len(shortlist)
                - sum(item["source"] == "Materials Project" for item in attempts)
                - int(origin == "Materials Project"),
                "prototype_attempt_limit": max_prototype_attempts,
                "selection_rule": "Caller template first; otherwise elemental host, energy and id shortlist, then atom-level symmetry and single-orbit validation; Ti scaffold fallback.",
            }
        except Exception as exc:
            attempts.append(
                {
                    "source": origin,
                    "material_id": getattr(option, "material_id", ""),
                    "status": "rejected",
                    "reason": str(exc),
                }
            )
            raw_path.unlink(missing_ok=True)
            model_path.unlink(missing_ok=True)
    raise ValueError(
        f"No validated {phase} prototype for host {host}. Untried database candidates: {max(0, len(shortlist) - max_prototype_attempts)}. Attempts: {attempts or 'no eligible candidate or local template'}"
    )


def _redact_text(value: Any, key: str | Sequence[str]) -> Any:
    if isinstance(value, str):
        for secret in [key] if isinstance(key, str) else key:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {name: _redact_text(item, key) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_text(item, key) for item in value]
    return value


def _write_csv(path: Path, fields: Sequence[str], rows: list[dict]) -> None:
    from .exporters import _safe_spreadsheet_text

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(
            {
                key: _safe_spreadsheet_text(value)
                if isinstance(value := row.get(key, ""), str)
                else value
                for key in fields
            }
            for row in rows
        )


def _write_report(
    staging: Path, composition: str, host: str, records: list[dict], wavelength: float
) -> None:
    lines = [
        "# 初始 CIF 使用说明 / Initial CIF guide",
        "",
        f"体系：{composition}；母相宿主：{host}。",
        "",
        "`initial/` 中的 CIF 已通过读取、空间群、单一金属轨道及占位检查，可作为后续拟合的初始模型。",
        "模型的可读取性不证明相存在，也不证明晶格、相成分或内坐标符合当前样品。",
        "",
        "| 相 | 状态 | 晶格基准 | CIF |",
        "|---|---|---|---|",
    ]
    for record in records:
        lines.append(
            f"| {record['phase']} | {record['status']} | {record.get('lattice_basis', '—')} | {record.get('cif', '—')} |"
        )
    lines.extend(["", "## 逐相依据与待调整参数", ""])
    for record in records:
        lines.extend([f"### {record['phase']}", "", record["note"], ""])
        if record.get("cif"):
            lines.append(f"- 来源：{record['prototype']['source']}。{record['prototype']['note']}")
            lines.append(f"- 晶胞 a,b,c,α,β,γ：{record['cell_parameters']}（Å、°）。")
            lines.append(
                f"- 实际写入的原子分数：{record['occupancies']}；成分语义：{record['composition_role']}。"
            )
            lines.append(f"- 引用：{record['citation'] or '未提供目标相晶格引用；保留原型晶格。'}")
            lines.append(f"- 条件：{record['conditions'] or '调用者未提供测量/处理条件。'}")
            lines.append(f"- 建议拟合晶格参数：{', '.join(_INDEPENDENT_AXES[record['phase']])}。")
            if record["phase"] == "alpha-double-prime":
                lines.append(
                    "- Cmcm 的 y 控制原子位移和强度，未经该样品文献或拟合确认的 y 仍是起始假设；不能由晶格常数推断。"
                )
            for warning in record["warnings"]:
                lines.append(f"- 提醒：{warning}")
            lines.append("")
    lines.extend(
        [
            "## 文件与后续使用",
            "",
            "- `initial/`：优先载入这些派生 CIF；每份 `.adapt.json` 记录成分、晶格变更和 SHA-256。",
            "- `sources/`：原始来源 CIF；`prototypes/`：通过检查的原型。请保持这些来源文件不变。",
            "- `preparation.json`：逐相检查、选择依据、被拒候选、相成分假设及软件版本。",
            f"- `peak_preview.csv`：λ={wavelength:.8g} Å、2θ=5–120° 的理论峰表，q=2π/d；强度按每相内部归一到100。",
            "- 可用 `diffractscout analyze <本包>/initial -o <新的分析目录>` 进行完整峰表导出。",
            "- 可用 `diffractscout verify <本包>` 检查文件完整性。验证通过不等于实验或精修验收。",
            "",
            "若当前保留原型晶格，请在参数文件中填入目标合金、目标相和适用条件下的晶格及引用，再生成新目录。",
            "软件不会自动查阅论文、预测相分配或宣称该三相在样品中同时存在。",
            "",
        ]
    )
    (staging / "report.md").write_text("\n".join(lines), encoding="utf-8")


def prepare_cifs(
    composition: str,
    output_dir: str | Path,
    *,
    nominal: str = "",
    weight_percent: str = "",
    atomic_percent: str = "",
    phases: Sequence[str] | None = None,
    host: str = "",
    templates: Mapping[str, str | Path] | None = None,
    template_args: Sequence[str] | None = None,
    parameter_file: str | Path | None = None,
    phase_parameters: Mapping[str, Any] | None = None,
    offline: bool = False,
    api_key: str | None = None,
    provider: Any = None,
    max_subsystems: int = 64,
    max_prototype_attempts: int = 8,
    preview_wavelength_A: float = 1.5406,
) -> PrepareCifsResult:
    """Deliver explicit-symmetry alloy starting models in a new verified directory.

    Known Ti-6Al-4V aliases automatically use the nominal grade *in this
    preparation command only*. Global composition is a bulk assumption;
    explicit per-phase compositions override it and are recorded separately.
    No lattice values are predicted or extracted from literature.
    """
    selected = canonicalize_phases(phases)
    if parameter_file is not None and phase_parameters is not None:
        raise ValueError("Use parameter_file or phase_parameters, not both.")
    parameters = (
        read_phase_parameters(parameter_file)
        if parameter_file is not None
        else _validate_phase_parameters(phase_parameters or {})
    )
    if set(parameters) - set(selected):
        raise ValueError(
            "Parameter file includes unselected phases; select them or remove their parameters."
        )
    template_map = parse_template_assignments(template_args)
    for name, path in (templates or {}).items():
        phase = canonical_phase(name)
        if phase in template_map:
            raise ValueError(f"Duplicate template for {phase}.")
        template_map[phase] = Path(path).expanduser().resolve()
    if set(template_map) - set(selected):
        raise ValueError("Templates include unselected phases.")
    for path in template_map.values():
        if not path.is_file():
            raise FileNotFoundError(f"Template CIF not found: {path}")
    chemistry = {
        "nominal": nominal,
        "weight_percent": weight_percent,
        "atomic_percent": atomic_percent,
    }
    elements, host, chemistry = _resolve_request(composition, chemistry, host, parameters)
    if (
        isinstance(max_subsystems, bool)
        or not isinstance(max_subsystems, int)
        or max_subsystems <= 0
    ):
        raise ValueError("max_subsystems must be a positive integer.")
    if (
        isinstance(max_prototype_attempts, bool)
        or not isinstance(max_prototype_attempts, int)
        or max_prototype_attempts <= 0
    ):
        raise ValueError("max_prototype_attempts must be a positive integer.")
    preview_settings = AnalysisSettings(
        input_mode="wavelength",
        wavelength_A=preview_wavelength_A,
        include_elasticity=False,
        include_patterns=False,
    )
    validate_analysis_settings(preview_settings)
    from .pipeline import _reject_reparse_components, _rename_directory_noreplace

    target = Path(os.path.abspath(os.fspath(Path(output_dir).expanduser())))
    _reject_reparse_components(target, label="initial CIF output")
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite {target}; choose a new output directory.")
    target.parent.mkdir(parents=True, exist_ok=True)
    key = (api_key or "").strip()
    redaction_keys = [key]
    if not offline and provider is not None:
        provider_key = getattr(provider, "api_key", "")
        if isinstance(provider_key, str) and provider_key.strip():
            redaction_keys.append(provider_key.strip())
    candidates: list[CandidateRecord] = []
    query_records = []
    query_warnings = []
    query_status = "offline" if offline else "not_requested"
    missing = tuple(phase for phase in selected if phase not in template_map)
    if (
        missing
        and not offline
        and (provider is not None or key)
        and (1 << len(elements)) - 1 > max_subsystems
    ):
        raise ValueError(f"Chemical system exceeds --max-subsystems {max_subsystems}.")
    if missing and not offline and (provider is not None or key):
        try:
            if provider is None:
                from .providers.materials_project import MaterialsProjectProvider

                provider = MaterialsProjectProvider(key)
            candidates, query_records = _query_candidates(
                provider, elements, host, missing, max_subsystems
            )
            query_status = "queried"
        except Exception as exc:
            query_status = "failed"
            query_warnings.append(str(exc).replace(key, "[redacted]") if key else str(exc))
    elif missing and not offline:
        query_status = "no_api_key"
    provider_metadata = {}
    if not offline and provider is not None and callable(getattr(provider, "metadata", None)):
        try:
            metadata = provider.metadata()
            provider_metadata = {
                field: metadata.get(field)
                for field in ("provider", "client", "queried_at_utc", "database_version")
            }
        except Exception as exc:
            query_warnings.append("Provider metadata unavailable: " + str(exc))
    with tempfile.TemporaryDirectory(
        prefix=".diffractscout-initial-", dir=target.parent
    ) as temporary:
        staging = Path(temporary) / "bundle"
        for folder in ("sources", "prototypes", "initial"):
            (staging / folder).mkdir(parents=True, exist_ok=True)
        records: list[dict] = []
        peaks: list[dict] = []
        for phase in selected:
            values = parameters.get(phase, {})
            destination = staging / "initial" / f"{phase}.cif"
            try:
                prototype, provenance = _acquire_prototype(
                    phase,
                    staging,
                    template=template_map.get(phase),
                    candidates=candidates,
                    provider=provider,
                    elements=elements,
                    host=host,
                    max_prototype_attempts=max_prototype_attempts,
                )
                provenance = _redact_text(provenance, redaction_keys)
                phase_chemistry = _chemistry_options(values)
                role = (
                    "caller_supplied_phase"
                    if any(phase_chemistry.values())
                    else "bulk_starting_assumption"
                )
                if role == "bulk_starting_assumption":
                    phase_chemistry = chemistry
                adapted = adapt_cif(
                    prototype,
                    destination,
                    **phase_chemistry,
                    **values.get("lattice", {}),
                    fract=values.get("fract"),
                    citation=values.get("citation", ""),
                )
                loaded = validate_phase_model(destination, phase, host=host)
                sidecar = json.loads(adapted.sidecar_path.read_text(encoding="utf-8"))
                source_axes = set(sidecar["lattice_unchanged"]) & set(_INDEPENDENT_AXES[phase])
                lattice_basis = (
                    "caller_cited_lattice"
                    if not source_axes
                    else "prototype_lattice"
                    if not sidecar["lattice_edits"]
                    else "mixed_cited_and_prototype_lattice"
                )
                warnings = list(query_warnings)
                if (
                    provenance["untried_candidate_count"]
                    and provenance["source"] != "Materials Project"
                ):
                    warnings.append(
                        f"{provenance['untried_candidate_count']} ranked database candidates were not attempted; increase --max-prototype-attempts or provide a template to inspect alternatives."
                    )
                if role == "bulk_starting_assumption":
                    warnings.append(_BULK_WARNING)
                if source_axes:
                    warnings.append(
                        "Prototype lattice retained on independent axes "
                        + ", ".join(sorted(source_axes))
                        + "; adjust these for the target sample."
                    )
                if phase == "alpha-double-prime" and "y" not in values.get("fract", {}):
                    warnings.append(
                        "Cmcm y is inherited from the prototype and is not a target-alloy measurement."
                    )
                warnings.append(
                    "Atomic displacement parameters are prototype starting values (zero if absent), not measured target-alloy thermal parameters."
                )
                if values.get("citation") and not values.get("conditions"):
                    warnings.append(
                        "Citation supplied without measurement/processing conditions; applicability requires review."
                    )
                details = f"Starting model for {composition}, phase family {phase}. Composition role: {role}. Lattice basis: {lattice_basis}. Source: {provenance['source']}. Citation: {values.get('citation', '') or 'none'}. Conditions: {values.get('conditions', '') or 'unspecified'}. Original source and hashes are recorded in preparation.json. Not an experimentally refined target structure."
                write_clean_model(
                    loaded.small_structure,
                    destination,
                    details=_redact_text(details, redaction_keys),
                )
                loaded = validate_phase_model(destination, phase, host=host)
                sidecar.update(
                    {
                        "source_cif": provenance["prototype_cif"],
                        "output_cif": destination.relative_to(staging).as_posix(),
                        "output_sha256": sha256_file(destination),
                        "composition_role": role,
                        "lattice_basis": lattice_basis,
                        "prototype": provenance,
                    }
                )
                write_json(adapted.sidecar_path, _redact_text(sidecar, redaction_keys))
                analysis = simulate_powder_pattern(loaded, preview_settings)
                for reflection in analysis.reflections:
                    peaks.append(
                        {
                            "phase": phase,
                            "h": reflection.h,
                            "k": reflection.k,
                            "l": reflection.l,
                            "d_A": reflection.d_spacing_A,
                            "q_invA": reflection.q_invA,
                            "two_theta_deg": reflection.two_theta_deg,
                            "relative_intensity": reflection.normalized_intensity,
                        }
                    )
                records.append(
                    {
                        "phase": phase,
                        "status": "ready",
                        "cif": destination.relative_to(staging).as_posix(),
                        "sha256": sha256_file(destination),
                        "lattice_basis": lattice_basis,
                        "composition_basis": adapted.composition_basis,
                        "composition_role": role,
                        "occupancies": adapted.occupancies,
                        "citation": values.get("citation", ""),
                        "conditions": values.get("conditions", ""),
                        "cell_parameters": loaded.cell_parameters,
                        "symmetry_crosscheck": "match",
                        "space_group": loaded.space_group_number,
                        "prototype": provenance,
                        "lattice_edits": sidecar["lattice_edits"],
                        "inherited_independent_axes": sorted(source_axes),
                        "coordinate_edits": sidecar["coordinate_edits"],
                        "warnings": warnings,
                        "note": "Validated initial model; review sample-specific lattice, chemistry and internal coordinates before refinement.",
                        "preview_peak_count": len(analysis.reflections),
                        **structure_mass_metadata(loaded),
                    }
                )
            except (ValueError, RuntimeError, OSError) as exc:
                destination.unlink(missing_ok=True)
                destination.with_suffix(".adapt.json").unlink(missing_ok=True)
                records.append(
                    {
                        "phase": phase,
                        "status": "failed",
                        "note": str(exc).replace(key, "[redacted]") if key else str(exc),
                    }
                )
        records = _redact_text(records, redaction_keys)
        payload = {
            "schema": "diffractscout_initial_cifs_v1",
            "generated_at_utc": utc_now_iso(),
            "composition": composition,
            "host": host,
            "elements": elements,
            "bulk_composition": chemistry,
            "phase_parameters": parameters,
            "query_status": query_status,
            "queries": query_records,
            "max_prototype_attempts": max_prototype_attempts,
            "provider_metadata": provider_metadata,
            "preview": {
                "wavelength_A": preview_wavelength_A,
                "two_theta_range_deg": [5, 120],
                "q_definition": "2*pi/d",
                "intensity_normalization": "maximum 100 within each phase",
            },
            "not_phase_identification": True,
            "not_experimental_refinement": True,
            "software_versions": package_versions(),
            "records": records,
        }
        write_json(staging / "preparation.json", _redact_text(payload, redaction_keys))
        _write_csv(
            staging / "initial_cifs.csv",
            ("phase", "status", "cif", "space_group", "lattice_basis", "composition_role", "note"),
            records,
        )
        _write_csv(
            staging / "peak_preview.csv",
            ("phase", "h", "k", "l", "d_A", "q_invA", "two_theta_deg", "relative_intensity"),
            peaks,
        )
        _write_report(staging, composition, host, records, preview_wavelength_A)
        members = [
            {
                "path": path.relative_to(staging).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        ]
        write_json(
            staging / "manifest.json",
            {
                "schema": "diffractscout_bundle_manifest_v1",
                "generated_at_utc": utc_now_iso(),
                "files": members,
            },
        )
        verification = verify_bundle(staging)
        if not verification["ok"]:
            raise RuntimeError(
                "Initial CIF bundle integrity check failed: " + "; ".join(verification["errors"])
            )
        _reject_reparse_components(target, label="initial CIF output")
        _rename_directory_noreplace(staging, target)
    return PrepareCifsResult(
        target,
        target / "report.md",
        target / "initial_cifs.csv",
        target / "manifest.json",
        tuple(
            InitialCifRecord(
                record["phase"],
                record["status"],
                target / record["cif"] if record.get("cif") else None,
                record["note"],
            )
            for record in records
        ),
    )
