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
    ),
)
```

`analyze_cifs` copies source artifacts into the output bundle, parses each CIF, pairs a compatible elasticity sidecar when present, calculates reflections and writes all exports. It returns a `PipelineResult` containing the `PhaseAnalysis` objects and manifest path.

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
        max_total=50,
    ),
)
```

`DiscoveryResult` contains the normalized input, queried subsystems, per-subsystem counts, deterministic candidate list, provider metadata and warnings.

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
    confirm_above=50,
)
```

Downloads above `confirm_above` require `authorize_large_download=True`.

## Lower-level functions

- `diffractscout.composition.parse_composition_text(text)`
- `diffractscout.composition.chemsys_subsystems(elements, max_order=None)`
- `diffractscout.structure.load_structure(path)`
- `diffractscout.elasticity.discover_elastic_tensor(cif_path)`
- `diffractscout.elasticity.validate_elastic_tensor(matrix_GPa, ...)`
- `diffractscout.elasticity.young_modulus_hkl_normal_GPa(tensor, cell, hkl)`
- `diffractscout.diffraction.resolve_wavelength(settings)`
- `diffractscout.diffraction.simulate_powder_pattern(structure, settings, elastic_tensor=None)`
- `diffractscout.validation.verify_bundle(path)`

## Provider protocol

A provider implements:

```python
class PhaseProvider(Protocol):
    name: str
    def search_subsystem(...): ...
    def download_candidates(...): ...
    def metadata(self) -> dict[str, object]: ...
```

Provider implementations must return source identity and must not silently synthesize missing property values.
