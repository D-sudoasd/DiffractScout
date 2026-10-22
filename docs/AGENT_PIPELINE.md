# External-agent scientific workflows

DiffractScout exposes its existing scientific workflows through one durable
job service, shared by the Python API, JSON CLI, optional local MCP server and
desktop Tasks page. An external agent supplies scientific intent and parameters;
DiffractScout performs the calculations and records their provenance. There is
no internal language model or experimental-pattern fitting in this interface.

## Choose the workflow

| `workflow` | Input and outcome |
| --- | --- |
| `analyze` | Local CIF files/folders → structure checks, theoretical diffraction, optional compatible elasticity, exports |
| `discover` | Composition/system/record IDs → candidate catalogue without structure downloads |
| `run` | Database discovery → downloads → analysis and exports |
| `prepare` | Grade or explicit chemistry, optional templates/cited parameters → checked starting CIFs and preparation report |
| `prepare_analyze` | Preparation → analysis of the prepared CIFs and exports |
| `fetch` | Chemical system and phase selection/templates → symmetry prototypes |
| `adapt` | One source CIF and explicit chemistry/cited cell or coordinates → a new CIF with provenance |

Discovery is a database candidate search, not identification of phases in a
sample. Preparation can retain prototype parameters and nominal chemistry;
it does not predict phase fractions, phase partitioning or phase equilibrium.
Read [scientific contracts](SCIENTIFIC_CONTRACTS.md) and the
[initial CIF guide](INITIAL_CIFS.md) when interpreting these results.

## Discover, plan, execute, inspect

Install the current checkout with `python -m pip install -e .`. Use one explicit
workspace for a continuing task, especially when the caller can change its
working directory. The default is `outputs/agent-workspace` relative to the
process working directory. The examples below run from the repository root.

```bash
diffractscout agent context
diffractscout agent schema request
diffractscout agent plan examples/agent/analyze-local.json
diffractscout agent run examples/agent/analyze-local.json
```

`context` reports workflows, optional dependency availability and whether runtime
credentials are configured. `schema request` is the authoritative field/default
reference for `diffractscout_workflow_v1`; obtain it rather than copying a schema
from prose. Unknown fields and credentials in a request are rejected.
`plan` checks local inputs, settings, dependencies and required information without
network access or output writes. Inspect its `ready` and `diagnostics` fields:
a successful CLI invocation alone does not establish readiness. Planning cannot
guarantee later database availability or scientific suitability of a candidate.

For long jobs, submit and retain the returned identity. In subsequent commands,
replace `RUN_ID` with the returned `run_id` and keep the same workspace.

```bash
diffractscout agent --workspace outputs/agent-workspace submit examples/agent/prepare-analyze-tc4.json
diffractscout agent --workspace outputs/agent-workspace status RUN_ID
diffractscout agent --workspace outputs/agent-workspace events RUN_ID --after 0 --limit 50
diffractscout agent --workspace outputs/agent-workspace result RUN_ID
```

`submit` returns after starting the background worker. The client may disconnect;
the durable record remains available to a later CLI, MCP or desktop session.
Poll `status` at an interval appropriate to the task, then read new event pages
using the returned `next_cursor` as the next `--after` value. `has_more` indicates
that more events are available now. Do not resubmit the same calculation merely
because the client lost a response; inspect `list` and existing job records first.

`run` waits in the foreground and is useful for short/offline work. JSON stdout
contains one result or error object; diagnostics go to stderr. CLI exit codes
are `0` for a successful operation, `3` for partial work, and `2` for errors or
failed, blocked, interrupted or cancelled work. Always inspect the returned state
and diagnostics as well as the exit code. `pending`/`running` are not completion.

## Requests and paths

See [runnable offline examples](../examples/agent/README.md) for local analysis,
explicit synchrotron radiation, TC4 preparation plus analysis and serial batches.
Request sections select `analysis`, `discovery`, `preparation`, `adaptation`,
`exports`, and `execution` options as applicable. `analysis` and `discovery`
reuse the ordinary scientific settings. The supported workbook templates are
`full` and `peak_table`; CSV exports remain available with Excel disabled.

For CLI JSON files and desktop imports, paths are relative to the request file,
including CIF inputs, preparation templates, phase-parameter files and output
targets. Inline JSON, stdin, MCP and ordinary Python mappings use the calling
process directory unless paths have already been normalized. Python callers can
use `WorkflowRequest.from_dict(payload, base_dir=...)` to set the base explicitly.
Workspace selection is independent of the request file's base directory.

Omit `output_dir` for a unique service-managed output in the workspace, or supply
a fresh output target outside the input tree. `execution.overwrite` does
not grant permission to delete arbitrary directories or bypass bundle checks.
Mutable job records and checkpoints belong outside committed result bundles;
editing a file in a verified bundle invalidates its integrity record.

