---
name: diffractscout-agent-pipeline
description: Execute DiffractScout scientific jobs through its durable CLI, Python or local MCP interface, including planning, candidate discovery, CIF preparation, theoretical diffraction, recovery and verified exports. Use for research execution requests, not general repository coding or experimental-pattern fitting.
---

# DiffractScout scientific jobs

Use the shared workflow service to turn the user's scientific request into a
recorded calculation with verified exports. Read the repository's
[agent pipeline guide](../../../docs/AGENT_PIPELINE.md) for execution and
recovery, and [scientific contracts](../../../docs/SCIENTIFIC_CONTRACTS.md)
when interpreting numerical fields. Concrete requests are in
[examples/agent](../../../examples/agent/README.md).

Obtain `diffractscout agent context` and `diffractscout agent schema request`
(or their MCP/Python equivalents) for current capabilities and fields. Choose
the existing workflow for the requested outcome; use `prepare_analyze` when
starting CIF preparation and subsequent theoretical analysis are both requested.
Do not build another numerical implementation or add a language model to the
calculation path.

Preserve the requested composition, local source identity, radiation and scan
range. Check available inputs before asking for missing information. Synchrotron
peak positions require an explicit wavelength or energy; ask for it if unavailable.
Nominal chemistry and prototype cell parameters are starting assumptions. Cited
lattice/coordinate edits must come from supplied evidence. Do not infer phase
fractions, invent elastic constants or claim experimental phase identification.

Normalize relative paths from the request file, select a workspace that remains
stable across sessions, and omit `output_dir` for a unique service-managed output
or select a fresh target outside the input tree.
Plan the request and resolve actionable diagnostics before execution. Keep
Materials Project credentials in the runtime environment (`MP_API_KEY`) or
runtime API argument, never in the request or outputs. Respect the user's
database scope and download authorization; do not widen limits to clear a failure.

Use `submit` for work that may outlive the current tool call. Record the returned
`run_id` and workspace, poll `status`, and consume new event pages using
`next_cursor`. A successful submission is not completion. Before resubmitting
after a lost response, inspect existing jobs. Resume an interrupted or blocked
job only after addressing its diagnostic; preserve checkpoint and source checks.
Cancellation is cooperative and retains completed evidence. Batch independent
requests serially unless finite concurrency is explicitly appropriate.

After a completed or partial run, obtain `result` with integrity verification.
Request table pages only as needed. Report artifact paths, radiation/range,
source/prototype assumptions, diagnostics and missing values with the result.
If verification fails or work remains blocked, identify the affected stage and
required input; do not present an unverified bundle or partial task as complete.
