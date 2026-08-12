# Analytic scientific benchmarks

DiffractScout ships a deterministic benchmark suite that checks the scientific
core against closed-form crystallographic and elastic results. The suite is
separate from unit tests that may reuse implementation helpers. Its fixtures,
expectations, tolerances, report, and SHA-256 manifest are exposed through one
command:

```bash
diffractscout benchmark -o outputs/analytic_benchmark
```

A successful bundle contains `benchmark_report.json`,
`benchmark_report.md`, the exact synthetic CIF files, the expectation file, and
`benchmark_manifest.json`. The command verifies the completed bundle before it
returns success.

## Crystallographic cases

| Case | Space group / lattice | Primary analytic checks |
|---|---|---|
| Simple cubic Al | primitive cubic, one atom | first families `(100)`, `(110)`, `(111)`; multiplicities 6, 12, 8; $F=f$ |
| BCC Fe | body-centred cubic | $h+k+l$ even selection rule; multiplicities; $F=2f$ |
| FCC Al | face-centred cubic | unmixed parity selection rule; multiplicities; $F=4f$ |
| NaCl | rocksalt basis | FCC selection rule; $F=4(f_{Na}-f_{Cl})$ for odd indices and $4(f_{Na}+f_{Cl})$ for even indices |

For each case the suite checks the first allowed families, explicitly forbidden
families where applicable, powder multiplicity, cubic
$d=a/\sqrt{h^2+k^2+l^2}$, and $q=2\pi/d$. X-ray atomic form factors are obtained
from Gemmi at the corresponding spacing, while the lattice sums are evaluated
independently in the benchmark code.

## Elasticity case

The suite evaluates a stable cubic stiffness matrix with an anisotropic
response along `[100]`, `[110]`, and `[111]`. Expected values are calculated
from the closed-form cubic-compliance expression and compared with the package
implementation at a relative tolerance of $10^{-12}$.

## Reproducibility

Setting `SOURCE_DATE_EPOCH` fixes generated timestamps. Under the same software
versions and platform, two benchmark runs must produce identical hashes for all
manifested files. CI performs the benchmark on Ubuntu Python 3.10--3.13,
Windows, macOS, and after clean wheel installation.

## Interpretation boundary

The benchmark establishes agreement with the declared crystallographic and
elastic equations for synthetic structures. It does not establish experimental
phase-identification accuracy, detector response, profile refinement, database
completeness, or external adoption. Those claims require the separately
versioned records defined in `docs/ADOPTION_AND_IMPACT.md`.
