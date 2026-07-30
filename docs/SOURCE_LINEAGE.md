# Source lineage

## Read-only source repositories

The initial integration was prepared from the following public snapshots on 30 July 2026:

| Repository | Snapshot | License | Role retained in DiffractScout |
|---|---|---|---|
| `D-sudoasd/PhaseScout` | `10e4cd4a7ae1317b4368ae4cce905e643d471584` | MIT | composition parsing, subsystem discovery, candidate metadata, Materials Project acquisition, CIF/Cij provenance |
| `D-sudoasd/CIF2Peaks` | `36e7e31419fa7ba2752e3e1bdf82e42b400e3b83` | MIT | CIF validation, theoretical powder peaks, intensity channels, elasticity pairing, hkl-normal modulus, batch export |

No commit, branch, tag, release, issue, setting or file was changed in either source repository during this integration.

## Architectural changes

The source projects were connected by adjacent files and naming conventions. DiffractScout replaces that boundary with typed records and a single pipeline:

| Previous behavior | DiffractScout implementation |
|---|---|
| PhaseScout script-level Materials Project logic | `PhaseProvider` protocol plus optional `MaterialsProjectProvider` |
| Separate candidate index and CIF folder | `DiscoveryResult` and copied/downloaded `inputs/` inside one bundle |
| `{stem}_elasticity.json` convention | Retained for compatibility and promoted into `ElasticTensor` with explicit frame and validation state |
| CIF2Peaks service/GUI orchestration | Headless `pipeline.py`, CLI, Python API and a thin GUI |
| pymatgen-required local diffraction | Gemmi-based offline engine; pymatgen remains optional through mp-api |
| Separate export files | Versioned provenance JSON and SHA-256 manifest covering the complete bundle |
| Literature fallback hints | Excluded from numerical tensor generation; missing Cij remains missing |

## Scientific behavior retained

- Chemical-system subsystem expansion and candidate deduplication.
- Conventional-cell Materials Project download as the default.
- Explicit distinction between Materials Project DFT tensors and experimental elastic constants.
- Indexed peak columns containing `hkl`, `d`, `2θ`, `q`, `g`, relative intensity and warnings.
- LP and no-LP volume-normalized theoretical intensity channels, with legacy `R_hkl` aliases retained for compatibility.
- Voigt engineering-shear convention for hkl-normal Young's modulus.
- CSV/Excel export intended for Origin, Excel and Python workflows.

## Attribution

Both source repositories were licensed under MIT with copyright `2026 D-sudoasd`. DiffractScout is licensed under MIT and retains the source notice in `NOTICE.md`. Git history in the new repository records subsequent modifications; the source snapshot table provides the audit trail for the initial merge.
