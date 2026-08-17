# JOSS readiness assessment

Assessment date: **12 August 2026**

Software version assessed: **0.4.0 release candidate**

Public repository date: **12 August 2026**

Earliest six-calendar-month date: **12 February 2027**

Project's earliest practical submission date: **15 February 2027**

Primary requirements consulted:

- JOSS review criteria: `https://joss.readthedocs.io/en/latest/review_criteria.html`
- JOSS review checklist: `https://joss.readthedocs.io/en/latest/review_checklist.html`
- JOSS paper format: `https://joss.readthedocs.io/en/latest/paper.html`
- JOSS submission and archive sequence: `https://joss.readthedocs.io/en/latest/submitting.html`
- JOSS AI policy: `https://joss.readthedocs.io/en/latest/policies.html`

## Current conclusion

The repository has an MIT license, installable package metadata, CLI/API/GUI,
deterministic tests and analytic benchmarks, cross-platform CI, user and
developer documentation, contribution and support routes, a JOSS-format paper,
and an explicit AI disclosure. The public `main` workflow has run successfully,
but the 0.4.0 release candidate must still complete its own local and remote
acceptance checks.

JOSS submission is **blocked** by evidence and time, not by a confirmed
scientific correctness defect. The project currently lacks a completed real
multiphase research-use case, independent public diffraction and elasticity
comparisons, external engagement, distributed public development over the
required period, and final human-confirmed submission metadata.

The local `v0.3.0` tag is retained as history and must not be moved. The first
complete public software baseline should be a new `v0.4.0` tag and GitHub
Release after release-stage acceptance. Tag creation, pushing, and Release
publication are external writes and are not part of the local implementation.

## Three readiness stages

```bash
python scripts/check_release.py
python scripts/joss_readiness.py --stage release --strict
python scripts/joss_readiness.py --stage submission --strict --as-of YYYY-MM-DD
python scripts/joss_readiness.py --stage publication --strict --as-of YYYY-MM-DD
```

| Stage | Purpose | Evidence intentionally not required yet |
|---|---|---|
| `release` | Verify release structure, version/license metadata, evidence-ledger integrity, paper structure, canonical repository identity, and an exact-source receipt from the complete docs/tests/demo/benchmark/wheel/sdist/Twine preflight | Six-month history, research impact, external engagement, archive DOI |
| `submission` | Add public-development age and distribution, real research use, separate diffraction and elasticity validations, external engagement, remote CI, official JOSS build, and human metadata confirmation | Final post-review archive DOI |
| `publication` | After JOSS review, require the final commit, version tag, immutable software archive DOI, and citation metadata to match | None |

Non-strict runs always return zero after producing an honest status report.
`--strict` returns a blocking exit code only for the selected stage. The JSON
and Markdown reports include the result for all three stages. Run
`python scripts/check_release.py` first to create the ignored, current-source
release receipt; skipped tests or package builds cannot create that receipt.
The receipt also covers a clean-environment install and demo/verify/benchmark/
quick-export run of the newly built wheel.
Local release-candidate work may remain uncommitted, but submission and
publication stages require a clean checkout so the repository state, HEAD,
remote CI commit, official paper-build commit, and evidence hashes identify the
same source.

## Repository and software status

| Criterion | 0.4.0 candidate state | Evidence or remaining action |
|---|---|---|
| OSI-approved license | Complete | Plain-text MIT `LICENSE`; retained source notices in `NOTICE.md` |
| Installable research software | Implemented | `pyproject.toml`; CLI, quick-export, and GUI entry points; clean-wheel CI job |
| Scientific scope and need | Documented | README; paper; `docs/COMPARISON.md`; scientific contracts |
| User examples and API documentation | Implemented | README; `docs/API.md`; GUI guide; offline demo |
| Automated verification | Implemented | Full suite reported by pytest/CI; stable 45-check analytic benchmark |
| Continuous integration | Public baseline green | Re-run every required job on the selected 0.4.0 release commit |
| Non-destructive evidence bundles | Implemented | Staged writes, rollback, manifest verification, structured diagnostics |
| Contribution/support/security | Complete | Contribution guide, issue forms, support, conduct, governance, security |
| JOSS paper structure | Drafted | All required headings and current approximate word range pass the local preflight; `paper.pdf` must be rebuilt from the changed source |
| Public development | In progress | Public clock began 2026-08-12; only genuine distributed work linked in `public_development_activity` counts |
| Real research use | Pending author input | Intake scaffold at `validation_cases/real_multiphase_case/README.md` |
| Independent validation | Pending | One public diffraction and one public elasticity record are required |
| External engagement | Pending | At least one public external installation, use, review, issue, or contribution |
| Software archive DOI | Post-review | Required by `publication`, not by the initial `submission` stage |

## Evidence that code changes cannot manufacture

The packaged analytic suite and synthetic FCC fixture establish calculation,
schema, provenance, and integrity contracts. They do not establish experimental
validity, adoption, or research impact. Only completed and traceable records may
be added to `docs/evidence/impact_evidence.json`.

The real multiphase case must identify the material, lawful input source,
software version, frozen CIF hashes, complete settings, result bundle, actual
research decision, and limitations. Online discovery context may be recorded,
but numerical reproduction must use the frozen and hashed structures.

Independent diffraction and elasticity comparisons must declare their
tolerances and conventions before inspecting the DiffractScout result. External
feedback must be public and used with attribution consent. Empty evidence arrays
are preferable to prospective or inferred records.

## Paper status

The draft contains every required JOSS section and remains within the local
approximate word-count range. Its Summary has been simplified for a broad
reader. The Research impact statement deliberately remains limited to current
analytic and community-readiness evidence until the real case is complete. The
tracked PDF predates this revision and is only a layout baseline; submission
readiness remains blocked until the official Open Journals workflow rebuilds
the revised source and its public run URL is recorded. The readiness report
prints stable SHA-256 values for the paper inputs and PDF; submission requires
those exact values in the evidence ledger so a stale PDF cannot pass merely
because a fresh checkout changed filesystem timestamps.

Before submission, the author must confirm authorship, ORCID, affiliation,
funding, contributors, related publications, the full human review of
AI-assisted work, a green remote CI URL, and the official Open Journals build
URL. During JOSS review, editor/reviewer responses must be written by the human
author rather than generated by AI.

The final software archive DOI is added only after review when JOSS requests the
final tagged release and archive. It must then be synchronized across
`CITATION.cff`, the bibliography, GitHub Release, and the review issue without
being confused with the later JOSS article DOI.
