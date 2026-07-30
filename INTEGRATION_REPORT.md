# DiffractScout integration and v0.2.0 hardening report

Date: 30 July 2026

## Repository scope

DiffractScout is an independent Python repository assembled from read-only inspection and lawful reuse of the MIT-licensed `D-sudoasd/PhaseScout` and `D-sudoasd/CIF2Peaks` projects. Neither source repository was modified. Source snapshots, retained behavior, architectural changes, and notices are recorded in `docs/SOURCE_LINEAGE.md` and `NOTICE.md`.

The integrated data flow covers:

1. alloy, formula, chemical-system, or Materials Project identifier parsing;
2. subsystem enumeration, provider queries, deduplication, and deterministic ranking;
3. conventional-standard CIF acquisition and optional DFT elastic-tensor records;
4. CIF hashing, block selection, cell/site/space-group/occupancy validation;
5. indexed theoretical powder reflections with systematic absences, multiplicity, $d$, $2\theta$, $q$, $g$, X-ray structure-factor terms, and explicit LP/no-LP channels;
6. uniquely paired and frame-compatible 6×6 stiffness tensors with `hkl`-normal Young's modulus;
7. CSV/XLSX/provenance/diagnostic output and strict SHA-256 bundle verification.

## v0.2.0 code audit and fixes

The hardening pass identified and corrected several reproducible defects or ambiguous behaviors:

- `--no-elasticity` previously allowed local sidecar discovery/copying; it now disables the entire elasticity path.
- a Materials Project elasticity service failure could be reported like a valid no-data result; query failure, no document, no tensor, and frame-transform requirement now have distinct statuses and errors;
- exact-name elastic sidecars could be used despite declaring a different paired CIF; conflicts and ambiguous matches now stop directional evaluation;
- existing output replacement checked only for a recognizable manifest; the current bundle must now pass full integrity verification before overwrite;
- result generation now uses a sibling staging directory, verifies the completed bundle, and atomically replaces the target with rollback protection;
- input/output path overlap is rejected before any write;
- manifest verification now rejects malformed hashes/sizes, duplicates, unsafe paths, root escapes, symbolic links, missing/modified files, and unlisted files;
- radiation mode validation now rejects simultaneous explicit energy and wavelength CLI arguments;
- CIF validation and space-group resolution now record explicit symbol/number/inference sources and spglib disagreement;
- profile grids and reciprocal-space searches now have configurable resource limits;
- spreadsheet exports now neutralize formula-like external text and use atomic file replacement;
- a duplicate `c_A` export mapping was removed.

## GUI upgrade

The desktop interface was rebuilt around two clear workflows:

- local CIF analysis with multiple files/folders and recursive scanning;
- Materials Project candidate discovery, download, diffraction, and optional elasticity.

The GUI now exposes radiation and profile parameters, reciprocal-space safety limits, candidate limits, elastic pairing, Excel output, verified overwrite authorization, progress state, task locking, timestamped diagnostics, and result-folder access. The API key is retained only in process memory. Completion messages distinguish clean success, completion with error diagnostics, and diagnostic-only output with no analyzable phase.

Reference screenshots are stored in:

- `docs/assets/gui-local.png`;
- `docs/assets/gui-materials-project.png`.

## Automated validation

The current deterministic suite contains **46 passing tests** and covers:

- composition and subsystem logic;
- CIF block, cell, site, space-group, and occupancy contracts;
- analytic FCC structure-factor behavior and systematic absences;
- Bragg geometry, intensity channels, normalization, and resource limits;
- tensor validation, cached compliance, sidecar identity, and coordinate frames;
- provider query-failure semantics;
- transactional output and preservation of an existing valid bundle on staged failure;
- spreadsheet safety and stable empty schemas;
- diagnostics workbook output;
- strict manifest verification.

Configured GitHub Actions include Ubuntu Python 3.10–3.13, Ruff, coverage, Windows/macOS smoke tests, Linux Xvfb GUI construction, wheel build and clean installation, the offline scientific demo, bundle verification, and the Open Journals draft-PDF action.

## JOSS engineering state

The repository now contains:

- installable package metadata and CLI/GUI entry points;
- OSI-approved MIT licensing and retained source notices;
- automated tests and CI configuration;
- user, GUI, API, architecture, validation, scientific-contract, comparison, source-lineage, release, security, conduct, and contribution documentation;
- structured issue and pull-request templates;
- JOSS manuscript source, bibliography, workflow figure, and AI usage disclosure;
- a reproducible offline demonstration and release preflight script.

## Remaining JOSS gates

The following evidence cannot be supplied by a one-time code hardening pass:

- sustained public development over the applicable JOSS screening period;
- successful remote CI records and reviewed pull requests;
- tagged releases and a software archive DOI;
- independent real-material diffraction and elasticity comparisons;
- documented research use and external feedback/adoption;
- confirmed final authorship, ORCID, funding, facility acknowledgements, and contributor list;
- human review and approval of all AI-assisted code, documentation, references, and claims.

These items are tracked in `docs/JOSS_READINESS.md`.

## Remote publication state

At the time of this report, `D-sudoasd/DiffractScout` is absent from the connected GitHub account. The current environment also lacks GitHub CLI and the available GitHub connector does not expose repository creation. Local source, commits, merge preparation, wheel, bundle, and checksums can be completed; remote push, pull-request merge, release publication, and remote branch deletion require creation of the empty repository or an equivalent authenticated repository-creation channel.
