# JOSS submission readiness

Assessment date: **26 September 2026**

Software assessed: the **0.4.0 development candidate** on the current branch.
The latest public `main` snapshot at this assessment was commit
[`0d56f99`](https://github.com/D-sudoasd/DiffractScout/commit/0d56f99e10abd7e32e87c6f0e5344fc29ba3c670),
published on 12 September 2026. The candidate work in this checkout is not yet
part of that public history.

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
repository has one tagged release (`v0.3.0`) and merged maintenance and feature
pull requests. Its public development history currently spans only August and
September 2026, with the latest public commit on 12 September. The 0.4.0
candidate, its release acceptance, and its remote CI record are not yet
complete for the source under review.

The submitting author has reported that the software was used in multiple
published papers. This is a meaningful research-use lead, not a reason to
describe the use as independently verified: representative citations, the
software version and functionality used, and the specific research outcomes
still need to be mapped to the manuscript and evidence ledger. Do not describe
the project as having no research use. Do not turn a reported use into a
completed evidence record before its sources are identified.

The **official JOSS pre-review blockers** are the public-history threshold and
demonstrated research impact. The recorded history is currently too short and
does not yet span the required period. The research-impact claim needs
traceable evidence from the reported publications or another documented
research workflow. JOSS also screens iterative development and open-source
practice; the current public record is heavily concentrated in August, with no
recorded non-author issue, pull request, or discussion. That makes continued,
substantive public iteration important even after the calendar threshold.

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
| Automated verification | Test suite, analytic benchmark, CI, demo and bundle verifier | Engineering evidence exists; run the full release acceptance path and required remote CI on the final commit. Analytic fixtures do not establish experimental accuracy. |
| Public development history | Repository created 12 August; `v0.3.0`; public PRs and commits through 12 September | **Official blocker.** Continue real, iterative development in public through more than six months; do not count private history, scheduled CI, or planned activity. |
| Research impact | Author reports multiple published uses; individual records are not yet indexed | **Official blocker until traceable evidence is supplied.** Add representative papers with DOI/URL, exact use, software version or commit, and the related research result. |
| Community engagement | Public issue and contribution routes exist; no external engagement is recorded | Reviewers value collaborative context. Capture actual external use, review, discussion, or contribution with consent where attribution is used. |
| Manuscript | Required JOSS sections are present in the draft | Revise and build with the official Open Journals workflow; inspect every page and align impact, citations, date, author list, funding, and AI disclosure with evidence and author confirmation. |
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

The `release` stage is a project acceptance check over the exact source. It
does not prove scientific validity or submission eligibility. The `submission`
stage includes both official criteria and the stricter local project gates
described above; inspect each named check rather than treating its aggregate
blocker count as a JOSS verdict. The `publication` stage is run after review,
when the final tagged source and immutable software archive DOI are available.

For this assessment, a non-strict submission snapshot was generated with
`--as-of 2026-09-26`. At that time the working source was uncommitted, so source
identity and release acceptance were not established for the candidate. The
machine-readable report in the ignored `outputs/` directory is a diagnostic
snapshot only; rerun the script against the selected clean commit before any
submission decision.

## Evidence boundaries

The 45-check analytic benchmark and synthetic FCC workflow verify specified
mathematical, software, and provenance contracts. They do not by themselves
show that the software informed a research decision, agree with experimental
measurements, or demonstrate adoption. The author-reported published uses
should be represented in the paper only after the corresponding papers and
specific use have been verified and cited.

Likewise, repository views, stars, downloads, scheduled workflows, a local
comparison experiment, or this feature-upgrade branch do not establish an
external user or a six-month public development history. Add records to
`docs/evidence/impact_evidence.json` only when each public URL, date, outcome,
source version, and consent requirement can be checked.

## Official JOSS sources checked 26 September 2026

- [Submission requirements and pre-review screening](https://joss.readthedocs.io/en/latest/submitting.html)
- [Review criteria](https://joss.readthedocs.io/en/latest/review_criteria.html)
- [Reviewer checklist](https://joss.readthedocs.io/en/latest/review_checklist.html)
- [Paper format and length](https://joss.readthedocs.io/en/latest/paper.html)
- [JOSS policies, including AI disclosure](https://joss.readthedocs.io/en/latest/policies.html)

JOSS editors and reviewers make the final scope, significance, and acceptance
decisions from the submitted software, paper, and public record.
