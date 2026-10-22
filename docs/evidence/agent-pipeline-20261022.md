# Agent pipeline acceptance — 2026-10-22

Local acceptance on Windows 11, Python 3.13.0. This record concerns software
execution, scientific-contract preservation and recovery. It does not establish
experimental phase identification or quantitative phase analysis.

## Delivered behavior

- Shared versioned request/planning service for Python, JSON CLI, optional local
  MCP and the desktop Tasks page.
- Frozen source snapshots; SHA-256-verified per-query, per-material and per-phase
  checkpoints; independent final export, verification and atomic publication.
- Foreground/background runs, bounded batches, idempotent submission identifiers,
  cancellation, interrupted-run recovery and verified paginated result access.
- Local CIFs, database discovery/analysis, initial CIF preparation plus analysis,
  explicit prototype retrieval and explicit CIF adaptation.
- Per-field parameter origins, runtime-only credentials, original input preservation,
  result coverage, scientific warnings and portable replay requests.

The numerical definitions and ordinary CLI result contracts are retained.
New workflow metadata is added only by the new execution service.

## Verification

| Check | Observed result |
| --- | --- |
| Offline suite, excluding main GUI and Tasks GUI modules | 851 passed, 6 skipped, 168.24 s |
| Final affected core/delivery/CLI regressions after background-process corrections | 70 passed, 32.06 s |
| Analytic scientific benchmark | 45/45 checks passed |
| Six-module GUI suite | 115 passed |
| Final Tasks GUI checks | 8 passed; one Tk initialization skip passed in a fresh isolated invocation |
| Optional MCP protocol pytest | 2 passed, including an actual stdio subprocess |
| Clean installed-wheel CLI checks | 9 commands passed, outside the checkout and without PYTHONPATH |
| Clean installed-wheel MCP checks | 18 official SDK 2.3.0 calls passed, including background completion and pagination |
| Installed dependency consistency | pip check passed |
| Wheel/source comparison | All 87 packaged Python files byte-match the accepted source |
| Ruff, documentation checker, whitespace checks | Passed |

The offline-suite skips comprise five unavailable inherited external CIF fixtures
and the optional MCP module in the base interpreter; MCP was checked separately.
One repeated-root Tk initialization transiently reported a missing Tcl script;
the skipped import/relative-path test passed alone. The actual local-job test
closed the GUI during work, observed independent completion, reopened history and
loaded the verified result. Offline preparation and 900×640 Chinese/English
interaction checks also passed. The accompanying screenshots illustrate synthetic
task history, not experimental results.

Full offline command (source checkout):

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
py -3 -m pytest -q --ignore=tests/test_gui.py --ignore=tests/test_gui_tasks.py
```

Focused final command:

```powershell
py -3 -m pytest -q tests/test_workflow.py tests/test_workflow_delivery.py tests/test_agent_cli.py
```

The independent review found two concrete recovery/delivery defects: a valid
published bundle could become blocked if its task acknowledgement failed, and
discovery replay requests were incorrectly converted to analysis requests.
Both have regression coverage. Additional regressions cover retained Windows
process handles, duplicate batch submissions, relative tensor identities and
portable replay of manually supplied elastic tensors.

## Measured recovery work

The reproducible [measurement script](../../scripts/measure_workflow_reuse.py)
uses two synthetic CIFs and injects one export failure after both calculations.
The [recorded measurement](agent-reuse-20261022.json) contains the complete counts
and timings. Both final bundles passed integrity verification.

| Work during retry | Ordinary pipeline restart | Workflow resume |
| --- | ---: | ---: |
| Provider queries | 1 | 0 |
| Material downloads | 2 | 0 |
| Phase calculations | 2 | 0 |
| Wall time in this small local fixture | 0.264 s | 0.298 s |

The evidence demonstrates elimination of repeated acquisition/calculation after
the injected failure. It does not demonstrate a wall-time speedup; persistent
checks and export overhead dominate this small fixture.

## Installation artifact and limits

Accepted wheel:
`outputs/agent-wheel-20261022-accepted/diffractscout-0.4.0-py3-none-any.whl`

SHA-256:
`27503be08b499a74ca6dd7279941d6c2049ecd0006e637e8a87e11390f8be7bb`

The isolated installation initially had no MCP, mp-api or pymatgen and completed
base analysis/background flows. Optional MCP installation was then verified
separately. Detailed installed-CLI/MCP/source-comparison JSON evidence is stored
beside the wheel. Live Materials Project access was not exercised; provider
failure, empty-query, retry and resume semantics use deterministic offline
providers. Hosted CI has not run. The optional MCP CI matrix now covers
Windows/Ubuntu and Python 3.10/3.13 when CI executes.

No new portable Windows executable or formal release was produced. Frozen-worker
dispatch has a targeted regression and follows the documented
[PyInstaller subprocess lifetime behavior](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#using-sys-executable-to-spawn-subprocesses-that-outlive-the-application-process-implementing-application-restart).
The source desktop and installed Python package were exercised directly.
