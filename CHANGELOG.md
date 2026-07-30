# Changelog

All notable changes are recorded here. The project follows semantic versioning after the first stable release.

## [Unreleased]

- Awaiting the first public GitHub release, archived software DOI, and external validation cases.

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
