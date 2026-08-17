# Scientific contracts and calculation boundaries

This document defines the numerical quantities and validation rules emitted by DiffractScout. Any change to these contracts requires regression tests, a changelog entry, and review by a contributor with relevant diffraction or elasticity expertise.

## 1. Source identity and CIF handling

- The exact input CIF is copied into `inputs/` and identified by SHA-256.
- A structure-bearing data block must contain six finite unit-cell parameters and at least one fractional atomic site.
- Cell lengths must be positive; angles must lie strictly between 0° and 180°; the computed cell volume must be finite and positive.
- DiffractScout records the selected CIF data-block name.
- Local inputs remain unchanged. A dedicated Gemmi structure copy is used for structure-factor occupancy conversion.
- Partial occupancies are retained as an average-structure model and generate an explicit warning.
- DiffractScout does not invent or repair atom labels, occupancies, compositions, oxidation states, disorder models, or crystallographic settings.

### Space-group resolution

Space-group identity is resolved in the following order and the chosen source is recorded:

1. explicit CIF Hermann–Mauguin symbol;
2. explicit International Tables number;
3. Gemmi inference from the parsed small structure;
4. P1 fallback with a warning when no reliable declaration can be resolved.

A disagreement between explicit symbol and number, or between the declared group and the independent spglib search, is recorded as a diagnostic. The diffraction calculation uses the resolved Gemmi group; users must review any mismatch before interpreting systematic absences.

## 2. Radiation definition

Energy and wavelength are related by

$$
E\lambda = 12.398419843320026\;\text{keV Å}.
$$

Built-in effective single-wavelength presets are:

| Source | Wavelength (Å) |
|---|---:|
| Cu Kα | 1.5406 |
| Co Kα | 1.78897 |
| Fe Kα | 1.93604 |
| Mo Kα | 0.7093 |
| Ag Kα | 0.5594 |

Explicit energy and wavelength inputs must be finite and positive. The CLI treats these two inputs as mutually exclusive. A custom source requires an explicit wavelength.

The presets represent one effective wavelength. Kα1/Kα2 doublets, spectral bandwidth, harmonic contamination, and source polarization are not expanded in the current version.

## 3. Reflection geometry

For each allowed reflection,

$$
2d\sin\theta = \lambda,
$$

$$
q = \frac{4\pi\sin\theta}{\lambda} = \frac{2\pi}{d},
\qquad
g = \frac{1}{d}.
$$

Gemmi supplies unique Miller indices, space-group operations, and systematic-absence checks. The exported representative `hkl` is a deterministic member of its symmetry family. `multiplicity` is the number of distinct symmetry- and Friedel-related indices used by the implemented family construction.

The scan window must satisfy

```text
0 <= 2θ_min < 2θ_max <= 180°
```

and the display-profile step and FWHM must be finite and positive. The pseudo-Voigt mixing fraction must lie in `[0, 1]`.

Candidate generation uses a relative $d_{min}$ search margin of $10^{-10}$ plus `nextafter(d_min, 0)` to avoid floating-point exclusion of a reflection exactly at the upper $2\theta$ boundary. The requested angular interval is then enforced directly with a $10^{-9}$ degree comparison tolerance. The search margin improves completeness and does not intentionally widen the exported scan range.

## 4. X-ray structure factors and intensity channels

Gemmi calculates the X-ray structure factor for the average CIF structure. Before calculation, DiffractScout calls Gemmi's crystallographic-occupancy conversion on a dedicated structure-factor copy. This accounts for special-position multiplicity while preserving original CIF occupancies for validation and composition reporting. The analytic FCC regression test verifies

$$
|F_{111}|^2=(4f_{\mathrm{Al}})^2
$$

for a monoatomic conventional `Fm-3m` fixture.

DiffractScout reports

$$
I_{\mathrm{no\,LP}} = m_{hkl}|F_{hkl}|^2,
$$

where $m_{hkl}$ is multiplicity. The implemented unpolarized laboratory-style Lorentz-polarization factor is

The exported per-multiplicity structure-factor helpers are defined by

