# CIF2Peaks and PhaseScout replacement audit

Date: 2026-09-27

## Finding and integration decision

Before this change, DiffractScout implemented the principal combined pipeline,
but did not preserve every upstream workflow. In particular, the PhaseScout
literature-search pack and original batch/index conventions, the full CIF2Peaks
workbook/figure exports and pymatgen engine, and a working portable builder were
missing or incomplete. The original integration report was not a full parity audit.

DiffractScout now owns the upstream runtime modules under `diffractscout.compat`.
They are shipped in the same wheel and source distribution, with no imports,
subprocess launches, or runtime reads from either original checkout. The main
desktop window exposes both inherited workbenches through its Compatibility menu.
This is one independently installable project with a unified pipeline and two
inherited workbenches; it is not yet a single redesigned screen for every option.

The original checkouts were read only. Exact source commits and SHA-256 hashes
are in [COMPAT_SOURCE_INVENTORY.json](COMPAT_SOURCE_INVENTORY.json). MIT notices
are included in both packaged namespaces. Only tracked runtime files were
imported; no saved keys, download libraries, virtual environments, or old builds
were imported.

## Capability matrix

| Original capability | Unified workflow | Inherited workflow in this package |
|---|---|---|
| Alloy/formula/chemical-system/MP-ID input | `discover`, `run` | `compat phasescout` |
| All subsystems, near-stable, full-system, explicit MP IDs | Discovery modes | Original CLI modes/options |
| Candidate preview without downloading | `discover` | `--dry-run` |
| Download caps and large-download authorization | `run` options | Original `--max-total`, `--confirm-above`, `--yes` |
| Conventional/primitive structure download | `run` | Original GUI/CLI cell options |
| Scheme-B filenames, numbered batches, applicability labels | Different bundle schema | Original filenames, `--label`, `--out-root`, `--applies-to`, `phase_index.csv` |
| MP numerical elasticity and provenance | Typed tensors and strict frame validation | Original JSON/index/provenance text |
| Offline literature search pack and live OpenAlex hints | Not a numerical tensor source | `--elasticity-web-offline`, default web fallback, `--no-elasticity-web` |
| API-key saving/clearing | Main GUI keeps key in memory | Inherited GUI saves explicitly to user data directory |
| Multiple CIFs/folders, recursive scan, drag/drop | Main GUI, analyze, quick-export | Original desktop and quick-export paths |
| Cu/source presets, manual energy/wavelength, d-range | Main CLI/GUI | Original CLI/GUI behavior |
| pymatgen diffraction and original R columns | Gemmi engine with declared differences | Original pymatgen engine and schemas |
| Cubic/full Cij input and hkl-normal modulus | Main GUI and tensor contracts | Original Cij input/editor and sidecar bridge |
| Excel, CSV, JSON, beginner table, structure/overlap views | Unified bundle and lab views | Original workbook, CSV and JSON sidecars |
| Separate continuous-pattern workbook and axis options | Profile CSV in bundle | Original pattern XLSX in 2theta/d/q/g |
| Publication SVG/PDF/EPS/PNG/TIFF | Unified figure options | Original five-format publication exporter |
| Experimental numeric-pattern loader | No experimental fitting | Original Python loader retained |
| Chinese/English GUI, preview, rename, open exports | Main GUI | Original CIF2Peaks workbench |
| Windows portable distribution | Real builder added | Both inherited workbenches collected into the same executable |

## Install and use

```sh
python -m pip install ".[complete]"
diffractscout gui
diffractscout compat --help
diffractscout compat cif2peaks path/to/cifs -o peaks.xlsx --export-patterns
diffractscout compat cif2peaks-gui
diffractscout compat cif2peaks-quick-export path/to/sample.cif
diffractscout compat phasescout "Ti-Al-V" --dry-run --out-dir candidates
diffractscout compat phasescout "Ti-Al-V" --elasticity --elasticity-web-offline --yes
diffractscout compat phasescout-gui
```

`complete` installs the third-party libraries needed by both inherited workflows;
it does not install either original project. The smaller base install remains
available for offline Gemmi workflows. No old top-level module names or console
commands are registered, so another installed CIF2Peaks/PhaseScout is not shadowed.

PhaseScout settings and default downloads are now under
`%LOCALAPPDATA%/DiffractScout` on Windows or `~/.local/share/DiffractScout` elsewhere.
`DIFFRACTSCOUT_DATA_DIR` overrides that location. Existing settings are not silently
copied. `MP_API_KEY` and explicit output paths remain supported.

For Python callers, import `diffractscout.compat.cif2peaks.<module>` or
`diffractscout.compat.phasescout.<module>`. Their APIs and export names are retained;
the namespace is intentionally different. `compat` outputs retain upstream schemas
and exit codes and do not acquire the unified pipeline's transactional manifest.

## Scientific compatibility

The inherited engine is retained for reproducing old calculations, not presented
as numerically interchangeable with Gemmi. Its original intensity conventions,
tensor-frame assumptions and diagnostics remain in effect. In particular, legacy
elastic sidecar acceptance must not be interpreted as verification of a rotation
between an MP tensor and the emitted CIF. Use the unified pipeline for strict
frame validation and manifest verification. Literature hits remain bibliographic
clues and are never promoted into numerical stiffness tensors.

## Validation and limits

Final local regression: **690 passed, 5 skipped**. The five skips require
undistributed upstream CIF fixtures. GUI/dispatch follow-up: **63 passed**.
Installed-wheel workflows ran outside the checkout. The frozen executable passed
offline demo/manifest verification and exported 83 inherited reflections from
three CIFs. All three frozen GUI windows started and closed successfully. The
portable ZIP was generated with Tcl/Tk and tkinterdnd2 runtime files present.

The original baseline had 547 passing tests and one transient Tk startup skip.
The imported runtime regression suite initially passed 135 tests, with five skips
for upstream private CIF fixtures that are not distributed. Nine upstream tests
for the old package metadata, old build scripts and agent instructions are listed
explicitly in `tests/inherited/EXCLUSIONS.json`; they are not evidence for the new
distribution. New tests cover dispatch, optional dependencies, source inventory,
user storage, portable archive validation and construction of both workbenches.

Online Materials Project acquisition and live OpenAlex responses require separate
live verification. Offline provider tests do not establish current service access.
Desktop construction tests do not establish drag/drop or visual-layout quality.
The two upstream repositories have not been removed or archived.

## Portable build

```sh
python -m pip install ".[complete,windows]"
python scripts/package_windows_portable.py --build
```

The builder collects both engines/workbenches, runs frozen help commands and a
verified offline demo, validates Tcl/Tk and examples, and creates the full-folder
ZIP. It refuses an existing app output directory; use a fresh `--dist` for another
build. A wheel build alone does not prove the frozen application works.
