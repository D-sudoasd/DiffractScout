<p align="center">
  <img src="docs/assets/hero.svg" width="100%" alt="DiffractScout: provenance-first phase scouting and indexed powder diffraction references.">
</p>

# DiffractScout

[![CI](https://github.com/D-sudoasd/DiffractScout/actions/workflows/ci.yml/badge.svg)](https://github.com/D-sudoasd/DiffractScout/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10–3.13](https://img.shields.io/badge/python-3.10%E2%80%933.13-3776ab.svg)](pyproject.toml)

**DiffractScout connects candidate-phase discovery to auditable theoretical powder-diffraction references.** It accepts an alloy grade, chemical system, Materials Project IDs, or local CIF files; records where every structure came from; validates the CIF; calculates indexed powder reflections; optionally couples a numerical 6×6 stiffness tensor to the normal of each `hkl`; and exports a self-contained evidence bundle with SHA-256 hashes.

[中文概览](README.zh-CN.md) · [Scientific contracts](docs/SCIENTIFIC_CONTRACTS.md) · [Architecture](docs/ARCHITECTURE.md) · [Validation](docs/VALIDATION.md) · [JOSS readiness](docs/JOSS_READINESS.md)

## Statement of need

Materials researchers often perform a chain of loosely connected tasks: expand an alloy into possible chemical subsystems, search a computed-materials database, download CIF files, inspect structural metadata, generate theoretical powder peaks, attach elastic constants, and prepare tables for experimental planning. Local scripts commonly lose the connection between a database record, the exact CIF, the tensor basis, the diffraction settings, and the exported table. That loss of provenance makes later interpretation and publication difficult.

DiffractScout treats the complete chain as one research object. Candidate records, downloaded structures, elastic sidecars, calculated reflections, display profiles, warnings, software versions, and file hashes are written into one result directory. Missing elastic data stays missing. Literature hints are never converted into numerical tensors. Theoretical peak references are labeled separately from experimental fitting and phase identification.

## Integrated workflow

```text
alloy / formula / chemsys / mp-IDs
        ↓
subsystem expansion and deterministic candidate ranking
        ↓
Materials Project CIF + optional DFT Cij, or local CIF inputs
        ↓
CIF identity, cell, space group, occupancy, and source checks
        ↓
indexed theoretical reflections: d, 2θ, q, g, |F|², multiplicity, LP
        ↓
optional E along the reciprocal-lattice normal of each hkl
        ↓
CSV + XLSX + provenance JSON + SHA-256 manifest
```

The base installation works offline for local CIF analysis. Materials Project access is an optional dependency and requires the user's own API key.

## Installation

```bash
git clone https://github.com/D-sudoasd/DiffractScout.git
cd DiffractScout
python -m pip install -e .
```

Add Materials Project discovery and download support:

```bash
python -m pip install -e ".[mp]"
```

Development environment:

```bash
python -m pip install -e ".[test]"
pytest -q
```

## Five-minute verification

The built-in demo uses a synthetic FCC structure and a synthetic isotropic stiffness tensor. It does not contain experimental property data.

```bash
diffractscout demo -o outputs/demo
diffractscout verify outputs/demo
```

Expected result:

```text
Analyzed phases: 1
PASS
```

## Analyze local CIF files

```bash
diffractscout analyze path/to/cifs -o outputs/local_cifs
```

Use 83 keV synchrotron radiation:

```bash
diffractscout analyze path/to/cifs -o outputs/83keV \
  --energy-keV 83 --two-theta-min 0.5 --two-theta-max 15
```

When `{cif_stem}_elasticity.json` or a compatible PhaseScout sidecar is present beside a CIF, DiffractScout validates the 6×6 matrix and fills `young_modulus_hkl_normal_GPa`. Disable this path with `--no-elasticity`.

## Discover candidate phases

```bash
export MP_API_KEY="your-key"
diffractscout discover "Ti-6Al-4V" -o outputs/ti64_candidates \
  --mode near_stable --e-hull-max 0.05 --max-total 100
```

The discovery command writes the candidate catalogue and provenance without downloading structures.

## Run the complete pipeline

```bash
export MP_API_KEY="your-key"
diffractscout run "Ti-Al-V" -o outputs/ti_al_v \
  --mode near_stable --e-hull-max 0.05 --max-total 50
```

The pipeline requests conventional-standard unit cells by default. For automatic `hkl`-normal modulus calculation, it uses the Materials Project raw/POSCAR-format tensor documented as consistent with that CIF setting. IEEE-format tensors are retained in provenance, but an IEEE-only record is marked `frame_transform_required` and produces no directional modulus until an explicit rotation into the CIF Cartesian frame is supplied. `--primitive` therefore requires `--no-elasticity`.

## Result bundle

Each completed run contains:

| File | Purpose |
|---|---|
| `inputs/` | Copied local inputs or downloaded CIF/Cij source artifacts |
| `candidate_index.csv` | Candidate phases, query subsystem, stability metadata, source URL |
| `phase_summary.csv` | CIF hash, unit cell, space group, occupancy and validation warnings |
| `peak_reference.csv` | Indexed theoretical peaks and optional hkl-normal modulus |
| `pattern_profiles.csv` | Normalized pseudo-Voigt display profiles |
| `elasticity.csv` | Tensor values, coordinate frame, source and warnings |
| `results.xlsx` | Human-readable workbook containing the same tables |
| `provenance.json` | Settings, equations, software versions and source metadata |
| `manifest.json` | SHA-256 inventory checked by `diffractscout verify` |

## Scientific contracts

DiffractScout calculates a kinematic theoretical powder reference. The current implementation does not perform experimental phase identification, Rietveld/Le Bail/Pawley refinement, quantitative phase analysis, instrument calibration, background estimation, preferred-orientation correction, absorption correction, size/strain broadening, or absolute intensity calibration.

The reflection table reports both:

```text
I_no_LP   = multiplicity × |F_xray|²
I_with_LP = I_no_LP × LP(θ)
volume_normalized_intensity_with_lp = I_with_LP / V_cell²
volume_normalized_intensity_no_lp   = I_no_LP / V_cell²
legacy R_hkl aliases                 = the same two project-defined quantities
```

The `R_hkl` column names are retained as compatibility aliases for the earlier CIF2Peaks schema. They denote project-defined volume-normalized theoretical intensity channels. They are not crystallographic residual R factors, standardized quantitative-phase coefficients, or experimentally calibrated scattering factors. The continuous profile is a visualization aid generated from the discrete lines with a user-selected pseudo-Voigt width. It is not fitted to an instrument response.

Full definitions and coordinate conventions are in [docs/SCIENTIFIC_CONTRACTS.md](docs/SCIENTIFIC_CONTRACTS.md).

## Python API

```python
from diffractscout import AnalysisSettings, analyze_cifs

result = analyze_cifs(
    ["path/to/cifs"],
    "outputs/example",
    settings=AnalysisSettings(
        input_mode="energy",
        energy_keV=83.0,
        two_theta_min_deg=0.5,
        two_theta_max_deg=15.0,
    ),
)
print(result.manifest_path)
```

Core API details are documented in [docs/API.md](docs/API.md).

## Graphical interface

```bash
diffractscout-gui
# equivalent:
diffractscout gui
```

The GUI exposes local CIF analysis and the complete Materials Project pipeline. Numerical logic remains in the package API and is covered by headless tests.

## Source lineage

DiffractScout integrates and restructures ideas and functionality from two MIT-licensed projects maintained by the same author:

- [`D-sudoasd/PhaseScout`](https://github.com/D-sudoasd/PhaseScout)
- [`D-sudoasd/CIF2Peaks`](https://github.com/D-sudoasd/CIF2Peaks)

The source repositories remain independent. The exact source snapshots, retained scientific behavior, changed architecture, and license notices are recorded in [docs/SOURCE_LINEAGE.md](docs/SOURCE_LINEAGE.md) and [NOTICE.md](NOTICE.md).

## JOSS preparation status

The repository includes package metadata, an OSI-approved license, automated tests, CI, installation and API documentation, examples, contribution and support routes, a release process, a JOSS-format paper draft, and an explicit AI usage disclosure. Current JOSS screening also requires sustained public development and concrete research-impact evidence. Those time- and use-dependent records must accumulate in the public repository and cannot be replaced by documentation alone. See [docs/JOSS_READINESS.md](docs/JOSS_READINESS.md).

## Citation

Use [CITATION.cff](CITATION.cff) for software metadata. Create a tagged release and archive it before a formal JOSS submission; replace the placeholder archive field in the paper after a DOI exists.

## License

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
