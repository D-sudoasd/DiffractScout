# Command-line workflows

The command-line interface uses the same calculation and bundle-verification
code as the Python API and desktop application. Run `diffractscout --help` for
the command list or add `--help` to a command for its options.

## Start with a complete offline run

```bash
diffractscout demo -o outputs/demo
diffractscout inspect outputs/demo
```

`inspect` verifies the bundle before reporting its calculation settings,
phase and reflection counts, diagnostics, and result files. It reads an
existing result; it does not repeat the calculation or modify any files.
If integrity verification fails, it reports the failure rather than presenting
the contents as a valid calculation result.

For a machine-readable inspection report:

```bash
diffractscout inspect outputs/demo --json
```

Use `verify` when only the manifest and file-integrity result are needed.
Inspection can check that a saved bundle is unchanged; it does not establish
agreement with experimental data.

## Reuse calculation parameters

Create a parameter preset without starting an analysis:

```bash
diffractscout preset save -o presets/energy-30.json --energy-keV 30 --two-theta-max 60
diffractscout preset show presets/energy-30.json
diffractscout analyze path/to/cifs -o outputs/energy-30 --preset presets/energy-30.json
```

Presets use the same versioned format as desktop **Save parameters** and
**Load parameters**. They store analysis settings and export switches, including
radiation, angular and d-spacing ranges, profile parameters, resource limits,
Excel, elasticity, laboratory views, patterns, figures, and recursive scanning.
Recursive scanning applies to local inputs in `analyze` and `quick-export`;
the database-backed `run` command does not use this preset field.
API keys, input/output paths, overwrite authorization, manual elastic tensors,
and the CLI-only `--figure-preset` style name are excluded.

The complete preset is validated before use. Values are resolved in this order:
command defaults, preset values, then explicitly supplied command-line options.
An explicit value overrides a preset even when it equals the command default.

```bash
diffractscout analyze path/to/cifs -o outputs/energy-83 --preset presets/energy-30.json --energy-keV 83
diffractscout preset save -o presets/energy-83.json --preset presets/energy-30.json --energy-keV 83
```

An explicit energy, wavelength, or built-in source selects the corresponding
radiation mode. An energy in keV is never reinterpreted as a wavelength in
Angstrom. Use `--wavelength-A` to supply a custom wavelength.

Both directions of an output switch are available, such as `--excel` and
`--no-excel`, so a disabled preset option can be enabled for one run. Use
`--clear-d-min` or `--clear-d-max` to remove a saved spacing bound. Existing
preset files are preserved unless `preset save --overwrite` is explicit.
Save presets outside result bundles; writing inside a bundle is refused to
preserve its manifest and recorded files, including when `--overwrite` is used.

```bash
diffractscout preset show presets/energy-30.json --json
diffractscout analyze path/to/cifs -o outputs/no-d-filter --preset presets/energy-30.json --clear-d-min --clear-d-max --no-patterns
```

## Export directly to Excel

```bash
diffractscout quick-export path/to/sample.cif -o outputs/sample.xlsx --preset presets/energy-30.json
diffractscout inspect outputs/sample_bundle
```

The standalone `diffractscout-quick-export` entry point supports the same preset
workflow. A direct `.xlsx` output creates a separate editable workbook and a
complete result bundle. An `.xlsx` target requires Excel output; choose a
directory target with `--no-excel` for a CSV-only bundle.

See the [Excel guide](EXCEL.md) for workbook navigation, intensity formatting,
and keeping editable copies separate from the verified bundle.

## Use results in batch scripts

Analysis and quick-export commands preserve their `--json` result structure.
Their text summaries show output locations, phase and reflection counts, and
warnings and errors with their recorded severity. The new `inspect --json`
report is a separate interface for already completed bundles.

| Exit status | Analysis and quick-export meaning |
|---|---|
| `0` | At least one phase succeeded and no error diagnostic was emitted. |
| `2` | Invalid arguments, failed operation, or no successful phase analysis. |
| `3` | A usable partial result was produced with one or more failed items. |

Warnings alone do not turn a successful analysis into a failed command. Check
both the exit status and diagnostics when deciding whether a partial result
should enter the next stage of a batch workflow.

Database discovery additionally needs the optional Materials Project
dependencies and credentials. Prefer `MP_API_KEY` over placing a credential in
a shell command. The [API guide](API.md) and [scientific contracts](SCIENTIFIC_CONTRACTS.md)
describe the calculation fields and tensor-coordinate requirements.
