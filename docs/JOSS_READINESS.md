# JOSS readiness assessment

Assessment date: **30 July 2026**

Software version assessed: **0.2.0**

Primary current requirements consulted:

- JOSS review criteria: `https://joss.readthedocs.io/en/latest/review_criteria.html`
- JOSS paper format: `https://joss.readthedocs.io/en/latest/paper.html`
- JOSS submission screening: `https://joss.readthedocs.io/en/latest/submitting.html`
- JOSS AI policy: `https://joss.readthedocs.io/en/latest/policies.html`

## Repository and software criteria

| Criterion | v0.2.0 state | Evidence or remaining action |
|---|---|---|
| OSI-approved license | Complete | `LICENSE` contains MIT text; retained source-project notices are in `NOTICE.md` |
| Installable research software | Complete locally | `pyproject.toml`; CLI and GUI entry points; wheel job configured |
| Clear statement of need | Complete | `README.md`; `paper/paper.md` |
| Distinct contribution and related software | Documented | `docs/COMPARISON.md`; paper State of the field |
| User installation and examples | Complete | README; GUI guide; offline demo; local and Materials Project examples |
| Core API documentation | Complete for public API | `docs/API.md`; docstrings |
| Scientific definitions and units | Complete for implemented scope | `docs/SCIENTIFIC_CONTRACTS.md` |
| Automated tests | Complete for offline contracts | 46 deterministic tests; analytic, failure, transaction, export, and integrity cases |
| Continuous integration | Configured, remote run pending | Python 3.10–3.13, Windows/macOS, Xvfb GUI, wheel, demo, coverage, Ruff |
| Non-destructive and auditable output | Complete | staged writes, rollback, strict manifest verification, structured diagnostics |
| Contribution route | Complete | `CONTRIBUTING.md`, issue forms, pull-request template |
| Support, conduct, and security routes | Complete | README, `CODE_OF_CONDUCT.md`, `SECURITY.md` |
| Release process | Documented | `docs/RELEASE.md`, `CHANGELOG.md`, `CITATION.cff`, release checker |
| Versioned software release | Pending remote publication | create repository, push, run CI, tag v0.2.0, publish release |
| Archived software DOI | Pending | archive a tagged public release and add DOI to citation/paper metadata |
| JOSS paper sections | Drafted | Summary, Statement of need, State of field, software design, impact, AI disclosure, acknowledgements, references |
| AI usage disclosure | Drafted and specific | `AUTHORS.md`; `paper/paper.md` |
| Research impact | Evidence package pending | real research case, independent comparisons, adoption/feedback records |
| Sustained public development | Time-dependent and pending | public issues, commits, pull requests, and releases distributed across the required period |

## Technical changes completed for v0.2.0

The v0.2.0 hardening work addresses review-relevant software quality:

- full scientific controls and two workflows in the desktop GUI;
- strict distinction between Materials Project query failure, missing data, missing tensor, and frame transformation requirement;
- unique and explicit elastic-sidecar pairing;
- robust CIF block, cell, atom-site, and space-group validation;
- profile-grid and reciprocal-space resource guards;
- input/output overlap rejection;
- staging, verification, atomic replacement, and rollback for result bundles;
- refusal to overwrite a damaged existing bundle;
- structured diagnostic CSV/workbook output;
- strict detection of unlisted, duplicate, unsafe, missing, modified, or symlinked bundle files;
- spreadsheet formula-injection protection;
- expanded tests, cross-platform CI configuration, Xvfb GUI smoke check, and clean-wheel installation job;
- revised user, GUI, architecture, scientific-contract, validation, release, and manuscript documentation.

## Criteria that cannot be satisfied by code changes alone

### Public development history

JOSS screening currently expects a sustained public development record rather than a one-time software import. The project needs visible iteration through commits, issues, pull requests, reviews, and releases over the applicable public period. Rewriting commit dates or manufacturing activity would not supply valid evidence.

### Demonstrated research impact

The synthetic fixture and automated tests establish calculation and provenance contracts. They do not show that the software has enabled research. A defensible evidence package should include:

1. a versioned real-material candidate-screening case that reaches an experimental planning or interpretation output;
2. independent diffraction comparisons with stated numerical tolerances;
3. an independent directional-elasticity comparison;
4. documented use by the author's group;
5. evaluation or contribution from at least one external user when feasible;
6. public issue or pull-request records arising from those uses;
7. a tagged release archived with a DOI.

Claims in the paper's Research impact statement should be updated only after those records exist.

## Paper status

`paper/paper.md` follows the current JOSS software-paper structure and keeps the scientific scope bounded. It documents the integrated workflow, design decisions, transaction and integrity controls, structured diagnostics, testing, related software, and AI-assisted development. The following metadata still requires author confirmation:

- final author list and order;
- ORCID identifiers;
- affiliation wording;
- funding and facility acknowledgements;
- contributor recognition;
- archive DOI;
- verified research-impact statements.

The exact formatted PDF should be rebuilt with the Open Journals draft workflow for every release candidate and inspected page by page.

## Remote publication gate

At the time of this assessment, `D-sudoasd/DiffractScout` does not exist in the connected GitHub account. The repository must be created before the configured CI, pull-request, merge, release, and branch-cleanup workflow can run. The two source repositories, `PhaseScout` and `CIF2Peaks`, remain unchanged.

## Submission gate

A formal JOSS submission should proceed only after all of the following are true:

- the public-development-history requirement is met;
- all required CI jobs pass on the selected release commit;
- real validation cases are archived and reproducible;
- research-impact statements have traceable evidence;
- authorship, ORCID, affiliation, funding, acknowledgements, and contributors are confirmed;
- a tagged release is archived and the DOI is present in `CITATION.cff` and the paper;
- the paper compiles with current Open Journals tooling;
- the human author has reviewed all AI-assisted code, documentation, references, and scientific claims.