$$
\mathrm{mean\_structure\_factor\_sq\_per\_multiplicity}
=\frac{I_{\mathrm{no\,LP}}}{m_{hkl}}=|F_{hkl}|^2,
$$

$$
\mathrm{mean\_structure\_factor\_abs\_per\_multiplicity}
=\sqrt{|F_{hkl}|^2}=|F_{hkl}|.
$$

Here “mean” retains the CIF2Peaks-compatible name for the per-equivalent-family
value. It does not average unrelated reflections or divide $|F|^2$ by
multiplicity a second time.

$$
LP(\theta) = \frac{1 + \cos^2(2\theta)}{\sin^2\theta\cos\theta},
$$

and

$$
I_{\mathrm{with\,LP}} = I_{\mathrm{no\,LP}}LP(\theta).
$$

Two project-defined volume-normalized channels are exported:

$$
J_{hkl}^{\mathrm{with\,LP}} = \frac{I_{\mathrm{with\,LP}}}{V_{\mathrm{cell}}^2},
\qquad
J_{hkl}^{\mathrm{no\,LP}} = \frac{I_{\mathrm{no\,LP}}}{V_{\mathrm{cell}}^2}.
$$

The preferred output names are:

```text
volume_normalized_intensity_with_lp
volume_normalized_intensity_no_lp
```

The legacy names below remain for CIF2Peaks schema compatibility:

```text
material_scattering_factor_R_hkl
material_scattering_factor_R_hkl_no_lp
```

Those aliases refer exactly to the two $J_{hkl}$ quantities. They do not represent crystallographic residual R factors, standardized quantitative-phase-analysis coefficients, or experimentally calibrated material scattering factors. Relating them to experimental integrated areas requires a correction chain consistent with the selected LP channel and all other experimental effects.

The highest `I_with_LP` line within each phase is normalized to 100 for display. This phase-internal normalization does not make intensities comparable across separate structures, experiments, instruments, or compositions.

### Current structure-factor omissions

The current implementation does not infer or fit:

- Debye–Waller parameters that are absent from the CIF;
- anomalous-dispersion corrections tied to a specific absorption edge;
- preferred orientation;
- absorption, fluorescence, extinction, polarization geometry beyond the stated LP expression;
- sample amount or phase fraction;
- instrument response and wavelength doublets.

## 5. Display profile

Each discrete line is broadened with a pseudo-Voigt function:

$$
p(x) = \eta L(x;\mathrm{FWHM}) + (1-\eta)G(x;\mathrm{FWHM}).
$$

The summed profile is normalized to a maximum of 100. FWHM and mixing fraction are user inputs stored in provenance. The profile is a visualization and interoperability product. It is not a fitted instrument function and contains no inferred axial divergence, spectral doublet, microstrain, crystallite size, detector response, or background.

## 6. Resource and query limits

Large angular grids, small-$d$ reflection searches, and unrestricted chemical-subsystem expansion can consume substantial memory, API quota, and runtime. DiffractScout applies three explicit guards before the expensive operation begins:

1. `max_profile_points` limits the requested continuous grid size;
2. `max_reflection_estimate` limits a conservative reciprocal-space estimate and the actual generated Miller-candidate count;
3. `max_subsystems` limits the number of chemical-subsystem provider queries implied by the parsed element set and `max_subsystem_order`.

The conservative estimate is proportional to the reciprocal-space sphere implied by the minimum accessible spacing and the direct-cell volume. It is a safety estimate, not a physical prediction of allowed reflections. Both configured limits, the estimate, and the actual candidate count are recorded in analysis metadata.

Increasing any limit is an explicit user decision. Lowering the profile step or extending to very high angle can trigger the profile guard. Large unit cells and small accessible $d$ can trigger the reciprocal-candidate guard. High-component systems can generate combinatorial subsystem counts; DiffractScout evaluates the binomial count before constructing the query list or contacting the provider and rejects counts above `max_subsystems`.

## 7. Elastic tensor

The accepted stiffness matrix is a finite 6×6 matrix in GPa using Voigt order

```text
[11, 22, 33, 23, 13, 12]
```

