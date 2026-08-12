# Validation strategy

## Current automated suite

The default suite is offline and deterministic:

```bash
pytest -q
```

Current v0.3.0 release-candidate status: **68 tests passing**, plus **45/45 analytic scientific benchmark checks**.

The suite covers:

### Composition and discovery

- alloy-grade, compact-formula, chemical-system, and Materials Project ID parsing;
- subsystem enumeration, order limits, and pre-provider combinatorial query limits;
- invalid negative/non-finite energy limits and non-positive count limits;
- candidate deduplication and deterministic ranking;
- explicit-ID provider lookup and provider-neutral source URLs;
- distinct provider-query, no-record, no-tensor, and frame-transform statuses.

### CIF and symmetry

- selection of a structure-bearing CIF data block;
- finite positive cell geometry and atomic-site requirements;
- space-group resolution from explicit symbol, explicit International Tables number, Gemmi inference, and warned P1 fallback;
- detection of declaration and spglib cross-check mismatches;
- partial-occupancy reporting;
- separation of original occupancies from the structure-factor copy.

### Diffraction

- FCC systematic absences and reflection-family multiplicities;
- analytic monoatomic-FCC structure factor $|F_{111}|^2=(4f_{\mathrm{Al}})^2$ after Gemmi's crystallographic-occupancy conversion;
- Bragg geometry and $q=2\pi/d$;
- LP and no-LP intensity definitions, phase-internal normalization, and profile normalization;
- rejection of unknown source presets, nonphysical scan/profile inputs, conflicting CLI energy/wavelength inputs, excessive profile grids, and excessive reciprocal-candidate estimates.

### Elasticity

- exact 6×6 shape, finite values, symmetry handling, inversion, positive definiteness, and conditioning warnings;
- cached compliance inversion for repeated directional evaluation;
- direction-independent $E=110$ GPa for an explicitly synthetic isotropic cubic tensor;
- exact sidecar pairing, declared-CIF conflicts, ambiguous matches, invalid matrices, and coordinate-frame boundaries;
- Materials Project raw/conventional-CIF coupling and IEEE-only `frame_transform_required` behavior.

### Orchestration and output

- complete offline discovery → download → structure validation → diffraction → export;
- `--no-elasticity` suppression of sidecar discovery, copying, and calculation;
- input/output overlap rejection;
- non-destructive refusal to overwrite unrelated or damaged directories;
- transactional preservation of a previous valid bundle when staged export fails;
- stable headers for empty CSV tables;
- formula-injection escaping in CSV and XLSX;
- workbook creation including the `Diagnostics` sheet;
- download and elastic-query error export.

### Bundle integrity

- SHA-256 and byte-size verification;
- missing or modified file detection;
- malformed manifest entries without verifier crashes;
- duplicate, absolute, parent-traversal, empty, and manifest-self paths;
- symbolic links and root-escape attempts;
- files present on disk but absent from the manifest;
- deterministic evidence-archive ordering and timestamp normalization;
- rejection of archive outputs inside the source tree and symbolic-link inputs.

## Analytic reference suite

The command below executes an independent closed-form path for simple-cubic, BCC, FCC, NaCl, and cubic directional-elasticity cases:

```bash
diffractscout benchmark -o outputs/analytic_benchmark
```

The 45 checks cover allowed and forbidden families, multiplicity, cubic plane spacing, $q=2\pi/d$, analytic lattice structure factors, profile normalization, and `[100]`, `[110]`, `[111]` directional moduli. All fixtures and expectations are installed with the wheel. A completed bundle is verified against its own SHA-256 manifest. When `SOURCE_DATE_EPOCH` is fixed, repeated runs under the same software versions and platform produce identical hashes for every manifested benchmark file. See `docs/ANALYTIC_BENCHMARKS.md`.

The benchmark is an internal analytic validation with an implementation path separated from the production orchestration. It does not satisfy the project requirement for an external user or independent third-party comparison.

## Synthetic reference fixture

The offline demo uses:

- a synthetic `Fm-3m` cell with $a=4$ Å and one aluminium site in the asymmetric unit;
- a synthetic cubic tensor with $C_{11}=200$, $C_{12}=120$, and $C_{44}=40$ GPa.