Specify radiation and range for the scientific question. Synchrotron requests
require an explicit `energy_keV` or `wavelength_A`; a missing value must not be
replaced by the laboratory default. Units are 2θ in degrees, wavelength and d
in Å, q = 2π/d and g = 1/d in Å⁻¹, and stiffness in GPa.
Cell or fractional-coordinate adaptations require a citation supplied by the
caller. Missing elastic data remain missing, and directional moduli require a
compatible tensor coordinate frame.

## Recovery and cancellation

```bash
diffractscout agent list
diffractscout agent status RUN_ID
diffractscout agent resume RUN_ID
diffractscout agent resume RUN_ID --foreground
diffractscout agent cancel RUN_ID
```

The service persists state JSON and event JSONL, source snapshots, and checkpoints
for completed discovery queries, downloads and phase analyses. Resume verifies
saved source snapshots and checkpoint hashes before reuse. Completed work can be
reused after interruption; an in-flight operation may need to run again. Changed
artifacts must be resolved from the reported diagnostic, not by removing locks
or modifying the saved request/checkpoint files. A submitted job uses its frozen
sources; edits to an original input require a new task to analyze the new data.

Status distinguishes `completed`, `partial`, `failed`, `blocked`, `interrupted`
and `cancelled`. A partial result needs its per-item diagnostics inspected before
use. A blocked job needs its stated missing dependency, credentials, parameter or
authorization resolved before resuming. Runtime credentials must be supplied
again if the worker process/environment no longer has them. Cancellation is
cooperative: it takes effect at a safe operation boundary and preserves completed
evidence. Restarting the desktop does not erase task history; OS termination
may interrupt the worker and requires a later explicit resume.

## Read verified results

`result` verifies the published artifact set by default and reports artifact
paths and available tables. Use a table name returned by that response to request
a page rather than loading all rows into an agent conversation:

```bash
diffractscout agent result RUN_ID
diffractscout agent result RUN_ID --table TABLE_NAME --offset 0 --limit 50
```

Verification failures must be reported as failures; `--no-verify` is a diagnostic
option and does not establish that modified output is valid. File integrity
demonstrates preservation of the recorded computation, not agreement with an
experiment. Report the radiation, range, source identity, warnings, missing
values and relevant prototype assumptions alongside scientific tables.

## Batches and database access

The `diffractscout_batch_v1` manifest contains `requests` and `max_workers`.
`run` or `submit` accepts this wrapper; plan individual requests before execution.
Execution is serial by default. Increase concurrency explicitly and finitely
only for independent requests with separate output targets; batch children have
their own task identities and status records. See the
[offline batch example](../examples/agent/batch-offline.json).

Database workflows need `.[mp]` and runtime `MP_API_KEY`. Do not place the key in
requests, saved configuration, task names, examples or result metadata. Optional
Python `api_key` arguments and desktop key entry are runtime-only inputs. Keep
subsystem/candidate limits within the intended search and inspect query estimates
before execution. Large downloads require `execution.authorize_large_download`
when exceeding `execution.confirm_above`; repeated network attempts are bounded
by `execution.max_attempts`. A provider failure is a diagnostic, not an empty
candidate list.

## Python and local MCP

The [API guide](API.md#durable-workflow-service) shows Python calls. The optional
MCP adapter uses the same service and requires a separate extra:

```bash
python -m pip install -e ".[mcp]"
python -m diffractscout.mcp_server
```

Configure a local MCP client to launch the interpreter with module arguments,
for example:

```json
{
  "mcpServers": {
    "diffractscout": {
      "command": "python",
      "args": ["-m", "diffractscout.mcp_server"]
    }
  }
}
```

Use the interpreter containing the installed package. Provide `MP_API_KEY` through
the server's runtime environment only for database work. MCP transport is stdio;
the process is not an HTTP service. Tools are `context`, `schema`, `plan`, `run`,
`submit`, `list_jobs`, `status`, `events`, `result`, `resume`, and `cancel`.
Read calls return bounded pages where applicable. A long `run` remains a blocking
tool call; `submit` followed by `status`/`events` is the durable interaction.

In the desktop, open **Tasks / 任务** and choose the same workspace to inspect
these jobs. See [desktop task history](GUI.md#task-history-and-recovery).
The project skill
[$diffractscout-agent-pipeline](../.agents/skills/diffractscout-agent-pipeline/SKILL.md)
guides an external agent through this scientific execution workflow.

Implementation checks, recovery operation counts and installation evidence are
recorded in the [2026-10-22 acceptance report](evidence/agent-pipeline-20261022.md).
