# Six-month public-development and submission plan

The public DiffractScout repository was created on **12 August 2026**. Six
calendar months are completed on **12 February 2027**; the project uses **15
February 2027** as its earliest practical submission date. Passing the date is
necessary but not sufficient: JOSS editors assess whether development is real,
open, distributed, and connected to scholarly use.

Use the staged preflight:

```bash
# Software release candidate
python scripts/check_release.py
python scripts/joss_readiness.py --stage release --strict

# JOSS submission candidate; the date does not override missing evidence
python scripts/joss_readiness.py \
  --stage submission --strict --as-of YYYY-MM-DD \
  --output build/joss-readiness

# Post-review tag/archive consistency
python scripts/joss_readiness.py \
  --stage publication --strict --as-of YYYY-MM-DD
```

The report cannot prove that local commits were public. Retain meaningful public
GitHub commit, issue, pull-request, and Release URLs as the authoritative
timeline and add completed records to the ledger's
`public_development_activity` array. The strict gate counts distinct calendar
months only from those auditable URLs; scheduled workflow runs alone do not
qualify.

## Milestones from 12 August 2026

| Period | Required work | Public evidence |
|---|---|---|
| Aug-Sep 2026 | Complete and publish the v0.4.0 baseline after release-stage, clean-wheel, cross-platform CI, and official paper-build checks | tag, GitHub Release, CI and draft-build URLs, release artifacts |
| Sep-Oct 2026 | Complete one lawful, frozen multiphase-alloy workflow and an independent diffraction comparison with predeclared tolerances | case report, hashed inputs, bundle, comparison table, issue/PR |
| Nov 2026 | Obtain external clean installation or research-use feedback and resolve real user friction | public user report, issue/PR, consented attribution |
| Dec 2026 | Complete independent directional-elasticity validation and API/GUI documentation audit | tensor/basis report, comparison results, maintenance release |
| Jan 2027 | Freeze submission scope, audit every claim/citation, confirm author metadata, and complete the reviewer-checklist matrix | submission candidate, green CI, official JOSS PDF, readiness report |
| 12-15 Feb 2027 | Confirm six-month age and genuinely distributed public activity | public timeline audit |
| After 15 Feb 2027 | Submit only if `--stage submission --strict` passes and no blocking scientific or software issue remains | JOSS submission and public pre-review issue |
| After successful JOSS review | Create the final tag if the software changed, archive the repository, add the software DOI, and run publication-stage readiness | final tag, Zenodo/figshare record, DOI, review issue update |

## Monthly operating rule

Every public change must correspond to needed software, documentation,
validation, support, dependency, release, or research-use work. Do not create
empty commits, retrospective issues, invented contributors, or unsupported
claims to simulate activity.

At the end of each month:

1. review the monthly reproducibility workflow and correct real failures;
2. retain demo, benchmark, readiness, and release artifacts for identifiable commits;
3. update the evidence ledger only with completed public URLs;
4. review open scientific and software issues;
5. update the changelog and roadmap from completed work;
6. review dependency pull requests through the full scientific regression path;
7. retain a non-strict submission-stage readiness snapshot.

A green scheduled run shows that a commit remains reproducible. It does not by
itself demonstrate sustained development or research impact.

## Submission gate

- date is 15 February 2027 or later;
- public work is distributed across at least four calendar months;
- a supported wheel installs and runs outside the source tree;
- all required remote CI jobs and the official JOSS paper build pass;
- the 45-check analytic benchmark passes;
- the real multiphase case is public, lawful, frozen, hashed, and tied to an actual research decision;
- independent diffraction and elasticity validations are public;
- at least one public external-use, installation, review, issue, or contribution record exists;
- authorship, affiliations, funding, contributors, related work, references, and AI disclosure are human-confirmed;
- every Research impact statement claim maps to the evidence ledger;
- `python scripts/joss_readiness.py --stage submission --strict --as-of YYYY-MM-DD` passes.

The immutable software archive DOI is a post-review publication requirement,
not a prerequisite for opening the initial JOSS submission.
