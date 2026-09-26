# Independent pymatgen reference comparison

Generated: `2026-09-26T12:37:13+00:00`

Overall acceptance: **PASS**

This receipt records independent software comparisons on explicitly synthetic benchmark fixtures. It is not experimental validation, a real-material property claim, or external-user evidence.

## Software and settings

- Python: `3.12.10`
- Comparison script SHA-256: `e8a8bd9e7742d120347ad543faaa278c0e33b9fb1556e9e2cb0b63fbf2e985b3`
- Gemmi: `0.7.5`
- pymatgen: `2026.5.4`
- Radiation: Cu Kα effective wavelength `1.5406 Å`
- 2θ range: `5.0–120.0°`
- Peak grouping/matching: `|Δd| ≤ 1e-06 Å`; geometry acceptance also requires `|Δ2θ| ≤ 1e-05°`.
- Diffraction intensities use each engine's unscaled theoretical pattern, are grouped at coincident d, and are separately normalized to a per-case maximum of 100; differences are diagnostic only.

## Diffraction peak positions and selection rules

| Synthetic CIF | Gemmi families | pymatgen groups | Matched d groups | max abs Δd (Å) | max abs Δ2θ (°) | position | selection | max intensity difference (points) |
|---|---:|---:|---:|---:|---:|:---:|:---:|---:|
| `src/diffractscout/benchmark_data/simple_cubic_al.cif` (simple_cubic_al) | 14 | 13 | 13 | 2.22e-16 | 4.26e-14 | PASS | PASS | 0.4517 |
| `src/diffractscout/benchmark_data/bcc_fe.cif` (bcc_fe) | 5 | 5 | 5 | 3.33e-16 | 7.11e-14 | PASS | PASS | 0.4657 |
| `src/diffractscout/benchmark_data/fcc_al.cif` (fcc_al) | 8 | 8 | 8 | 2.22e-16 | 4.26e-14 | PASS | PASS | 0.7899 |
| `src/diffractscout/benchmark_data/nacl.cif` (nacl) | 16 | 14 | 14 | 1.33e-15 | 7.11e-14 | PASS | PASS | 0.5716 |

The comparison groups lines by d-spacing rather than requiring identical representative hkl labels. Pymatgen may return a single pattern peak containing several hkl families where DiffractScout returns separate family rows; the comparison therefore sums coincident-family intensities before per-case normalization.

## Cubic directional Young's modulus

The same synthetic stiffness matrix in GPa is interpreted with Voigt order `['11', '22', '33', '23', '13', '12']` and engineering shear strain. Acceptance is `|ΔE| ≤ max(1e-08 GPa, 1e-10 × |E_pymatgen|)`.

| Plane normal | DiffractScout (GPa) | pymatgen (GPa) | abs ΔE (GPa) | Result |
|---|---:|---:|---:|:---:|
| `[1, 0, 0]` | 137.5 | 137.5 | 0 | PASS |
| `[1, 1, 0]` | 209.523809524 | 209.523809524 | 5.68e-14 | PASS |
| `[1, 1, 1]` | 253.846153846 | 253.846153846 | 5.68e-14 | PASS |

## Reproduction

Install the optional Materials Project dependencies, then run from the repository root:

```sh
python scripts/compare_reference_engines.py --output validation_cases/independent_engines
```

The tracked JSON receipt records relative CIF paths and SHA-256 hashes, software versions, thresholds, per-peak results, selection-rule outcomes, and tensor results. The script exits nonzero if peak geometry/selection or elastic acceptance checks fail. Intensity differences do not affect the exit status.
