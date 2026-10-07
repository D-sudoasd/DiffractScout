# Desktop UI acceptance — 7 October 2026

The main Tk workbench and Initial CIF preparation dialog now share native
styles, installed system fonts, readable field states and keyboard focus.
The analysis forms prioritize radiation, scan range and outputs; profile,
d-spacing, resource limits, Cij and candidate filters expand when needed.
Translated choices preserve the canonical calculation settings.

Completed runs open a result view with phase/peak/diagnostic counts and separate
theoretical-pattern, peak-table and diagnostic tabs. Peak tables sort numerical
values, page long tables, retain missing moduli as `—`, and locate a selected
reflection on the plot. Curves use the returned pipeline data and show the
actual wavelength. Display normalization is independent for each phase and
does not represent phase fractions. Numerical engines and export schemas were
not changed.

## Execution and visual inspection

Local acceptance used Windows, Python 3.12.10 and Tk 8.6, starting from commit
`47a4093a6309abf6239d36de6a95dfe02997829f`. Actual Tk windows ran through CLI
processes on a private Windows desktop using `CreateDesktopW` and
`CreateProcessW`; `PrintWindow` captured their rendered pixels. There was no
desktop switch, computer-use API, or input on the user's current desktop.
Test events were generated only within the private Tk process.

The English and Chinese views were inspected at 1200×820 and 900×640. At the
minimum window size, the final English pattern canvas was 824×162 pixels and
the peak table was 811×164 pixels. The Activity log retained visible lines
after resizing. Inspection corrected overlapping axis labels, clipped sorting
arrows and unavailable diagnostic-detail space. Diagnostic messages appear
before source details, and both diagnostics and CIF notes retain full text with
independent scrolling.

| Actual workflow | Result |
| --- | --- |
| Analyze packaged synthetic FCC Al, BCC Fe and NaCl CIFs through the Run button | 3 analyses, 29 indexed peaks; bundle integrity verified |
| Inspect the workbook | Overview, recommended peaks, canonical data and per-phase sheets present |
| Select a peak, click native table headings and locate it in the plot | Selection, numerical descending sort and plot navigation passed |
| Run the Materials Project form with an offline provider fixture | 1 analysis; bundle integrity verified |
| Retry into an unrelated nonempty folder | Failure reported; unrelated sentinel and previous valid result retained |
| Analyze one valid and one malformed CIF | Successful phase retained; complete error diagnostic accessible |
| Prepare offline TC4 starting CIFs and load them into the main form | 3 checked starting CIFs; bundle integrity and loading verified |
| Recheck source files after all runs | All three SHA-256 values unchanged |

These are engineering checks with synthetic and offline inputs. No live
Materials Project query or experimental phase-identification acceptance was
performed. The generated CIFs remain starting models with recorded assumptions.
The [machine-readable results](desktop-ui-20261007.json) retain fixture hashes,
workflow outcomes and measured viewport dimensions. The temporary capture
harness and generated bundles remain in the ignored
`outputs/ui-review-20261007/` directory: automatic command approval rejected
its deletion with `blocked by policy`. All seven retained screenshots were
checked against their source SHA-256 values before attempting cleanup.

## Regression checks

The combined local check covered 96 cases in `test_gui.py`, `test_gui_cifs.py`,
`test_gui_results.py` and `test_gui_settings.py`. It reported 94 passes and two
issues during final layout refinement: a resize assertion needed Tk's pending
geometry to settle, and the compact diagnostic layout needed space for its
details scrollbar. Both were corrected. The affected final checks then passed
(10 cases), followed by seven passing result-view checks after putting the
diagnostic message before its source details. No local failure remains.

The retained tests cover first-result language selection, canonical settings,
readiness and task states, CIF identity and deletion, collapsed settings,
focus scrolling, remembered panel sizes, narrow-window layouts, full messages,
missing values, numerical sorting, pagination and preservation of narrow peaks
in the display envelope. The Xvfb CI interaction step now runs all three GUI
test modules. Numerical workflows retain their existing CI checks.

Modified Python files passed Ruff. Repository documentation and metadata passed
`scripts/check_docs.py`, and the final diff passed whitespace checks.

## Reference views

- [Local CIF analysis](../assets/gui-local.png)
- [Materials Project form](../assets/gui-materials-project.png)
- [Theoretical pattern](../assets/gui-results.png)
- [Pattern at 900×640](../assets/gui-results-compact.png)
- [Peak table at 900×640](../assets/gui-peaks-compact.png)
- [Diagnostics at 900×640](../assets/gui-diagnostics-compact.png)
- [Prepared starting CIFs](../assets/gui-initial-cifs.png)
