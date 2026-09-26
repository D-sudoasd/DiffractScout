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
themselves. A new [pymatgen comparison case](../validation_cases/independent_engines/README.md)
checks diffraction positions and selection rules on four synthetic CIFs, plus
directional Young's moduli for a synthetic cubic stiffness matrix. The
immutable report is in public candidate commit
[`a09ee1b`](https://github.com/D-sudoasd/DiffractScout/blob/a09ee1b0e48de4bf07898bceda4bec46b70dab43/validation_cases/independent_engines/reference_engine_comparison.md);
the evidence ledger records its Markdown and JSON hashes. It passes the stated
software-comparison tolerances for those inputs and versions. It does not
establish a real-material property, experimental agreement, external adoption,
or research impact.

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

The two reports under `validation_cases/independent_engines/` are indexed with
the immutable commit `a09ee1b`, the Markdown report hash, and the JSON result hash.
They satisfy the local readiness script's diffraction and elasticity
comparison-record requirements for those synthetic inputs and conventions.
They are implementation cross-checks, not experimental validation or reports
from an external validator. The current JOSS checklist does not name
independent diffraction and elasticity reports as stand-alone reviewer gates.

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
unpublished local work, or automatic CI. Public PR #14 records proposed
iteration at its current public head; do not describe it as merged or released.
A tagged software release is not an immutable archive DOI. After successful
review, tag and archive the reviewed source and record its DOI for the
publication stage.

## Claim ledger

| Potential manuscript claim | Evidence now available | Status |
|---|---|---|
| The software has been used in published research | Submitting-author report, 26 September 2026; representative papers and exact use not yet indexed | **Reported; citation-level audit pending.** Do not state a paper count until verified. |
| The package reproduces defined analytic diffraction and elasticity cases | 45-check analytic suite, synthetic offline FCC workflow, and the pymatgen reference-engine comparison | Supportable for the named analytic/synthetic cases and recorded implementations only; not an experimental-accuracy or impact claim. |
| A real multiphase workflow informed a specific research decision | No hashed, versioned case report is indexed | Pending. |
| Indexed reflection geometry agrees with an independent reference | Pymatgen `XRDCalculator` comparison on four synthetic CIFs with recorded grouping and position tolerances | Verified for those fixtures and settings only; not for real materials or experiment. |
| Directional elasticity agrees with an independent tensor reference | Pymatgen compliance contraction on one synthetic cubic matrix and `[100]`, `[110]`, `[111]` directions | Verified for that matrix, basis, convention, and reference version only; not for experimental or database tensors. |
| Researchers outside the development environment installed or used the software | No external test or use record is indexed | Pending. |
| The software changed a research decision, dataset, presentation, preprint, or paper | Author reports published use; affected result and software contribution are not yet mapped to sources | Source verification pending. |

The evidence ledger intentionally retains empty research-use and
external-engagement arrays until their source records satisfy the documented
checks. The validation entries link to immutable source-commit URLs and hashed
reports. Do not substitute these numerical comparisons for research-use or
external-engagement evidence.
