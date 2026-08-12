# Diffraction engine parity: Gemmi vs CIF2Peaks (pymatgen)

DiffractScout’s offline powder engine is built on **Gemmi**. CIF2Peaks used
**pymatgen** `XRDCalculator` for theoretical powder lines. The two implementations
are designed for **workflow parity**, not bit-identical intensities.

## What “workflow parity” means

Both tools aim to produce, from a structure-bearing CIF and an X-ray wavelength:

1. indexed reflections with Miller indices, \(d\), \(\theta\), \(2\theta\), \(q\), \(g\);
2. structure-factor-related intensities with and without a laboratory-style
   Lorentz–polarization (LP) factor;
3. phase-internal relative intensities (strongest line scaled to 100);
4. volume-normalized intensity channels
   \(J = I / V_{\mathrm{cell}}^2\) (legacy names still contain `R_hkl`);
5. optional plane-normal Young’s modulus when a valid \(C_{ij}\) is paired;
6. a continuous pseudo-Voigt display profile for plotting.

Users can move the same scientific questions—candidate peaks, LP vs no-LP
channels, elasticity on `hkl` normals—between the two codebases with the column
aliases in [`SCHEMA_ALIASES.md`](SCHEMA_ALIASES.md).

## What is **not** guaranteed

| Quantity | Expectation |
|---|---|
| Absolute \(I\) or \(J\) values | May differ between Gemmi and pymatgen |
| Peak-by-peak intensity ordering near ties | May swap when values are close |
| Multiplicity of a given representative | Same physical idea; counting of symmetry/Friedel mates can differ in edge cases |
| Representative `hkl` of a family | Both pick a deterministic member; the choice rule may differ |
| Multi-family coincidence at one \(2\theta\) | CIF2Peaks could merge pymatgen families into one peak row; DiffractScout emits one row per unique family |
| Floating-point \(2\theta\), \(d\), \(q\) | Agree to crystallographic precision for clean cells; not bit-identical |

Do **not** use bit-identical intensity regression between CIF2Peaks exports and
DiffractScout as a release gate. Prefer analytic structure-factor checks (e.g.
monoatomic FCC \(\lvert F_{111}\rvert^2\)), space-group absences, and internal
invariants (\(J = I / V^2\), LP ratio consistency).

## Architectural differences

| Topic | CIF2Peaks (pymatgen) | DiffractScout (Gemmi) |
|---|---|---|
| Structure I/O | pymatgen structure from CIF | Gemmi small structure; dedicated occupancy conversion for SF |
| Powder intensities | `XRDCalculator.get_pattern(scaled=False)` | Enumerate Miller candidates, absences, \(\lvert F\rvert^2\), multiplicity, LP |
| Atomic form factors / SF | pymatgen calculator defaults | Gemmi `StructureFactorCalculatorX` |
| Debye–Waller | Assumed 1 when absent | Same practical boundary; missing \(B\) not invented |
| LP factor | Same laboratory-style form \((1+\cos^2 2\theta)/(\sin^2\theta\cos\theta)\) | Same formula in `diffraction.py` |
| Volume-normalized \(J\) | `I_unscaled / V^2` and `(I_unscaled/LP)/V^2` | `I_with_LP / V^2` and `I_no_LP / V^2` |
| Offline base install | Required pymatgen for local XRD | Core analysis uses Gemmi; pymatgen optional via mp-api |
| Provenance | Export notes | SHA-256 inputs, manifest, scientific boundary string |

## Intensity channel correspondence

Conceptually:

```text
I_with_LP  ≈ theoretical_intensity_unscaled   (CIF2Peaks)
I_no_LP    ≈ multiplicity_structure_factor_sq (CIF2Peaks)
J_with_LP  = I_with_LP / V_cell^2  ↔  material_scattering_factor_R_hkl
J_no_LP    = I_no_LP / V_cell^2    ↔  material_scattering_factor_R_hkl_no_lp
```

The **definitions** of the \(J\) channels match. The **numerators** come from
different structure-factor stacks, so \(J\) values are workflow-comparable, not
byte-equal.

## Systematic absences and indexing

Both engines respect crystallographic absences for the resolved space group.
DiffractScout records space-group resolution order and optional spglib
cross-checks in diagnostics. A mismatch between declared and detected symmetry
is a user-review item in both ecosystems; it can change which lines appear.

## Hexagonal / trigonal labels

CIF2Peaks often retained four-index Miller–Bravais labels when pymatgen supplied
them. DiffractScout stores three-index \(h,k,l\) on `ReflectionRecord` and can
format four-index **display** labels with `label_hkl_for_crystal_system` in
`hkl.py` when the crystal system string indicates hexagonal or trigonal families.
Plane-normal elasticity always uses the three-index plane
`plane_hkl_for_normal` (requiring \(i = -(h+k)\) for four-index input).

## Validation guidance

1. **Contract tests**: \(J = I / V^2\), ranks consistent with channels, LP ratio
   \(I_{\mathrm{with\,LP}} / I_{\mathrm{no\,LP}}\).
2. **Analytic fixtures**: known monoatomic cells and expected \(\lvert F\rvert^2\).
3. **Cross-engine comparison**: compare \(d\) and \(2\theta\) to a tight tolerance;
   compare intensity **ratios** or top-\(N\) peak sets, not raw floats.
4. **Never** treat legacy `R_hkl` columns as Rietveld residuals (see
   `SCHEMA_ALIASES.md` and `SCIENTIFIC_CONTRACTS.md`).

## Summary

DiffractScout preserves the CIF2Peaks **scientific workflow** (indexed peaks, LP
split, volume-normalized channels, optional \(E(n_{hkl})\), plottable profile)
while moving crystallographic computation to Gemmi for an offline-first,
provenance-oriented package. Intensity parity is **semantic**, not bitwise.
