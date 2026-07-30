# Scientific contracts and calculation boundaries

This document defines the numerical quantities emitted by DiffractScout. Changes to these definitions require tests, changelog entries and review by a contributor with relevant diffraction or elasticity expertise.

## CIF identity and structure

- The exact input CIF is copied into `inputs/` and identified by SHA-256.
- A CIF data block must contain six unit-cell parameters and fractional atom coordinates.
- The declared space group is interpreted by Gemmi. Optional spglib support performs an independent symmetry search using the expanded unit-cell sites.
- Partial occupancies are retained in the structure-factor calculation and generate a warning.
- DiffractScout does not repair atom labels, occupancies, chemical composition, oxidation states or crystallographic settings.

## Radiation

Energy and wavelength are related by

$$
E\lambda = 12.398419843320026\;\text{keV Å}.
$$

Built-in single-wavelength presets are:

| Source | Wavelength (Å) |
|---|---:|
| Cu Kα | 1.5406 |
| Co Kα | 1.78897 |
| Fe Kα | 1.93604 |
| Mo Kα | 0.7093 |
| Ag Kα | 0.5594 |

These presets represent one effective wavelength. Kα1/Kα2 doublets and spectral distributions are not expanded in the current version.

## Reflection geometry

For each allowed reflection,

$$
2d\sin\theta = \lambda,
$$

$$
q = \frac{4\pi\sin\theta}{\lambda} = \frac{2\pi}{d},
\qquad
g = \frac{1}{d}.
$$

Gemmi supplies unique Miller indices, space-group operations and systematic-absence checks. The exported representative `hkl` is a deterministic member of the symmetry family; `multiplicity` is the number of distinct symmetry- and Friedel-related indices.

## Intensity channels

Gemmi calculates the X-ray structure factor for the average CIF structure. Before this calculation,
DiffractScout applies Gemmi's `change_occupancies_to_crystallographic()` conversion on a dedicated
copy of the parsed small structure. This accounts for special-position multiplicity while leaving
the original CIF occupancies unchanged for validation and composition reporting. The synthetic FCC
test verifies the analytic result $|F_{111}|^2=(4f_{\mathrm{Al}})^2$.

DiffractScout reports

$$
I_{\mathrm{no\,LP}} = m_{hkl}|F_{hkl}|^2,
$$

where $m_{hkl}$ is multiplicity. The unpolarized laboratory-style Lorentz-polarization factor is

$$
LP(\theta) = \frac{1 + \cos^2(2\theta)}{\sin^2\theta\cos\theta},
$$

and

$$
I_{\mathrm{with\,LP}} = I_{\mathrm{no\,LP}}LP(\theta).
$$

DiffractScout also reports two project-defined volume-normalized theoretical intensity channels:

$$
J_{hkl}^{\mathrm{with\,LP}} = \frac{I_{\mathrm{with\,LP}}}{V_{\mathrm{cell}}^2},
\qquad
J_{hkl}^{\mathrm{no\,LP}} = \frac{I_{\mathrm{no\,LP}}}{V_{\mathrm{cell}}^2}.
$$

The export schema retains `material_scattering_factor_R_hkl` and `material_scattering_factor_R_hkl_no_lp` as compatibility aliases inherited from CIF2Peaks. Those names refer exactly to the two $J_{hkl}$ quantities above. They are not crystallographic residual R factors, standardized quantitative-phase-analysis coefficients, or experimentally calibrated material scattering factors. Their use with experimental integrated areas requires a correction scheme consistent with the selected LP channel and every other experimental effect.

## Display profile

Each discrete line is broadened with a pseudo-Voigt function:

$$
p(x) = \eta L(x;\mathrm{FWHM}) + (1-\eta)G(x;\mathrm{FWHM}).
$$

The profile is normalized to a maximum of 100. The width and mixing fraction are user inputs. No instrument function, axial divergence, wavelength doublet, microstrain, crystallite size or detector response is inferred.

## Elastic tensor

The accepted stiffness matrix is a finite 6×6 matrix in GPa using Voigt order

```text
[11, 22, 33, 23, 13, 12]
```

with engineering shear strain. DiffractScout:

1. symmetrizes a matrix outside tolerance using $(C+C^T)/2$ and records a warning;
2. rejects singular matrices;
3. rejects matrices that are not positive definite;
4. reports a warning for severe ill-conditioning;
5. preserves source, nature of data and coordinate-frame labels.

For a unit vector $n=(l,m,n)$ normal to the reciprocal-lattice plane `hkl`, define

$$
q(n) = [l^2,m^2,n^2,mn,ln,lm]^T.
$$

With compliance $S=C^{-1}$,

$$
E(n) = \frac{1}{q(n)^T S q(n)}.
$$

The plane normal is obtained by orthogonalizing the reciprocal-lattice vector. For Materials Project downloads, automatic directional coupling uses the raw/POSCAR-format tensor documented as consistent with the conventional-standard CIF; its declared frame is `materials_project_conventional_cif_cartesian`. The IEEE-format tensor is retained for provenance because it may differ by a rotation. An IEEE-only record receives status `frame_transform_required`, and all `hkl`-normal modulus fields remain empty until an explicit, verified transformation into the CIF Cartesian frame is available. Primitive-cell downloads are rejected when automatic elasticity coupling is enabled.

## Database semantics

Materials Project structures are computed records and commonly DFT-relaxed. A downloaded structure is a candidate reference, not proof that the corresponding phase exists in an experiment. `energy_above_hull` is retained as provider metadata; it is not an experimental stability measurement.

Materials Project elastic tensors are labeled `DFT_calculated` and `not_experimental=true`. When no numerical tensor is returned, modulus fields remain empty. DiffractScout does not extract tensors from literature text or generate substitute values.

## Excluded analyses

The current version does not perform:

- experimental phase identification;
- Rietveld, Le Bail or Pawley refinement;
- quantitative phase analysis;
- preferred-orientation, absorption or fluorescence correction;
- background, zero-shift or specimen-displacement fitting;
- crystallite-size or microstrain extraction;
- instrument calibration or absolute intensity calibration;
- uncertainty propagation from structural parameters or database calculations.
