# JOSS evidence ledger

`impact_evidence.json` is the machine-readable index checked by
`scripts/joss_readiness.py`. The assessment and claim rules are in
[`docs/ADOPTION_AND_IMPACT.md`](../ADOPTION_AND_IMPACT.md) and
[`docs/JOSS_READINESS.md`](../JOSS_READINESS.md).

## Evidence rules

Add a record only after its source is publicly accessible or retained in a
stable repository. Each record must have a source URL, date, title, exact
software version or commit, and the precise claim it supports. Additional
fields are defined by `impact_evidence.schema.json` and validated by
`scripts/joss_readiness.py`.

- Put papers and preprints in `publications_or_preprints`; include the DOI or
  stable URL and explain the software's specific role. The author reported
  published uses on 26 September 2026, but representative citations have not
  yet been identified in this ledger.
- Add a `research_use_cases` record only for a completed, versioned workflow
  with a report under `validation_cases/`, its report hash, frozen input and
  result-manifest hashes, lawful input license, research decision, and
  limitations. The local gate intentionally requires this fuller case record;
  a publication citation and a replayable case are distinct evidence types.
- Add an `independent_validations` record only after completing its report
  under `validation_cases/`. State the reference implementation/version and
  tolerance basis before comparing results. Diffraction records include the
  input hash, radiation, and scan range. Elasticity records include tensor
  source/frame, Voigt convention, and `[100]`, `[110]`, `[111]` directions.
- Add `external_engagement` only for a real external interaction or test.
  Identify the tested artifact, commands, result, outcome, and limitations.
  Set consent to true before naming a person; an unattributed record may set it
  false.
- Add `public_development_activity` for meaningful public commits, issues,
  pull requests, and releases that document real work. Record the public URL
  and outcome. An open public PR can evidence proposed iteration if its status
  is explicit; do not describe it as integrated or released. Do not count
  private history, planned or empty issues, scheduled CI, stars, views, or
  download counts. PR #14 currently points to public head commit
  `a09ee1b0e48de4bf07898bceda4bec46b70dab43`.
- Add an `archived_releases` record only when the exact final tag is archived
  with a persistent DOI. An ordinary GitHub Release does not satisfy that
  post-review record.

JOSS currently requires more than six months of active public development
history and evidence of research use at least by the developers. External
engagement is a strong positive signal. The local readiness tool adds stricter
project gates for four active public months, a hashed research-use case, both
diffraction and elasticity reports, and external engagement. The project
should report these as local controls, not as verbatim JOSS requirements.

## Submission metadata

Use `scripts/joss_readiness.py --evidence-file PATH` for a final audit ledger
stored under ignored `outputs/` or outside the repository. Copy the shared
ledger, then record the selected commit's CI/build results and confirmed
author inputs in that copy. Updating a separate file keeps the selected Git
commit unchanged. The checker reports the file it used and applies the same
validation rules; an unreadable or invalid file blocks the check.

Remote CI must verify the selected HEAD. The official PDF build may refer to
HEAD or an ancestor with identical Git blobs for `paper.md`, `paper.bib`,
`fig_workflow.png`, and `fig_validation.png`. The checker rejects unknown or
unrelated commits and changed manuscript inputs, and still checks the recorded
paper-source and PDF hashes.

Keep author-controlled confirmation booleans false until the submitting
author confirms them for the selected source. As of 26 September 2026, the
user confirmed that the currently listed Delun Gong name, ORCID, and Institute
of Metal Research affiliation are correct. The complete author list, any
coauthor consent and affiliations, funding/sponsor role, contributor list,
related publications, and human review of all AI-assisted work still need to
be confirmed; a current identity confirmation does not complete that review.

The ledger records successful CI run `36242599844` and official Open Journals
build `36242597087` on candidate commit
`a09ee1b0e48de4bf07898bceda4bec46b70dab43` as a historical snapshot. A final
audit must update the CI record to the selected HEAD; the paper build remains
usable only while its input blobs match that HEAD. The four-page PDF passed artifact
identity and rendered-content checks, while author review of all AI-assisted
work remains pending. Following successful JOSS review, create the final tag
and software archive DOI and enter them for the `publication` stage.
