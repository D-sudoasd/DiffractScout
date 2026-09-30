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

## Prepare usable initial CIFs

```bash
diffractscout prepare-cifs TC4 -o outputs/TC4_initial --offline
diffractscout verify outputs/TC4_initial
diffractscout prepare-cifs Ti-Nb -o outputs/TiNb_initial --at Ti=80,Nb=20 --offline
```

Load `initial/*.cif` and read `report.md` for inherited lattice parameters,
composition assumptions and refinement suggestions. This preparation command
recognizes nominal Ti-6Al-4V aliases, selects the host by the largest atomic
fraction, checks actual parent-lattice atom orbits, restores chemically verified
P1 symmetry, and preserves source files. All three Ti families have attributed
offline scaffolds; their lattice/internal coordinates are not target-alloy
measurements. Add `--parameters phase-parameters.json` for cited per-phase
values, `--template phase=path.cif` for overrides, `--host` for explicit host,
or `--json` for machine-readable artifact paths. `--max-prototype-attempts`
controls the per-phase download/validation budget (default 8); remaining untried
candidates are reported. Online mode uses `MP_API_KEY`;
`--offline` never contacts a provider. Exit codes are 0 complete, 3 partial,
2 no usable CIF or invalid input. The output directory must be new.
See [the parameter template](../examples/phase_parameters.template.json) and
[the initial CIF guide](INITIAL_CIFS.md) for the exact scientific contract.

## Fetch a symmetry prototype, then adapt it

`discover` and `run` enumerate chemical subsystems. For an alloy grade they can
download intermetallics as well as the elemental prototypes. They do not edit
occupancy or lattice parameters, and they do not read papers.

Use this sequence when the goal is one alpha, beta, or alpha-double-prime CIF
for a stated composition.

1. Run `fetch-prototypes` first. A row whose status is `scaffold` or `template`,
   and any row whose `target_composition` is `false`, still has the source
   occupancy and lattice. The COD 1523304 scaffold is Ti–20 at% Nb, Cmcm. Its
   Nb occupancy and cell are the Brown, Clark, Eastabrook, and Jepson (1964)
   entry, not the alloy being requested.
2. Look up a measurement for the user's composition and phase. Prefer the same
   alloy, the same phase, room temperature, and a stated heat treatment. Record
   the citation, the specimen condition, and the reported uncertainty.
3. If that paper does not report a lattice for the phase, stop and say which
   value is missing. An analogue alloy can be used only when the citation and
   the output filename both say that it is a comparison.
4. Leave every coordinate the paper does not report at the prototype value.
   Change alpha-double-prime `y` only when the paper reports it or the user
   passes `--fract y=...`.
5. Keep the nominal alloy composition separate from equilibrium phase chemistry.
   Martensite can inherit the parent composition. Equilibrium alpha and beta in
   Ti-6Al-4V are commonly partitioned and are not bulk 6 wt% Al–4 wt% V.
6. Run `adapt`. Report the loader's space-group cross-check. A result other
   than `match` means the file was not written.

```bash
diffractscout fetch-prototypes "Ti-6Al-4V" -o prototypes \
  --phase alpha --phase beta --phase alpha-double-prime
diffractscout adapt prototypes/alpha.cif -o TC4_alpha.cif \
  --nominal tc4 --a 2.935 --b 2.935 --c 4.673 \
  --citation "Author, Journal, volume, pages, year, DOI"
```

`--nominal tc4`, `ti64`, and `ti-6al-4v` mean the conventional grade: 6 wt% Al,
4 wt% V, balance Ti. That switch exists on `adapt` and `prepare-cifs`. In `discover` and `run` those aliases
still expand to the element set Ti, Al, V. Other alloys need `--wt` or `--at`.
The percentages must sum to 100 within 0.05. Occupancies are rounded to five
decimal places and the residual is added to the last element.

Independent axes, angles, and fractional coordinates change only when supplied.
Hexagonal/tetragonal a and b, and cubic a, b and c, are linked by symmetry.
Specify one of the equal axes; conflicting explicit values are rejected. `--citation` is
required for every lattice or coordinate edit. Composition-only edits do not
need one. The command writes `name.adapt.json` beside the new CIF and refuses
to overwrite the source, the destination, or the sidecar.

`fetch-prototypes` queries every chemical subsystem and applies no
energy-above-hull cutoff, because beta-Ti is well above the usual near-stable
threshold. The default `--max-subsystems` is 64. The host is the first parsed
element unless overridden with `--host`, so `Ti-Al-V` and `Ti-6Al-4V` use Ti. An elemental host prototype is
preferred over a lower-energy multielement candidate. Alpha requires space
group 194 and excludes D0₁₉ and C14. Beta requires 229. Alpha-double-prime
requires 63 and a formula whose elements are inside the requested system, which
excludes oxides of an oxygen-free alloy.

Alpha and beta need a Materials Project key or `--template phase=path`.
Alpha-double-prime can be fetched with no key: the packaged scaffold is copied
and the index says so. If a key is set, the command searches first and uses the
scaffold only when no eligible Cmcm hit exists. The packaged scaffold is restricted
to host Ti; other hosts need a candidate or template. A Materials Project conventional
CIF is stored unchanged. When its declared symmetry is P1, `adapt` will refuse
it; pass a symmetry-declared file with `--template`.

`fetch-prototypes` is the low-level raw acquisition command: CIFs and the index
are individually created without overwrite, but the directory is not a
transactional bundle. Use separate output directories for concurrent fetches;
use `prepare-cifs` for a fully staged, verified atomic bundle.

| Exit status | `fetch-prototypes` | `adapt` |
|---|---|---|
| `0` | Every requested phase produced a CIF. | The new CIF and sidecar passed validation. |
| `2` | Invalid input, missing API key for alpha or beta, or another fatal error. | Invalid input, missing citation, or the symmetry check failed. No destination file is left behind. |
| `3` | The index was written and at least one requested phase is missing. | Not used. |