The tensor satisfies $C_{44}=(C_{11}-C_{12})/2$, yielding $E=110$ GPa for every direction. The values are constructed for verification and labeled `synthetic_test_fixture`; they are not experimental aluminium properties.

Run the public smoke test:

```bash
diffractscout demo -o outputs/demo
diffractscout verify outputs/demo
```

Expected first five families in the 5–100° Cu Kα window:

```text
(111), (200), (220), (311), (222)
```

The forbidden FCC families `(100)` and `(110)` must be absent.

## GUI validation

The GUI form converters are unit-tested independently of a display. A Linux CI smoke step starts the complete Tk application under Xvfb, runs one update cycle, and destroys it cleanly:

```bash
xvfb-run -a python -c \
  "from diffractscout.gui import create_app; app=create_app(); app.update(); app.destroy()"
```

Reference screenshots are stored in `docs/assets/gui-local.png` and `docs/assets/gui-materials-project.png`. They document the v0.3.0 control layout; they are not substitutes for functional tests.

## CI and packaging validation

The configured GitHub Actions checks are:

- Python 3.10–3.13 on Ubuntu;
- Ruff error and unused-name checks;
- source compilation;
- coverage threshold of 65% for the headless scientific, orchestration, provider, export, and verification code; the Tk controller and one-line module launcher are excluded from the line metric and checked by form-unit tests plus the Xvfb construction smoke test;
- offline demo and manifest verification;
- Windows and macOS tests and demo smoke runs;
- Linux Xvfb GUI construction;
- wheel build;
- wheel installation in a clean virtual environment;
- demo execution from the installed wheel;
- Open Journals draft-PDF compilation;
- non-strict JOSS readiness and evidence-ledger generation;
- tag-driven release packaging with wheel, source distribution, deterministic benchmark/demo/readiness archives, metadata validation, and SHA-256 inventory;
- a monthly reproducibility audit that reruns release and scientific checks and retains evidence artifacts for 90 days;
- monthly Dependabot pull requests for Python and GitHub Actions dependencies.

Local release preflight:

```bash
python scripts/check_release.py
```

The script checks required files, version consistency, bibliography keys, source compilation, the test suite, the offline demo, analytic benchmark, manifest verification, JOSS evidence machinery, and wheel creation. The wheel still requires a clean-environment installation test; CI performs that step on each package job. Release and monthly workflows create archives through `scripts/archive_tree.py`, which sorts paths, uses a fixed timestamp derived from `SOURCE_DATE_EPOCH`, stores a single safe root, rejects symbolic links, and writes atomically.

Scheduled audit runs show that one public commit remains reproducible at a later date. They do not establish distributed development by themselves. Substantive six-month evidence must come from reviewed software changes, scientific validation, documentation improvements, support activity, releases, issues, or pull requests tied to real work.

## PDF verification

After `paper/paper.pdf` is rebuilt, render it to images and inspect every page:

```bash
python /home/oai/skills/pdfs/scripts/render_pdf.py paper/paper.pdf \
  --out_dir /tmp/diffractscout-paper-render --dpi 200
```

Check headings, equations, table/figure placement, references, clipping, missing glyphs, and page balance. The exact JOSS draft is produced by the Open Journals workflow.

## Evidence still required before JOSS submission

Automated numerical tests establish declared software contracts. They do not establish experimental validity or research impact. The submission record should add:

1. a representative set of CIF peak positions and intensities compared with an independent crystallography package using documented tolerances;
2. at least one archived laboratory or synchrotron XRD planning/interpretation case with redistributable inputs;
3. one elastic-tensor case checked against an independent implementation or analytic crystal-class result;
4. documented use in a real research workflow and preferably evaluation by an external group;
5. issue or pull-request records showing feedback-driven refinement;
6. repeated tagged releases and a software archive DOI.

These cases should be versioned in `validation_cases/` or a separately archived reproducibility repository. Experimental inputs that cannot be redistributed should be represented by a lawful, documented public substitute rather than silently omitted.
