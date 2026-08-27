# Examples

`demo_cifs/` contains explicitly synthetic validation fixtures. They are not
experimental measurements and must not be cited as material-property data or
used as evidence of real-material phase identification, elastic behavior, or
instrument agreement.

After installing the checkout (`python -m pip install -e .`), run the example
analysis and verify the resulting bundle:

```bash
diffractscout analyze examples/demo_cifs -o outputs/examples-analyze
diffractscout verify outputs/examples-analyze
```

The successful run reports `Analyzed phases: 1`, and the verifier reports
`PASS`. Inspect `phase_summary.csv`, `peak_reference.csv`, `provenance.json`,
`diagnostics.csv`, and `manifest.json` before using any output. The bundle is a
synthetic/offline software example; scientific acceptance still requires
independent real-material validation. Use a new output directory on reruns, or
use `--overwrite` only for an existing bundle that first passes
`diffractscout verify`.
