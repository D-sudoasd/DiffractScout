> Historical plan written 26 September 2026. PR #14 and #15 are now merged. For current status and the author-confirmed research use, follow [the current guide](joss/README.md). The dates below remain conditional; a creation timestamp does not establish public visibility.

# Public development and JOSS submission plan

The public DiffractScout repository was created on **12 August 2026 at
10:02:29 UTC**. The current JOSS submission guidance requires more than six
months of public history with active development spanning that period. The
six-calendar-month anniversary is 12 February 2027; the project retains
**15 February 2027** as the earliest practical submission date. Passing that
date is necessary but insufficient: the public record must show iterative
work across the period and the research-impact and open-source-practice gates
must also be satisfied.

Use the staged local preflight:

```bash
# Exact-source software release acceptance
python scripts/check_release.py
python scripts/joss_readiness.py --stage release --strict

# Submission candidate; use the actual assessment date
python scripts/joss_readiness.py \
  --stage submission --strict --as-of YYYY-MM-DD \
  --output build/joss-readiness

# After JOSS review and before publication
python scripts/joss_readiness.py \
  --stage publication --strict --as-of YYYY-MM-DD
```

The script's four-active-month rule and public, hashed research-use,
diffraction, and elasticity records are stricter **project acceptance
policies**. JOSS's current screen has no separate four-month count or explicit
requirement for both types of independent numerical comparison. JOSS does
require more than six months of active, iterative public development, public
issues/PR and release evidence for a recently opened repository, and
demonstrated research impact. Do not describe the stricter local gates as
official JOSS rules.

## Evidence already on the public record

The GitHub API was checked on 26 September 2026. It reports repository
creation on 12 August, one public release (`v0.3.0`) that day, merged PRs from
12–27 August, and a later public iteration in [PR #14](https://github.com/D-sudoasd/DiffractScout/pull/14),
whose current head is commit [`a09ee1b`](https://github.com/D-sudoasd/DiffractScout/commit/a09ee1b0e48de4bf07898bceda4bec46b70dab43).
The default-branch snapshot recorded at the start of this audit was commit
`0d56f99` on 12 September; PR #14 was opened on 26 September and remains open
at this assessment. This amounts to public activity in August and September,
with earlier work concentrated in August. Commits dated before the repository
became public do not count as public history. An open public PR can document
iteration, but it must not be described as merged or released until those
events occur. CI and the official Open Journals build both passed for
candidate commit `a09ee1b`; neither result replaces the public-age requirement
or author-controlled evidence. Private work, scheduled CI runs, and download
statistics do not establish public development or external adoption.

The submitting author reports that DiffractScout was used in multiple
published papers. Representative citations and a mapping from each paper to
the software version, function used, and research result still need to be
recorded. The report is not treated as a lack of research use; it is a lead
that must be made auditable before the manuscript claims those examples.

## Milestones

| Period | Work tied to a real project need | Public evidence to retain |
|---|---|---|
| Aug–Sep 2026 | Establish the release baseline, harden the analysis workflow, and complete the current usability, workbook, CLI, and result-inspection improvements. | Existing `v0.3.0`, merged pull requests, public commits, and open PR #14 with its current head and actual CI state; do not represent unmerged changes as released. |
| Oct 2026 | Verify representative published-use records with the author; map paper citations to software versions, functions, and the described research outcome. Prepare a lawful, frozen case record if the inputs and results may be shared. | DOI/URLs, source and result hashes, exact use, limitations, and consent where another person is attributed. |
| Nov 2026 | Gather and address actual installation, workflow, or review feedback; publish any needed usability and documentation changes. | Public user/reviewer issue, discussion, PR, or consented report; exact artifact tested and outcome. |
| Dec 2026 | Maintain and, if needed, extend the project's predeclared diffraction and directional-elasticity software comparisons; address any real discrepancies before claims are made. The current candidate already includes synthetic pymatgen reference-engine reports. | Reproducible reports with reference versions, frozen inputs, units, basis/conventions, tolerances fixed in advance, hashes, and limitations. These comparisons do not establish experimental validity or research impact. |
| Jan 2027 | Freeze the intended submission source, audit every software and manuscript claim, check references and author metadata, run final acceptance, CI, and Open Journals build. | Clean commit, complete local readiness report, green remote CI URL, official PDF build URL, and full-page PDF review. |
| 12–15 Feb 2027 | Verify the public age, distributed activity, impact evidence, and submission checklist against current JOSS guidance. | Dated public-history audit and a passing submission-stage preflight. |
| After successful JOSS review | Create the final tagged release and immutable software archive; synchronize the version and archive DOI in citation metadata and the review issue. | Tag, archive DOI, matching commit hashes, and updated review record. |

These months are checkpoints, not a schedule for manufacturing activity. Publish
work when it resolves an actual software, validation, support, documentation,
or research-use need. A green scheduled workflow confirms only the tested
commit; it cannot replace iteration, research use, or community evidence.

## Submission gate

Before submitting, confirm all of the following against the same candidate:

- The repository has been public for **more than six months**, and its public
  history shows active iteration over that period, releases, and public
  issue/PR work.
- The software has demonstrable research use. Index representative published
  papers reported by the author or a complete, traceable research workflow;
  identify the source version, exact use, and research result.
- The package is installable and feature-complete, with documentation,
  examples, tests, CI, contribution instructions, and support/governance
  expectations for the submitted commit.
- The JOSS paper is 750–1750 words and contains all required sections,
  accurate citations, an AI usage disclosure, authorship/affiliation
  metadata, and a funding acknowledgement or an author-confirmed statement
  about the absence of financial support.
- The submitting author has confirmed the complete author list, affiliations,
  funding and sponsor role, contributors, related publications, and full human
  review of AI-assisted work. Every coauthor has agreed to be listed.
- The selected source is clean, release acceptance passes, required CI and the
  official Open Journals build pass for the exact commit, and every PDF page
  has been inspected.
- All research-impact statements point to traceable records. The stricter
  project evidence gates also pass if the team continues to use the local
  submission-stage readiness command.

The archive DOI is normally created after the software review is completed:
JOSS's submission instructions ask authors to tag and archive the reviewed
source before acceptance and then update the review issue. It is not a
pre-review age requirement.

## Monthly operating rule

At each monthly checkpoint:

1. review real user reports, scientific discrepancies, and software defects;
2. make and publish changes only when a concrete need exists;
3. retain release, CI, benchmark, and readiness results with their exact
   commits;
4. add public evidence only after checking its URL, date, outcome, version,
   hashes, and attribution consent; label open PRs as proposed work and do not
   count them as merged changes or releases;
5. update the manuscript and changelog from evidence and merged behavior; and
6. preserve pending or private facts as pending rather than estimating them.

Do not create empty commits, retrospective issues, or invented contributors to
simulate six months of development or collaboration.
