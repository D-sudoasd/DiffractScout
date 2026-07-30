# DiffractScout integration report

Date: 30 July 2026

## Scope completed

A new independent Python repository, **DiffractScout**, was created from read-only inspection of `D-sudoasd/PhaseScout` and `D-sudoasd/CIF2Peaks`. The two source repositories were not edited. Their source snapshots and MIT notices are recorded in `docs/SOURCE_LINEAGE.md` and `NOTICE.md`.

The integrated package provides one data flow for:

1. alloy, formula, chemical-system, or Materials Project identifier parsing;
2. subsystem enumeration and deterministic candidate ranking;
3. provider-based candidate search and source acquisition;
4. conventional-standard CIF download and optional DFT elastic-tensor sidecar, using the Materials Project raw/POSCAR tensor for automatic directional coupling and retaining IEEE data for provenance;
5. CIF block selection, hashing, cell/space-group/occupancy validation;
6. indexed theoretical powder reflections with systematic absences, multiplicity, d, 2theta, q, g, X-ray structure-factor terms, and explicit LP/no-LP channels;
7. validated 6x6 stiffness tensors and hkl-normal Young's modulus;
8. CSV/XLSX/provenance export and SHA-256 bundle verification.

The local-CIF path uses Gemmi and the base dependencies. Materials Project support is optional and isolated behind a provider protocol. This keeps the scientific core testable without a network or API key.

## Validation completed

The offline test fixture is a synthetic FCC cell with an explicitly synthetic isotropic cubic stiffness tensor. It verifies:

- FCC systematic absences and expected reflection families;
- analytical d spacing and the identity q = 2*pi/d;
- multiplicity and normalized theoretical intensity output;
- direction-independent Young's modulus of 110 GPa for the chosen isotropic tensor;
- fail-closed handling of Materials Project tensor frames: raw/conventional-CIF coupling is enabled, IEEE-only records require a verified transform, and primitive-cell downloads cannot auto-couple elasticity;
- discovery-to-download-to-analysis orchestration through a fake provider;
- CSV and XLSX generation;
- overwrite protection;
- SHA-256 detection of missing or modified bundle files;
- command-line demo and verification.

The fixture is a numerical contract test and is not presented as experimental material data.

## Release-candidate verification

The local release candidate was verified on Linux with Python 3.13.5:

- `25 passed` in the offline automated suite;
- total test coverage `68.16%`, above the configured `65%` gate;
- `scripts/check_release.py` passed version, bibliography, compile, test, demo, manifest, and wheel checks;
- the built `diffractscout-0.1.0-py3-none-any.whl` installed into a newly created environment using only declared runtime dependencies;
- the installed wheel generated and verified a complete synthetic result bundle containing eight FCC reflection families and all seven workbook sheets;
- the four-page manuscript PDF compiled with Pandoc/XeLaTeX, passed PDF preflight, and was inspected page by page for clipping, overlap, and broken glyphs.

The GitHub-hosted CI jobs remain unexecuted until the repository is created and pushed. Their Ubuntu Python 3.10-3.13 matrix, Windows/macOS smoke tests, lint step, wheel installation, and Open Journals draft-PDF action are configured in `.github/workflows/`.

## Repository engineering

Included components:

- installable `src/` package and command-line entry points;
- optional Materials Project dependency group;
- headless core plus thin Tk interface;
- automated tests and coverage threshold;
- Ubuntu Python 3.10-3.13 CI and Windows/macOS smoke tests;
- wheel build and clean-install verification;
- official Open Journals draft-PDF workflow;
- issue forms for software bugs, scientific validation, and features;
- contribution, security, conduct, release, citation, source-lineage, and scientific-contract documentation;
- JOSS-format manuscript source and verified bibliography.

## Remaining JOSS gates

The repository can satisfy the technical review criteria after CI runs on GitHub. Formal submission still requires evidence that cannot be manufactured during a one-time integration:

- sustained public development history meeting the current JOSS screening period;
- archived releases and a software DOI;
- verified real-material cases and independent numerical comparisons;
- concrete research use, external adoption, or equivalent impact evidence;
- confirmed authorship, ORCID, funding, acknowledgements, and contributor list;
- human review of all AI-assisted code, documentation, references, and scientific claims.

These items are tracked in `docs/JOSS_READINESS.md`.

## Remote publication state

The prepared repository is complete locally. Remote creation and push require an authenticated GitHub write channel. `scripts/publish_github.sh` and `scripts/publish_github.ps1` create `D-sudoasd/DiffractScout` as a private repository by default, push the clean local history, and set research-software topics after `gh auth status` succeeds.
