# Adoption and research-impact evidence

Assessment date: **26 September 2026**. The JOSS manuscript may make only
claims supported by traceable records. The machine-readable index is
`docs/evidence/impact_evidence.json`; this document defines what each record
can support and distinguishes established evidence from author-reported leads.

## Current evidence status

The submitting author reports that DiffractScout has been used in multiple
published papers. This report indicates actual research use and must not be
rewritten as “no research use.” The specific papers, DOI/URLs, software
version or commit, feature used, and research outcomes have not yet been
mapped into the evidence ledger. Until representative sources are identified
and checked, the manuscript should not claim a publication count or describe
the contribution of those papers.

The public repository contains a 45-check analytic benchmark and a synthetic
FCC demonstration. These materials support reproducibility of selected
calculation, software, and provenance contracts. They do not show experimental
accuracy, external adoption, productivity gains, or research impact by
themselves. A comparison with another implementation can support a numerical
validation claim when the method and acceptance criteria were fixed in
advance; it does not establish use by another research group or agreement with
experiment.

## Evidence categories

### Research use

For a published use, record the paper's DOI or stable URL, exact software
version/commit, operation used, and the result or research decision that the
software informed. Cite the publication in the JOSS manuscript. If the
workflow is not yet public, describe it only to the extent the author can
document it and JOSS editors can inspect it; do not disclose restricted data.

For the project's stricter public case record, include the scientific
question, lawful input source, frozen input hashes, full settings, result
bundle and manifest hashes, research decision, and limitations. A versioned
report belongs under `validation_cases/`. A general statement that someone
ran the software is not enough to substantiate a specific scientific claim.

### Independent numerical comparison

An independent comparison should use an analytic result, accepted standard,
or separately implemented reference. State the acceptance criteria before
examining the DiffractScout result. Preserve implementation and version,
conventions, units, frozen input/result hashes, absolute and relative
differences, and unresolved discrepancies. For diffraction, state radiation
and scan range. For elasticity, identify tensor source and coordinate frame,
Voigt convention, transformations, and tested directions.

These two public comparison reports are required by the local readiness
script. They are useful internal scientific controls; current JOSS criteria do
not list independent diffraction and elasticity reports as stand-alone
reviewer-checklist gates.

### External engagement

Useful evidence includes a public issue or discussion from a user, an external
installation or review report, a contribution, or a documented workflow with
another group. Record the artifact and version tested, commands, verification
result, concrete outcome, and limitations. Attribute a person only with
consent. Stars, views, download counts, self-authored roadmap issues, and
scheduled CI runs measure other things and do not demonstrate external
research impact.

### Public development and releases

The ledger records meaningful public commits, issues, pull requests, and
releases with their dates and outcomes. The public repository date is
12 August 2026. Do not count commits predating that date, private changes,
unmerged branches, or automatic CI. A tagged software release is not an
immutable archive DOI. After successful review, tag and archive the reviewed
source and record its DOI for the publication stage.

## Claim ledger

| Potential manuscript claim | Evidence now available | Status |
|---|---|---|
| The software has been used in published research | Submitting-author report, 26 September 2026; representative papers and exact use not yet indexed | **Reported; citation-level audit pending.** Do not state a paper count until verified. |
| The package reproduces defined analytic diffraction and elasticity cases | 45-check analytic suite and synthetic offline FCC workflow | Supportable only as reproducible software/analytic verification; not an experimental-accuracy or impact claim. |
| A real multiphase workflow informed a specific research decision | No hashed, versioned case report is indexed | Pending. |
| Indexed reflection geometry agrees with an independent reference | No completed, pre-toleranced diffraction report is indexed | Pending. |
| Directional elasticity agrees with an independent tensor reference | No completed, tensor-basis-aware report is indexed | Pending. |
| Researchers outside the development environment installed or used the software | No external test or use record is indexed | Pending. |
| The software changed a research decision, dataset, presentation, preprint, or paper | Author reports published use; affected result and software contribution are not yet mapped to sources | Source verification pending. |

The evidence ledger intentionally retains empty research-use, validation, and
external-engagement arrays until their source records satisfy the documented
checks. Do not substitute prospective plans for completed work.
