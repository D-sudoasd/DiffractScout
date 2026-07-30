# Graphical interface guide

DiffractScout provides a Tk desktop interface for researchers who prefer to configure and inspect a run without composing command-line arguments. The interface delegates all scientific work to the same tested pipeline functions used by the CLI and Python API.

## Launch

```bash
diffractscout-gui
# equivalent
diffractscout gui
```

A normal Python installation with Tk support is required. On Linux, the operating-system package is commonly named `python3-tk` or `tk`.

## Local CIF analysis

![Local CIF analysis interface](assets/gui-local.png)

1. Select one or more individual CIF files and/or folders.
2. Choose whether selected folders should be scanned recursively.
3. Select the result directory.
4. Define radiation and profile settings.
5. Set the profile-grid and reciprocal-candidate safety limits.
6. Choose whether compatible numerical elastic sidecars should be paired.
7. Run the analysis and inspect the Activity log.

Duplicate input paths are removed. Only readable files with the `.cif` extension enter the calculation. Selecting `Replace an existing verified DiffractScout bundle` authorizes replacement only when the existing directory contains a supported manifest and currently passes the bundle-integrity check.

## Materials Project pipeline

![Materials Project pipeline interface](assets/gui-materials-project.png)

The query can be an alloy grade, chemical formula, chemical system, or explicit Materials Project identifiers. The form exposes:

- discovery mode;
- maximum energy above hull;
- maximum subsystem order;
- maximum records per subsystem;
- maximum total candidates;
- deprecated-record inclusion;
- conventional-standard or primitive cell selection;
- optional frame-compatible elastic-tensor evaluation;
- the same radiation, profile, resource, Excel, and overwrite controls as the local workflow.

The API key remains in process memory. DiffractScout does not save it in configuration, result, log, or repository files. Users should still remove keys before sharing screenshots, terminal history, or diagnostic material.

## Radiation controls

| Mode | Required control | Interpretation |
|---|---|---|
| `source` | Built-in source preset | Uses the documented effective wavelength for Cu, Co, Fe, Mo, or Ag Kα |
| `source` + `Custom` | Radiation value | Interpreted as wavelength in Å |
| `wavelength` | Radiation value | Explicit wavelength in Å |
| `energy` | Radiation value | Explicit photon energy in keV |

Energy and wavelength inputs must be finite and positive. The CLI also makes explicit energy and wavelength options mutually exclusive.

## Scientific controls

- `2θ min` and `2θ max` define the reflection and profile window.
- `Step` controls only the continuous display-profile grid.
- `FWHM` and pseudo-Voigt `η` define the display broadening.
- `Profile points` rejects a requested grid above the configured count before allocation.
- `Reciprocal candidates` rejects a conservative Miller-candidate estimate, and then the actual candidate list, above the configured limit.
- Elasticity pairing calculates a directional modulus only for a valid 6×6 stiffness tensor with an explicitly compatible coordinate frame.

The discrete indexed reflection table remains the primary scientific result. Profile parameters do not represent an inferred instrument function.

## Activity log and completion states

The Activity panel reports timestamps and separates informational, warning, and error diagnostics. A completed bundle can contain diagnostic errors for individual phases that failed while other phases succeeded. Completion messages therefore distinguish:

- successful completion without error diagnostics;
- completion with one or more error diagnostics;
- completion with no analyzable phases, where a diagnostic-only bundle is still available.

The `Open result folder` action is enabled after a result bundle has been written. `Copy` places the current Activity log on the clipboard; `Clear` affects only the displayed log.

## Threading and window closure

One pipeline task can run at a time. Run buttons are disabled while a worker thread is active, preventing duplicate downloads or simultaneous writes to the same target. Closing the window during a task requires confirmation. The scientific output transaction remains responsible for preserving an existing valid bundle when a run fails.

## Headless smoke test

CI starts and destroys the application under Xvfb on Linux:

```bash
xvfb-run -a python -c \
  "from diffractscout.gui import create_app; app=create_app(); app.update(); app.destroy()"
```

This check validates import, widget construction, layout initialization, and clean shutdown. Numerical workflows are tested separately through the headless API and CLI.
