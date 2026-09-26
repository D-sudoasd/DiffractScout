# JOSS submission readiness

Assessment date: **26 September 2026**

This assessment preserves two distinct snapshots. The baseline assessment
below refers to commit [`0d56f99`](https://github.com/D-sudoasd/DiffractScout/commit/0d56f99e10abd7e32e87c6f0e5344fc29ba3c670)
on `main` (12 September 2026), **before the 0.4.0 usability and manuscript
upgrade**. On 26 September, the maintainer opened public [PR #14](https://github.com/D-sudoasd/DiffractScout/pull/14)
with the 0.4.0 candidate, workbook and workflow updates, and synthetic
reference-engine comparisons. The PR is public development evidence, but its
changes were not yet merged at this snapshot. The new comparisons are
described below; their final evidence-ledger commit and hashes must match the
public source commit that contains the frozen reports.

The GitHub API reports that the public repository was created at
**12 August 2026 10:02:29 UTC**. Six calendar months elapse on 12 February
2027; JOSS currently requires **more than** six months of public history, so
12 February itself is not an eligible submission date. The project retains
**15 February 2027** as a conservative earliest planning date, conditional on
active public development spanning that period. A date alone cannot satisfy
the history or research-impact criteria.

## Assessment

DiffractScout has an MIT license, Python package metadata, command-line,
Python API and desktop interfaces, automated checks, documentation,
contribution and support routes, and a JOSS-formatted manuscript. The public
repository has one tagged release (`v0.3.0`), merged maintenance and feature
pull requests, and public PR #14 opened on 26 September. The public record
therefore spans August and September 2026, with substantial activity
concentrated in August and a later iteration proposed in September. PR #14
does not by itself establish a completed release or passing CI for its exact
candidate source.

The submitting author has reported that the software was used in multiple
published papers. This is a meaningful report of actual research use, not a
reason to describe the use as independently verified: representative
citations, the software version and functionality used, and the specific
research outcomes still need to be mapped to the manuscript and evidence
ledger. Do not describe the project as having no research use. Do not turn a
reported use into a completed evidence record before its sources are
identified.

The **official JOSS pre-review blockers** are the public-history threshold and
demonstrated research impact. The repository was created on 12 August 2026;
only August and September are represented so far, and the history is still
concentrated in August. PR #14 adds a later public iteration, but the required
period has not elapsed and future activity cannot be assumed. The author's
reported publication use needs traceable evidence from representative papers
or another documented research workflow. JOSS also screens iterative
development and open-source practice. External engagement is a strong
positive signal, not a standalone gate; no non-author interaction was
recorded at this snapshot.

The repository's local readiness script applies additional project policies:
at least four months with indexed public activity, a hashed real-material
research-use case, public diffraction and elasticity comparison reports, and
an external-engagement record. These are **stricter local evidence gates**, not
separate numeric requirements in the JOSS reviewer checklist. They support
this project's scientific claim control and should not be represented as
verbatim JOSS criteria. A local comparison run can support a validation record
when its methods and predeclared tolerances are documented, but it is not
external user adoption or experimental validation.

## Status by criterion

| Area | Evidence at this assessment | State and next action |
|---|---|---|
| License and package | `LICENSE`, `pyproject.toml`, Python entry points | Present; rerun packaging checks on the final submission commit. |
| Scope and software need | README, comparison and scientific-contract documents, manuscript | Defined; manuscript must explain the workflow contribution and build-versus-contribute rationale. |
| User and API documentation | README, CLI/API/GUI guides, offline demo | Present; audit against the final public interfaces. |
| Automated verification | Test suite, analytic benchmark, CI, demo and bundle verifier | Remote CI for commit `39f1477` [#36243627211](https://github.com/D-sudoasd/DiffractScout/actions/runs/36243627211) passed all ten jobs, including Windows, macOS, Python 3.10–3.13, GUI, optional dependencies, and the installed wheel. The local preflight on that source passed 543 tests, 45 analytic checks, packaging, and isolated wheel workflows. Rerun acceptance when the selected source changes. Analytic fixtures do not establish experimental accuracy. |
| Public development history | Repository created 12 August; `v0.3.0`; merged PRs through August; public PR #14 opened 26 September | **Official blocker.** Only August and September are represented. Continue substantive, iterative public work for more than six months; the planned earliest date of 15 February 2027 is conditional, not an eligibility guarantee. |
| Research impact | Author reports multiple published uses; individual records are not yet indexed | **Official blocker until traceable evidence is supplied.** Add representative papers with DOI/URL, exact use, software version or commit, and the related research result. |
| Community engagement | Public issue and contribution routes exist; no non-author engagement is recorded | External engagement is a strong positive signal. Capture real use, review, discussion, or contribution with consent where attribution is used; do not treat its absence as a separate JOSS hard gate. |
| Manuscript | Required JOSS sections are present in the draft; the Open Journals workflow for commit `a09ee1b` [#36242597087](https://github.com/D-sudoasd/DiffractScout/actions/runs/36242597087) succeeded | Four-page PDF generation and source/artifact, rendered-page, reference, and text-layer checks passed. The submitting author still must confirm research-use citations, date, complete authors, funding, and full human review of AI-assisted work. |
| Submission metadata | Known author details have been confirmed by the user; other fields remain unconfirmed | Confirm the complete author list and consent, each affiliation, funding and sponsor role, contributors, related publications, and full human review of AI-assisted work. |
| Post-review archive | No final tagged archive DOI is recorded | Create the final tag and archive DOI after review, then synchronize the citation and review records. This is a post-review step, not an initial submission blocker. |

## Staged project preflight

The local script reports release, submission, and publication stages:

```bash
python scripts/check_release.py
python scripts/joss_readiness.py --stage release --strict
python scripts/joss_readiness.py --stage submission --strict --as-of YYYY-MM-DD
python scripts/joss_readiness.py --stage publication --strict --as-of YYYY-MM-DD
```

For final submission checks, copy the evidence ledger to an ignored file and
update that copy with the selected commit's verification records and the
author's confirmations. This preserves the identity of the committed source
while recording its completed checks:

```bash
mkdir -p outputs
cp docs/evidence/impact_evidence.json outputs/submission-evidence.json
python scripts/joss_readiness.py --stage submission --strict --evidence-file outputs/submission-evidence.json
```

`--evidence-file` reads the specified ledger without changing it and records
its path in the report. The usual schema, hashes, and confirmation requirements
still apply. Remote CI must match the selected HEAD. An official PDF build may
use HEAD or an ancestor only when Git proves that the manuscript, bibliography,
and both figure blobs are identical to HEAD; PDF and source hashes are still
checked. This permits recording the generated PDF without invalidating its
build evidence. Without this option, the repository's shared ledger is used.

The `release` stage is a project acceptance check over the exact source. It
does not prove scientific validity or submission eligibility. The `submission`
stage includes both official criteria and the stricter local project gates
described above; inspect each named check rather than treating its aggregate
blocker count as a JOSS verdict. The `publication` stage is run after review,
when the final tagged source and immutable software archive DOI are available.

The earlier non-strict submission snapshot used `--as-of 2026-09-26` against
the **pre-upgrade, uncommitted working source**. It is a diagnostic snapshot,
not a readiness result for PR #14. Rerun release and submission checks against
the selected clean commit after the source, comparison receipts, paper, and
remote CI are frozen; do not reuse the ignored report in `outputs/` as current
evidence.

## Evidence boundaries

The 45-check analytic benchmark, synthetic FCC workflow, and new pymatgen
reference-engine comparison verify specified mathematical, software, and
provenance contracts for named synthetic fixtures. They do not by themselves
show that the software informed a research decision, agree with experimental
measurements, or demonstrate adoption. The author-reported published uses
should be represented as specific examples in the paper only after the
corresponding papers and software contribution have been verified and cited.

Likewise, repository views, stars, downloads, scheduled workflows, synthetic
engine comparisons, or a public PR do not establish external adoption or a
six-month public development history. PR #14 is a public record of proposed
iteration; do not describe it as merged or released before that occurs. Add
records to `docs/evidence/impact_evidence.json` only when each public URL,
date, outcome, source version, and consent requirement can be checked.

## Official JOSS sources checked 26 September 2026

- [Submission requirements and pre-review screening](https://joss.readthedocs.io/en/latest/submitting.html)
- [Review criteria](https://joss.readthedocs.io/en/latest/review_criteria.html)
- [Reviewer checklist](https://joss.readthedocs.io/en/latest/review_checklist.html)
- [Paper format and length](https://joss.readthedocs.io/en/latest/paper.html)
- [JOSS policies, including AI disclosure](https://joss.readthedocs.io/en/latest/policies.html)

JOSS editors and reviewers make the final scope, significance, and acceptance
decisions from the submitted software, paper, and public record.
