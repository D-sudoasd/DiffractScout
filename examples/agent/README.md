# Offline workflow requests

Install the checkout with `python -m pip install -e .`. Run these commands from
the repository root; `python -m diffractscout` can replace `diffractscout`.
No Materials Project credentials or MCP installation are needed.

```bash
diffractscout agent plan examples/agent/analyze-local.json
diffractscout agent run examples/agent/analyze-local.json
diffractscout agent run examples/agent/analyze-synchrotron.json
diffractscout agent run examples/agent/prepare-analyze-tc4.json
diffractscout agent run examples/agent/batch-offline.json
diffractscout agent list
```

The examples omit `output_dir` so the service chooses a distinct output for each
run within the workspace. Relative input paths resolve from the JSON file's
directory. If moving a JSON file, adjust its relative input paths too. For a
specific destination, add a fresh `output_dir`; relative output paths also
resolve from the request file. Do not delete prior output or enable overwrite
to make an example pass. A workspace can be selected with
`agent --workspace /absolute/path/to/workspace ...`.

| File | Purpose |
| --- | --- |
| [analyze-local.json](analyze-local.json) | Synthetic FCC Al, Cu Kα, 5–100°, synthetic paired stiffness tensor, full Excel |
| [analyze-synchrotron.json](analyze-synchrotron.json) | Same synthetic CIF, explicit 83 keV, 0.5–15°, peak-table workbook |
| [prepare-analyze-tc4.json](prepare-analyze-tc4.json) | Offline alpha, beta and alpha-double-prime starting models, then theoretical diffraction |
| [batch-offline.json](batch-offline.json) | Two independent requests, serial execution and CSV output |

The FCC fixture and its tensor are synthetic software examples. TC4 uses nominal
grade chemistry with packaged prototype lattice and internal coordinates; these
are starting assumptions, not measured TC4 phase parameters or an equilibrium
phase prediction. Read the preparation report and provenance before scientific
use. The serial batch manifest is accepted by `run` and `submit`; use `plan` on
each individual request when checking a batch before execution.

For background submission, replace `run` with `submit`, retain each returned
`run_id`, then use `status`, `events`, and `result` as described in the
[agent pipeline guide](../../docs/AGENT_PIPELINE.md). A saved request is an
execution description; completion and integrity must be read from the job and
its verified result.
