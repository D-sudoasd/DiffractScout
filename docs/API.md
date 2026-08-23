# Core Python API

## Local CIF analysis

```python
from diffractscout import AnalysisSettings, analyze_cifs

result = analyze_cifs(
    ["cifs/"],
    "outputs/run_01",
    settings=AnalysisSettings(
        input_mode="energy",
        energy_keV=83.0,
        two_theta_min_deg=0.5,
        two_theta_max_deg=15.0,
        step_deg=0.005,
        fwhm_deg=0.03,
        profile_eta=0.5,
        include_elasticity=True,
        max_profile_points=500_000,
        max_reflection_estimate=1_000_000,
    ),
)

print(result.manifest_path)
for diagnostic in result.diagnostics:
    print(diagnostic.level, diagnostic.stage, diagnostic.item, diagnostic.message)
```

`analyze_cifs`:

1. validates run-wide radiation, scan, profile, and resource settings before writes;
2. resolves and deduplicates CIF inputs;
3. rejects overlap between input and output trees;
4. copies source artifacts into a staging result directory;
5. pairs elastic sidecars only when `include_elasticity=True`;
6. analyzes each readable phase while recording per-phase diagnostics;
7. writes CSV, optional XLSX, provenance, and a manifest;
8. verifies the staged bundle;
9. atomically moves it into the requested target.

It returns a `PipelineResult`. An invalid phase can be recorded in `diagnostics` while other phases complete. CLI exit status is `0` when all analyzable items complete, `3` when a usable bundle contains error diagnostics for one or more items, and `2` when no phase is analyzable or a fatal input/configuration error occurs.

## Python quick export

```python
from diffractscout.quick_export import quick_export

result = quick_export(
    ["cifs/"],
    "outputs/energy_bundle",
    energy_keV=20.0,       # infers input_mode="energy"
    include_excel=False,
)
```

`quick_export` accepts the `AnalysisSettings` fields as keyword overrides. A
single `energy_keV` or `wavelength_A` keyword infers its matching radiation
mode and clears the irrelevant counterpart before analysis. Supplying both,
or supplying one that conflicts with an explicitly supplied `input_mode`
keyword, raises before the output directory is created. Radiation keywords
override the prior mode in a supplied `settings=AnalysisSettings(...)` object;
the intentional `source_preset="Custom"` plus `wavelength_A` source-mode
contract remains available. Irrelevant wavelength/energy fields are cleared
after selecting or merging settings, immediately before `analyze_cifs` validates
them: energy mode clears `wavelength_A`, wavelength mode clears `energy_keV`,
and source mode follows its preset semantics (built-in sources clear both;
`Custom` keeps its wavelength and clears `energy_keV`). Contradictory explicit
radiation overrides still raise; normalization does not loosen conflict
validation.
The existing `.xlsx` shortcut remains atomic and does not replace an existing
workbook unless `overwrite=True` is explicit.

Bundle Summary retains `two_theta_range_deg` as the requested settings range,
adds the explicit alias `requested_two_theta_range_deg`, and separately records
the configured per-phase bounds as `analysis_two_theta_range_deg` and actual
sample endpoints as `profile_sampled_two_theta_range_deg`. It also adds
`effective_two_theta_range_deg`, `effective_wavelength_A`,
`effective_energy_keV`, `effective_radiation_source`, and
`source_preset_applied`. These fields describe the post-filter analysis when a
phase is available; an empty/no-analysis bundle remains serializable.

## Candidate discovery

```python
import os

from diffractscout.models import DiscoverySettings
from diffractscout.pipeline import discover_candidates
from diffractscout.providers.materials_project import MaterialsProjectProvider

provider = MaterialsProjectProvider(os.environ["MP_API_KEY"])
discovery = discover_candidates(
    "Ti-Al-V",
    provider,
    settings=DiscoverySettings(
        mode="near_stable",
        e_hull_max_eV_atom=0.05,
        max_subsystem_order=3,
        max_subsystems=4096,
        max_per_subsystem=100,
        max_total=50,
    ),
)
```

`DiscoveryResult` contains normalized input, queried subsystems, per-subsystem counts, a deterministic candidate list, provider metadata, and warnings. Invalid negative/non-finite energy limits and non-positive count limits are rejected before provider access. The total number of proposed subsystem queries is calculated before materializing the query list; values above `max_subsystems` are rejected to prevent combinatorial expansion in high-component systems.

## Discovery-only export

