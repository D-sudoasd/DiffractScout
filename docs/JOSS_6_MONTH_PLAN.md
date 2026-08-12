# Six-month public-development and submission plan

JOSS pre-review screening requires at least six months of public development,
with activity distributed across that period. The clock starts on the date the
GitHub repository is actually public. Local commit dates, a one-time code
import, or retrospective issue creation do not establish public history.

Run the project preflight at any time:

```bash
python scripts/joss_readiness.py \
  --public-since YYYY-MM-DD \
  --output build/joss-readiness
```

Use `--strict` only as a release or submission gate. The report cannot verify
that local commits were publicly visible; the GitHub timeline remains the
evidence source.

## Worked calendar

If the repository becomes public on **12 August 2026**, six calendar months are
completed on **12 February 2027**. A practical submission target is **15
February 2027**, after checking the full public record and the final tagged
release. If publication occurs later, shift every milestone by the same amount.

| Period from public date | Required work | Public evidence |
|---|---|---|
| Day 0–30 | Publish v0.3.0, enable CI, open roadmap and validation issues, document installation on a clean machine | public repository, CI runs, release notes, initial issues |
| Day 31–60 | Complete one independent crystallographic comparison and resolve every discrepancy | validation issue, versioned inputs, result table, pull request |
| Day 61–90 | Publish one real-material workflow with licensed or synthetic-reconstructable inputs and predeclared tolerances | archived case report, hashes, issue discussion, release |
| Day 91–120 | Obtain external testing or review; improve documentation from observed user friction | public user report, issue/PR, contributor credit with consent |
| Day 121–150 | Complete independent elasticity validation, API review, accessibility review, and release-candidate audit | validation report, CI artifacts, release candidate |
| Day 151–six-month date | Freeze scientific definitions, archive the submission release, add DOI, rebuild paper, audit every claim and citation | DOI, tag, release, paper PDF, readiness report |
| After six-month date | Confirm activity is distributed, no blocking issues remain, and the submission commit matches the archive | final readiness report and JOSS submission |

## Monthly operating rule

Each public change must correspond to real software, documentation,
validation, support, or research use. Do not manufacture commits, issues,
contributors, downloads, or citations to make the timeline appear active.
Combine trivial edits when they belong to one change; retain separate records
when they document independent review or validation.

At the end of each month:

1. review the scheduled `Monthly JOSS maintenance snapshot` result, then run tests, analytic benchmarks, demo verification, and the release checker after any corrective change;
2. archive benchmark and validation outputs as CI or release artifacts;
3. update `docs/evidence/impact_evidence.json` with public URLs only;
4. review open scientific and software issues;
5. update the changelog and roadmap from completed work;
6. review Dependabot pull requests, merging only updates that pass the full checks and retain scientific behavior;
7. run `scripts/joss_readiness.py` and retain the report.

The scheduled workflow is a reproducibility record for a specific public commit. A green timer-triggered run without a code, validation, documentation, release, issue, or review outcome is not counted as active development. Public activity should reflect work that was actually needed and reviewed.

## Final submission gates

- public repository age is at least six calendar months;
- development is visibly distributed across the period;
- supported installation succeeds from the archived release;
- all automated tests and 45 analytic benchmark checks pass;
- at least one real research-use case supports the impact statement;
- at least one independent numerical validation is public;
- external engagement is documented for the single-author project;
- the submission release has a persistent archive DOI;
- paper sections, word count, figures, references, author metadata, funding,
  acknowledgements, and AI disclosure are final;
- the Open Journals draft PDF has been inspected page by page;
- no manuscript claim exceeds the linked evidence.