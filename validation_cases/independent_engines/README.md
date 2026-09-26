# Independent reference-engine comparison

This case compares the offline Gemmi diffraction implementation with pymatgen's `XRDCalculator` using the project's explicitly synthetic analytic CIF fixtures. It also compares the project's cubic directional Young's-modulus calculation with a fourth-rank compliance-tensor contraction from pymatgen. The case is a numerical software cross-check; it is not experimental validation, a real-material property claim, or evidence of external-user adoption.

The generated results are in [the Markdown receipt](reference_engine_comparison.md) and [the machine-readable JSON receipt](reference_engine_comparison.json).

The inputs are the four CIFs already distributed with the package:

| Fixture | Synthetic cell and basis | Selection rule checked |
|---|---|---|
| `simple_cubic_al.cif` | Pm-3m, a = 3.5 Å, one Al site | Primitive-cubic reflections |
| `bcc_fe.cif` | Im-3m, a = 2.86 Å, one Fe site | h + k + l even; (100) and (111) absent |
| `fcc_al.cif` | Fm-3m, a = 4.0 Å, one Al site | h, k, l all odd or all even; (100) and (110) absent |
| `nacl.cif` | Fm-3m, a = 5.64 Å, Na at (0,0,0), Cl at (1/2,1/2,1/2) | F-centering parity rule; (100) and (110) absent |

The expected initial allowed families and cubic lattice parameters are maintained in [`expectations.json`](../../src/diffractscout/benchmark_data/expectations.json). The CIFs themselves are hashed in the generated JSON receipt so a changed fixture cannot silently reuse these results.

## Diffraction comparison

Both calculations use the same conventional synthetic CIF, an effective single wavelength of 1.5406 Å (Cu Kα), and a 2θ interval of 5–120°. DiffractScout is evaluated with `source_preset="Cu Ka"`; pymatgen reads each structure with `primitive=False` and runs `XRDCalculator(wavelength=1.5406, symprec=0).get_pattern(..., scaled=False, two_theta_range=(5, 120))`.

Peak families are grouped and matched by d-spacing, with a grouping/matching tolerance of 1 × 10⁻⁶ Å. A position comparison passes only when every group is matched and the maximum absolute differences satisfy both |Δd| ≤ 1 × 10⁻⁶ Å and |Δ2θ| ≤ 1 × 10⁻⁵°. This avoids requiring the two engines to choose identical representative Miller indices. It also accounts for coincident families: the script sums their calculated intensities before normalizing each case to a maximum of 100.

The tracked receipt was generated with Python 3.12.10, Gemmi 0.7.5, and pymatgen 2026.5.4. All four cases passed the peak-position and selection-rule checks. The maximum observed |Δd| was 1.33 × 10⁻¹⁵ Å and maximum |Δ2θ| was 7.11 × 10⁻¹⁴°. The maximum difference between independently normalized intensities was 0.790 percentage points across the four cases. Intensity differences are reported peak by peak in the JSON receipt but do not have an acceptance threshold: this is not a common-form-factor-model comparison, and agreement in the calculated pattern does not establish absolute experimental intensity accuracy.

The fixture CIFs omit explicit symmetry-operation loops and provide Hermann–Mauguin symbols and International Tables numbers. Pymatgen records a parser warning that it uses the declared Hermann–Mauguin symbol; these warnings are included in the receipt.

## Elastic comparison

The modulus check uses `fcc_al.cif` only to define a cubic Cartesian frame. It pairs that synthetic structure with the explicitly synthetic stiffness matrix (GPa)

```text
[[250, 150, 150,   0,   0,   0],
 [150, 250, 150,   0,   0,   0],
 [150, 150, 250,   0,   0,   0],
 [  0,   0,   0, 100,   0,   0],
 [  0,   0,   0,   0, 100,   0],
 [  0,   0,   0,   0,   0, 100]]
```

The order is [11, 22, 33, 23, 13, 12], with engineering shear strain. Pymatgen's `ElasticTensor.from_voigt` converts this matrix into its fourth-rank tensor representation; the reference Young's modulus is calculated as the reciprocal of the fourth-rank compliance contraction along each unit direction. This distinction matters because pymatgen's `ElasticTensor.directional_elastic_mod` contracts the stiffness tensor and therefore returns a longitudinal modulus, not the Young's modulus emitted by DiffractScout.

For [100], [110], and [111], both implementations returned 137.5, 209.5238095238096, and 253.8461538461537 GPa, respectively. The predeclared acceptance rule is |ΔE| ≤ max(1 × 10⁻⁸ GPa, 1 × 10⁻¹⁰ × |E_pymatgen|). The largest observed absolute difference was 5.69 × 10⁻¹⁴ GPa. This is a convention and implementation check on an analytic tensor, not validation of an experimental or database elastic tensor.

## Reproduction

The optional `mp` dependency group supplies pymatgen. From a development installation:

```text
pip install -e ".[mp]"
python scripts/compare_reference_engines.py --output validation_cases/independent_engines
```

The script exits with status 0 only when geometry, selection-rule, and elastic checks pass. It writes `reference_engine_comparison.json` with the per-peak values, hashes, software versions, warnings, and tolerances, plus `reference_engine_comparison.md` with a compact result table. Intensity differences remain diagnostic and never affect the exit status. The script and matching helpers are tested by `tests/test_reference_engine_comparison.py`; those tests need only the project's core/test dependencies and do not import pymatgen.

## Official method references

- [pymatgen XRDCalculator documentation](https://pymatgen.org/pymatgen.analysis.diffraction.html#pymatgen.analysis.diffraction.xrd.XRDCalculator) describes the reciprocal-point search, atomic scattering factors, structure-factor intensity, Lorentz-polarization correction, configurable wavelength, and unscaled-pattern option.
- [Gemmi scattering documentation](https://gemmi.readthedocs.io/en/latest/scattering.html) describes X-ray form factors and the direct `StructureFactorCalculatorX` summation, including occupancy conversion for small-structure CIF input.
- [pymatgen ElasticTensor documentation](https://pymatgen.org/pymatgen.core.elasticity.html#pymatgen.core.elasticity.elastic.ElasticTensor) describes the fourth-rank elastic tensor, its GPa units, and compliance tensor derived from the Voigt stiffness matrix.
- The calculation quantities and conventions checked here are also stated in [`SCIENTIFIC_CONTRACTS.md`](../../docs/SCIENTIFIC_CONTRACTS.md), especially its diffraction intensity and elastic-tensor sections.

Documentation pages were checked on 2026-09-26. The JSON receipt records the exact package versions used for its numerical results.