```python
from diffractscout.pipeline import export_discovery

result = export_discovery(
    "Ti-Al-V",
    provider,
    "outputs/ti_al_v_candidates",
    discovery_settings=DiscoverySettings(max_total=50),
)
```

This produces a verifiable result bundle without downloading structures.

## Complete pipeline

```python
from diffractscout.pipeline import run_pipeline

result = run_pipeline(
    "Ti-Al-V",
    provider,
    "outputs/ti_al_v",
    discovery_settings=DiscoverySettings(
        mode="near_stable",
        e_hull_max_eV_atom=0.05,
        max_total=50,
    ),
    analysis_settings=AnalysisSettings(
        input_mode="source",
        source_preset="Cu Ka",
    ),
    conventional_unit_cell=True,
    include_elasticity=True,
    confirm_above=50,
)
```

Downloads above `confirm_above` require `authorize_large_download=True`. Automatic Materials Project elasticity coupling requires a conventional-standard cell. A primitive-cell run must set `include_elasticity=False`.

## Result records

### `PipelineResult`

- `output_dir`: committed bundle directory;
- `discovery`: optional `DiscoveryResult`;
- `downloads`: `DownloadArtifact` records with separate CIF and elasticity status;
- `analyses`: successful `PhaseAnalysis` records;
- `manifest_path`: committed manifest path;
- `warnings`: deduplicated warning/error summaries;
- `diagnostics`: structured stage/item/severity/message records.

### `AnalysisSettings`

- radiation: `input_mode`, `source_preset`, `wavelength_A`, `energy_keV`;
- window/profile: `two_theta_min_deg`, `two_theta_max_deg`, `step_deg`, `fwhm_deg`, `profile_eta`;
- elasticity: `include_elasticity`;
- safety: `max_profile_points`, `max_reflection_estimate`.

### `DiscoverySettings`

- search: `mode`, `e_hull_max_eV_atom`, `exclude_deprecated`;
- subsystem scope: `max_subsystem_order`, `max_subsystems`;
- result scope: `max_per_subsystem`, `max_total`.

`max_subsystems` defaults to 4096 and is checked before provider access. Raising it should follow a review of the element count, subsystem order, provider rate limits, and intended research scope.

## Lower-level functions

- `diffractscout.composition.parse_composition_text(text)`
- `diffractscout.composition.chemsys_subsystems(elements, max_order=None)`
- `diffractscout.selection.validate_discovery_settings(settings)`
- `diffractscout.diffraction.validate_analysis_settings(settings)`
- `diffractscout.structure.load_structure(path)`
- `diffractscout.elasticity.discover_elastic_tensor(cif_path)`
- `diffractscout.elasticity.validate_elastic_tensor(matrix_GPa, ...)`
- `diffractscout.elasticity.young_modulus_hkl_normal_GPa(tensor, cell, hkl)`
- `diffractscout.diffraction.resolve_wavelength(settings)`
- `diffractscout.diffraction.simulate_powder_pattern(structure, settings, elastic_tensor=None)`
- `diffractscout.validation.verify_bundle(path)`

Scientific meanings and units are defined in `docs/SCIENTIFIC_CONTRACTS.md`.

## Analytic benchmark API

```python
from diffractscout.benchmark import (
    run_reference_benchmarks,
    verify_benchmark_bundle,
)

report = run_reference_benchmarks(
    "outputs/analytic_benchmark",
    overwrite=False,
)
assert report["all_passed"]
assert verify_benchmark_bundle("outputs/analytic_benchmark")["ok"]
```

The benchmark bundle contains the exact synthetic CIF fixtures, machine-readable expectations, 45 individual checks, tolerances, package versions, portable runtime metadata, Markdown/JSON reports, and a SHA-256 manifest. Setting `SOURCE_DATE_EPOCH` fixes generated timestamps for reproducible evidence artifacts.

## Provider protocol

A provider implements:

```python
class PhaseProvider(Protocol):
    name: str

    def search_subsystem(...): ...
    def download_candidates(...): ...
    def metadata(self) -> dict[str, object]: ...
```

A provider must preserve source identity and distinguish service failure from a valid no-data result. It must not synthesize missing property values. `DownloadArtifact` supports separate `status/error` and `elasticity_status/elasticity_error` fields for this purpose.

## Bundle verification

```python
from diffractscout.validation import verify_bundle

report = verify_bundle("outputs/run_01")
if not report["ok"]:
    raise RuntimeError(report["errors"])
```

Verification checks every declared hash and size and rejects unsafe paths, duplicates, symlinks, root escapes, missing files, modified files, and unlisted files.
