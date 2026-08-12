# Analytic reference suite v1

**Status:** executable, synthetic, deterministic

**Entry point:**

```bash
diffractscout benchmark -o outputs/analytic_reference_v1
```

**Source fixtures:** `src/diffractscout/benchmark_data/`

**Acceptance rule:** every reported check passes and the completed benchmark
bundle passes its SHA-256 manifest verification.

The suite covers simple-cubic, BCC, FCC, NaCl, and cubic directional-elasticity
solutions. The equations and tolerances are documented in
`docs/ANALYTIC_BENCHMARKS.md`. This case supports claims about agreement with
declared analytic contracts. It does not count as external validation or a
real research-use case in the JOSS evidence ledger.
