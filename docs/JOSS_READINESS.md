# JOSS readiness assessment

Assessment date: **30 July 2026**.

Primary criteria consulted:

- JOSS review criteria: `https://joss.readthedocs.io/en/latest/review_criteria.html`
- JOSS paper format: `https://joss.readthedocs.io/en/latest/paper.html`
- JOSS submission screening: `https://joss.readthedocs.io/en/latest/submitting.html`
- JOSS AI policy: `https://joss.readthedocs.io/en/latest/policies.html`

## Repository and software criteria

| Criterion | Current repository state | Evidence |
|---|---|---|
| OSI-approved license file | Complete | `LICENSE` contains MIT text |
| Installable package | Complete | `pyproject.toml`; editable install and wheel validation |
| Clear statement of need | Complete | `README.md`, `paper/paper.md` |
| User installation and examples | Complete | README, offline demo, local and Materials Project examples |
| Core API documentation | Complete | `docs/API.md` and docstrings |
| Scientific assumptions and units | Complete | `docs/SCIENTIFIC_CONTRACTS.md` |
| Automated test suite | Complete for offline core | `tests/`; synthetic analytic checks and full offline pipeline |
| Continuous integration | Configured | `.github/workflows/ci.yml` |
| Contribution route | Complete | `CONTRIBUTING.md`, issue templates, PR template |
| Support and conduct routes | Complete | README, `CODE_OF_CONDUCT.md`, `SECURITY.md` |
| Release process | Complete as a documented procedure | `docs/RELEASE.md`, changelog, citation metadata |
| JOSS paper sections | Drafted | Summary, Statement of need, State of the field, Software design, Research impact statement, AI disclosure, acknowledgements, references |
| AI usage disclosure | Drafted and specific | `AUTHORS.md`, `paper/paper.md` |

## Screening criteria that cannot be created in one integration commit

### Public development history

Current JOSS screening requires a public repository for more than six months with development activity distributed across that period. The new repository must therefore remain active in public through releases, issues, pull requests and iterative commits before submission. Importing a large code snapshot or rewriting commit dates would not satisfy this criterion.

### Demonstrated research impact

The submission must provide concrete evidence such as research use, reproducible benchmarks, adoption by another group, integration into a research workflow, a preprint, or a publication enabled by the software. The current synthetic tests prove defined numerical behavior and packaging; they do not establish research impact.

Recommended evidence package:

1. a versioned real-material case beginning with an alloy/chemical system and ending with an experimental planning or interpretation table;
2. independent diffraction and elasticity comparisons with documented tolerances;
3. one internal research use record and one external user test when available;
4. public issues or pull requests resulting from those uses;
5. a tagged release archived with a DOI.

## Paper status

`paper/paper.md` is structurally compatible with the current JOSS section requirements and remains within the intended software-paper scope. The research-impact section is deliberately marked for replacement with verified evidence before submission. Author metadata, funding, acknowledgements and archive DOI also require final confirmation.

## Submission gate

A formal JOSS submission should proceed only after all of the following are true:

- the repository has met the public-development-history gate;
- the real validation cases are archived and reproducible;
- research-impact statements have traceable evidence;
- authorship, affiliation, funding and acknowledgements are confirmed;
- all tests and CI checks pass on a tagged release;
- the release is archived and the archive DOI is added to the paper and citation metadata;
- the paper is compiled with the current Open Journals `inara` workflow.
