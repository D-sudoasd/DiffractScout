# Changelog

All notable changes are recorded here. The project follows semantic versioning after the first stable release.

## [Unreleased]

### Added

- Windows launchers: `启动DiffractScout.bat` (GUI) and `quick_export_diffractscout.bat` (drag-and-drop quick-export with Excel next to the first input).
- Packaging stub `scripts/package_windows_portable.py` documenting a future PyInstaller portable layout (`--help` / `--print-recipe`; no freeze yet).
- Optional dependencies `figures` (matplotlib) and `gui-dnd` (tkinterdnd2); `paper` remains as a matplotlib alias.
- Console entry point `diffractscout-quick-export` and GUI entry point `diffractscout-gui` documented alongside `diffractscout`.
- Documentation for CIF2Peaks parity features (lab Excel views, *d*-range filters, bilingual lab sheets, quick-export, figures) in README / README.zh-CN, GUI controls in `docs/GUI.md`, and module mapping in `docs/SOURCE_LINEAGE.md`.

### Notes

- Awaiting the first public GitHub release, archived software DOI, and external validation cases.

## [0.3.0] - 2026-08-12

### Added

- Added a packaged analytic benchmark suite for simple-cubic, BCC, FCC, NaCl, and cubic directional-elasticity solutions, producing a self-verifying SHA-256 evidence bundle with 45 closed-form checks.
- Added a machine-readable JOSS evidence ledger, JSON schema, readiness preflight, six-month public-development plan, adoption/impact claim ledger, governance, support, roadmap, and validation-case registry.
- Added portable runtime metadata to provenance and benchmark reports without storing local paths or host identifiers.
- Added a tag-driven release workflow that verifies the tag/version match, runs the full release preflight, builds wheel and source distributions, validates package metadata, creates deterministic benchmark/demo/readiness archives and checksums, and publishes a GitHub Release.
- Added a monthly reproducibility-audit workflow and monthly Dependabot updates for Python and GitHub Actions dependencies.
- Added deterministic evidence-archive tooling with sorted paths, fixed timestamps, safe roots, symbolic-link rejection, and atomic output replacement.

### Fixed

- Scanned `.cif` filenames case-insensitively on all platforms and rejected missing or explicitly non-CIF inputs with actionable errors.
- Prevented same-basename CIF files from overwriting one another in a result bundle by deriving deterministic collision-safe copied names.
- Preserved exact upper-bound reflections by applying a documented floating-point search margin followed by exact angular filtering.
- Distinguished `not_requested` elasticity from valid no-data states throughout phase, peak, and provider outputs.
- Converted declared Pa, kPa, MPa, GPa, and TPa stiffness units into GPa and rejected unknown units before directional-property calculation.
- Returned a dedicated partial-success CLI exit status when a valid result bundle contains failed phases or provider items.
- Prevented oversized Excel tables from silently truncating by placing an omission record in the workbook while retaining the complete CSV output.
- Rejected chemical-subsystem expansions above a configurable pre-provider query limit to prevent combinatorial API growth in high-component systems.

### Validation

- Expanded the offline suite to 68 tests.
- Added deterministic benchmark and evidence-archive reproducibility checks using `SOURCE_DATE_EPOCH`.
- Added automated integrity checks for the JOSS evidence ledger, citation metadata, repository materials, manuscript structure, public-history dates, release archives, research use, independent validation, and external engagement.

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
