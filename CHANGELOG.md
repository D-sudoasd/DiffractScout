# Changelog

All notable changes are recorded here. The project follows semantic versioning after the first stable release.

## [0.4.0] - Unreleased

### Added

- Windows launchers: `启动DiffractScout.bat` (GUI) and `quick_export_diffractscout.bat` (drag-and-drop quick-export with Excel next to the first input).
- Packaging stub `scripts/package_windows_portable.py` documenting a future PyInstaller portable layout (`--help` / `--print-recipe`; no freeze yet).
- Optional dependencies `figures` (matplotlib) and `gui-dnd` (tkinterdnd2); `paper` remains as a matplotlib alias.
- Console entry point `diffractscout-quick-export` and GUI entry point `diffractscout-gui` documented alongside `diffractscout`.
- Documentation for CIF2Peaks parity features (lab Excel views, *d*-range filters, bilingual lab sheets, quick-export, figures) in README / README.zh-CN, GUI controls in `docs/GUI.md`, and module mapping in `docs/SOURCE_LINEAGE.md`.
- Stage-aware JOSS readiness gates for ordinary releases, initial submission,
  and post-review publication/archive consistency.
- A current-source release acceptance receipt covering documentation,
  compilation, tests, demo/verify, the analytic benchmark, wheel, sdist, and
  Twine checks plus a source-independent wheel smoke test; strict release
  readiness fails closed without it.
- A reviewer-checklist evidence matrix and an explicitly incomplete intake
  scaffold for the required real multiphase-alloy research case.

### Fixed

- Made GUI radiation transitions unit-safe with explicit Å/keV labels and
  conversion/clearing rules; quick-export now infers and validates radiation
  keyword modes before any output target is created.
- Rejected inactive numeric radiation fields during analysis preflight, so
  energy, wavelength, Custom-source, and built-in-source settings cannot be
  persisted in contradictory combinations.
- Corrected non-orthogonal hkl plane normals to use the direct CIF Cartesian
  basis, exported finite q/g zeros at 2θ=0, and added requested/effective
  radiation and angular-window provenance.
- Made *d*-spacing/2θ intersections inclusive at equality and explicit when
  empty, including the physically inaccessible `d_max_A < lambda/2` case;
  retained configured analysis bounds while separately recording actual
  profile-sample endpoints, requested/effective ranges, and geometric versus
  filter `d_min` meanings.
- Made bundle README artifact claims conditional, retained caller-owned
  diagnostics for Excel omission warnings, enforced Excel/lab-view and
  elasticity control dependencies, and preserved a valid prior Open result
  action after a failed retry.
- Recorded effective optional-output flags in provenance and made Excel,
  continuous-pattern, figure, and lab-view definitions conditional on actual
  emission.
- Failed closed for Materials Project raw/POSCAR elasticity tensors and
  generic JSON tensors without `coordinate_frame`; numeric tensors remain in
  provenance, but hkl-normal modulus output requires an explicit verified
  transform into the emitted CIF Cartesian frame.
- Validated run-wide diffraction and discovery settings before copying local inputs, contacting providers, or starting GUI workers.
- Snapshotted GUI run options on the Tk thread so background workers do not access mutable Tk state.
- Required explicit overwrite authorization for existing quick-export workbooks and replaced authorized workbooks atomically.
- Preserved workbooks created by another process during quick export when overwrite was not authorized.
- Rechecked bundle and benchmark targets immediately before commit so files created during a long-running calculation are not silently replaced.
- Rejected malformed or non-finite provider elasticity matrices instead of truncating oversized arrays to 6×6.
- Applied Materials Project stability thresholds before server-side result limits, with strict local verification so qualifying candidates are not lost to post-filtering.
- Normalized common Unicode dash characters and case-insensitive chemical-system input during composition parsing.
- Kept the optional spglib cross-check warning-only across its 2.7-to-2.8 exception transition without emitting repeated deprecation noise.
- Exported an empty Cu Kα convenience angle, rather than a false `0°`, when a reflection is inaccessible at that wavelength.
- Recorded the verified public-repository date and removed stale claims that the
  canonical GitHub repository did not yet exist.
- Removed drifting hard-coded pytest totals from static documentation and the
  paper; CI and readiness artifacts now own collected-test counts.
- Clarified that `--pattern-axis` selects the CSV/Excel pattern coordinate while
  v0.4.0 figures remain on a 2θ axis.
- Documented the per-multiplicity structure-factor helper equations and added a
  multiplicity-greater-than-one regression.
- Migrated package licensing metadata to the SPDX form required by current
  setuptools while retaining the complete MIT license file.
- Made GUI scroll-wheel and focus bindings idempotent across repeated widget
  mapping, and stopped disabled built-in-source radiation fields from blocking
  a run with stale non-numeric text.
- Added explicit `--wavelength-A` / `--energy-keV` modes to standalone
  quick-export, with an actionable error for an under-specified `Custom`
  source; normalized trailing folder paths in the Windows drag-and-drop
  launcher.
- Kept Unicode phase/CIF names in provenance and tabular exports while using
  a neutral ASCII title for dependency-free raster figures, so base installs
  still emit both SVG and PNG outputs.
- Cleaned unique same-directory text-export temporary files on every failure
  path and constrained the Materials Project extras for Python 3.10 to
  `mp-api<0.46` and `pymatgen<2026` while leaving newer Python lower bounds
  unbounded.
- Parsed additive composition chains without dropping later terms or silently
  treating them as a different composition syntax.
- Failed closed when a CIF contains an unknown element instead of emitting a
  partial or fabricated composition/mass result.
- Matched elasticity-index records using normalized absolute CIF paths so an
  index remains unambiguous across working directories.
- Included nested `manifest.json` files in manifest construction and
  verification while excluding only the root manifest.
- Recovered stale transaction locks only when the no-replace safety checks
  proved that the lock was isolated; an uncertain lock is preserved and fails
  closed.
- Applied the profile-grid and reciprocal-candidate resource guards to
  quick-export before expensive analysis begins.
- Defined `run_pipeline` elasticity-setting precedence: an explicit keyword
  override wins, while an omitted override honors `AnalysisSettings`.
- Made GUI initialization failures actionable and tightened platform-specific
  test skips so unavailable GUI environments are reported accurately.
- Hardened Windows launcher interpreter selection to prefer the checkout
  environment before the active Python and `py -3` fallbacks.
- Added an installation hint for the optional Materials Project extras and
  kept API-key handling explicit in user documentation.
- Recorded stable provenance definitions for expanded unit-cell mass and
  transformed profile axes, including their schema names and limitations.
- Completed README/release gate hardening: first-run guidance and
  release/readiness wording now keep unreleased source status, generated notes,
  and scientific acceptance distinct.

### Notes

- This entry is a release candidate until the full local and remote acceptance
  checks pass and an explicitly authorized `v0.4.0` tag and GitHub Release are
  created. The existing `v0.3.0` tag is not moved.
- JOSS submission remains blocked until 15 February 2027 or later and until
  real research-use, independent diffraction and elasticity validation,
  external engagement, official paper-build, remote-CI, and human metadata
  evidence pass. The immutable software archive DOI is a post-review gate.

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
