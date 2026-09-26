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
  and outcome. Do not count private history, planned or empty issues, scheduled
  CI, stars, views, download counts, or unmerged changes.
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

Leave confirmation booleans false and URLs/hashes empty until the submitting
author confirms them for the selected source. As of 26 September 2026, the
author confirmed that the currently listed Delun Gong name, ORCID, and
Institute of Metal Research affiliation are correct. The complete author
list, any coauthor consent and affiliations, funding/sponsor role,
contributor list, related publications, and human review of all AI-assisted
work still need to be confirmed; a current identity confirmation does not
complete that review.

Record the public remote CI run and official Open Journals build only when
they test the same exact 40-character commit selected for submission. After
building and inspecting the final PDF, record the source and PDF SHA-256 values
reported by readiness. Following successful JOSS review, create the final tag
and software archive DOI and enter them for the `publication` stage.