with engineering shear strain. Sidecars may declare Pa, kPa, MPa, GPa, or TPa; values are converted to GPa before validation and the conversion is recorded. Generic matrix fields without a unit retain legacy GPa interpretation with an explicit warning. Unknown units stop directional evaluation. DiffractScout:

1. requires an exact 6×6 shape;
2. rejects non-finite entries;
3. symmetrizes a matrix outside tolerance using $(C+C^T)/2$ and records a warning;
4. rejects singular matrices;
5. rejects matrices that are not positive definite;
6. records a warning for severe ill-conditioning;
7. preserves provider, record ID, source URL, methodology URL, nature of data, coordinate frame, and original sidecar path.

For a unit vector $n=(l,m,n)$ normal to reciprocal-lattice plane `hkl`, define

$$
q(n) = [l^2,m^2,n^2,mn,ln,lm]^T.
$$

With compliance $S=C^{-1}$,

$$
E(n) = \frac{1}{q(n)^T S q(n)}.
$$

The normal is obtained from the reciprocal-lattice vector and normalized in the CIF Cartesian frame. The compliance inverse is cached within one tensor object because a phase can contain many reflections.

## 8. Elastic sidecar identity and coordinate frames

A numerical tensor is paired only when the relation to the CIF is unique. Pairing can use an exact `{cif_stem}_elasticity.json`, an explicit `paired_cif`/`cif_filename`, an unambiguous material identifier, or an unambiguous index row. The following cases stop automatic directional evaluation and generate diagnostics:

- an exact-name sidecar declares a different paired CIF;
- several sidecars match the same CIF;
- several index rows match the same CIF;
- the payload is malformed or lacks a valid 6×6 tensor;
- the tensor coordinate frame is absent or incompatible;
- a provider query failed.

For Materials Project downloads, automatic directional coupling uses the raw/POSCAR-format tensor paired with the conventional-standard CIF and declares

```text
materials_project_conventional_cif_cartesian
```

The IEEE-format tensor is retained for provenance because it may differ by a rotation. An IEEE-only record receives status `frame_transform_required`; all `hkl`-normal modulus fields remain empty until an explicit, verified transform into the CIF Cartesian frame is available. Primitive-cell downloads are rejected when automatic elasticity coupling is enabled.

Materials Project tensors are labeled `DFT_calculated` and `not_experimental=true`. A missing record remains missing. DiffractScout does not convert literature search results into numerical tensors.

## 9. Database semantics

A database record is a candidate reference. It is not proof that the phase exists in an experiment. `energy_above_hull` and stability flags remain provider metadata and are not experimental stability measurements. Candidate ranking is deterministic and does not constitute phase-probability inference.

Database query failure, no property document, a document without a tensor, a tensor requiring a frame transformation, and a run where elasticity was disabled are exported as distinct statuses. The disabled state is `not_requested`; it is not counted as missing data. This distinction prevents service outages or user choices from being silently reported as valid negative results.

## 10. Result-bundle integrity

All outputs are first written to a staging directory. CSV and workbook files use temporary-file replacement. The completed staging bundle is verified before it can replace the target directory.

The manifest verifier checks SHA-256, byte size, path safety, duplicate paths, symbolic links, root escapes, missing files, modified files, and files present on disk but absent from the manifest. A pre-existing bundle must itself pass verification before overwrite is allowed.

Spreadsheet cells derived from external provider/CIF text are prefixed when they begin with spreadsheet formula-control characters (`=`, `+`, `-`, `@`, tab, carriage return, or newline). This prevents exported metadata from being interpreted as an active spreadsheet formula.

## 11. Excluded analyses

The current version does not perform:

- experimental phase identification or automated phase assignment;
- Rietveld, Le Bail, or Pawley refinement;
- quantitative phase analysis;
- preferred-orientation, absorption, fluorescence, or extinction correction;
- background, zero-shift, specimen-displacement, or detector-geometry fitting;
- crystallite-size or microstrain extraction;
- instrument calibration or absolute intensity calibration;
- uncertainty propagation from CIF parameters, database calculations, or experimental observables;
- thermodynamic phase-fraction prediction;
- automatic literature extraction of structures or elastic tensors.
