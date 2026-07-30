# Changelog

All notable changes are recorded here. The project follows semantic versioning after the first stable release.

## [Unreleased]

- Awaiting the first public GitHub release, archived software DOI, and external validation cases.

## [0.2.0] - 2026-07-30

### Added

- Rebuilt the Tk desktop interface with separate local-CIF and Materials Project workflows, complete scientific controls, progress state, structured logs, result-folder access, and v0.2.0 reference screenshots.
- Added profile-grid and reciprocal-space resource guards to the API, CLI, GUI, analysis metadata, tests, and documentation.
- Added `DiagnosticRecord`, `diagnostics.csv`, and a `Diagnostics` workbook sheet for discovery, download, elasticity, and per-phase analysis outcomes.
- Added a headless Linux GUI smoke job and expanded release documentation.

### Fixed

- Made `--no-elasticity` suppress elastic-sidecar discovery, copying, and evaluation.
- Distinguished Materials Project elasticity service failures from valid no-data and no-tensor responses.
- Rejected elastic sidecars that declare a different CIF and reported ambiguous pairings explicitly.
- Strengthened CIF validation and space-group resolution from symbols, International Tables numbers, Gemmi inference, and spglib cross-checks.
- Made explicit CLI energy and wavelength inputs mutually exclusive.
- Removed a duplicate `c_A` export mapping.
- Corrected the GitHub publication helpers so a local bundle/file remote is replaced by the intended GitHub remote before push; added a non-destructive dry-run mode.

### Safety and reproducibility

- Added disjoint input/output validation, staged result generation, integrity verification before commit, atomic directory replacement, and rollback preservation of the previous valid bundle.
- Required an existing bundle to pass integrity verification before overwrite.
- Extended manifest verification to reject malformed entries, duplicate/unsafe paths, symbolic links, root escapes, and unlisted files.
- Added spreadsheet formula-injection protection and atomic CSV/XLSX writes.
- Expanded the deterministic offline suite to 46 tests, including transaction failure, resource limits, provider failure semantics, workbook diagnostics, and strict bundle integrity.

## [0.1.0] - 2026-07-30

- Created the independent DiffractScout package without modifying PhaseScout or CIF2Peaks.
- Added alloy/formula/chemical-system parsing and subsystem enumeration.
- Added an optional Materials Project provider for candidate search, conventional CIF download, and DFT elastic-tensor sidecars.
- Added Gemmi-based CIF validation and kinematic powder X-ray reflection calculation.
- Applied Gemmi crystallographic-occupancy conversion on a dedicated structure-factor copy, with an analytic monoatomic-FCC regression test for special-position multiplicity.
- Coupled Materials Project raw/POSCAR-format elastic tensors only to conventional-standard CIFs; IEEE-only records now require an explicit frame transform, and primitive-cell downloads reject automatic elasticity coupling.
- Documented the legacy `R_hkl` fields as project-defined volume-normalized theoretical intensity aliases, separate from crystallographic residual factors and quantitative-phase coefficients.
- Added explicit Lorentz-polarization and no-LP intensity channels.
- Added 6×6 stiffness validation and hkl-normal Young's modulus calculation.
- Added self-contained CSV, Excel, provenance JSON, and SHA-256 manifest exports.
- Added local CLI, end-to-end CLI, graphical interface, offline synthetic demo, automated tests, CI configuration, documentation, and a JOSS paper draft.
