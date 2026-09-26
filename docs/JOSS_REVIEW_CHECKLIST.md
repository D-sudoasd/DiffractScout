# JOSS reviewer-checklist evidence matrix

Assessment date: **26 September 2026**. This project-side matrix follows the
[current JOSS reviewer checklist](https://joss.readthedocs.io/en/latest/review_checklist.html)
and its [review criteria](https://joss.readthedocs.io/en/latest/review_criteria.html).
It records evidence and open work; it is not a JOSS decision.

## General checks and open development

| JOSS item | Repository evidence | Current assessment | Evidence or action still required |
|---|---|---|---|
| Repository and license | [Public GitHub repository](https://github.com/D-sudoasd/DiffractScout); `LICENSE` | Available | Recheck the exact submission commit and issue access. |
| Major contribution and complete author list | `AUTHORS.md`, `CITATION.cff`, paper metadata, Git history | User confirmed the listed Delun Gong name, ORCID, and Institute of Metal Research affiliation. | Confirm that the author list is complete, contributions and order are appropriate, and every coauthor consents; update all metadata consistently. |
| Scope and significance | README, manuscript, comparison and scientific-contract documents | Research application and workflow are described. The author reports use in multiple published papers. | Map representative papers to DOI/URL, precise use, version or commit, and the relevant manuscript claim. Until then the statement is not yet auditable. |
| Sustained public development | GitHub repository metadata, release, merged PRs, public commits, and [open PR #14](https://github.com/D-sudoasd/DiffractScout/pull/14) | Public since 12 August 2026; public activity is documented in August and September, including the PR opened 26 September. Most earlier activity was clustered in August. | **Official blocker:** continue substantive, iterative public work for more than six months before submission. The repository date alone does not pass this check; PR #14 is public iteration, not a merged release. |
| Open-source workflow | `CONTRIBUTING.md`, issue forms, support routes, CI, one release, public PRs | Core routes exist; public PRs are maintainer-authored and no non-author discussion or contribution is recorded. | Keep resolving real issues and publishing needed changes. External engagement is a strong positive signal. Do not count self-authored roadmap issues, bots, or scheduled CI as external engagement. |
| Good open-source practices | MIT license, package metadata, tests/CI, documentation, support and governance | Present in the current public baseline. | Recheck installation, release, CI, and documentation on the final commit. |

The internal `public_development_activity` ledger records verifiable public
milestones, including an open PR as proposed public iteration with its open
status stated. It excludes commits before the repository became public,
automated CI runs, and future work. Do not describe an unmerged PR as
integrated or released. The project's four-active-month rule is a conservative
local threshold; JOSS's current screen instead requires more than six months
of active public development spanning that period and evidence of release and
public issue/PR activity.

## Functionality and documentation

| JOSS item | Repository evidence | Current assessment | Evidence or action still required |
|---|---|---|---|
| Installation | `pyproject.toml`, README, wheel CI | Python packaging and documented install path exist. | Preserve a clean-environment wheel install and run result for the submitted commit. |
| Core functionality | CLI, Python API, desktop GUI, offline demo, bundle verifier | Deterministic offline workflow and scientific contracts are documented. | Verify user-visible claims against the final release candidate; do not imply Materials Project live service verification from offline checks. |
| Performance claims | Manuscript makes no speed or scaling claim | Not applicable. | Keep it that way unless a reproducible, representative benchmark supports a new claim. |
| Statement of need and examples | README, API/GUI guides, demo | Available. | Ensure the example and final software version agree. Add a real-material example only when its source and license permit redistribution. |
| Functionality/API documentation | `docs/API.md`, `docs/GUI.md`, scientific contracts | Core behavior has dedicated documentation. | Audit public APIs and GUI behavior after the current usability changes. |
| Tests and correctness checks | `tests/`, CI run [#36242599844](https://github.com/D-sudoasd/DiffractScout/actions/runs/36242599844), 45-check analytic benchmark, and synthetic pymatgen diffraction/elasticity comparison | Remote CI succeeded on commit `a09ee1b`; reference-engine reports are limited to the named synthetic inputs and conventions. | Run the complete local release check on the exact final clean source. Analytic and cross-engine checks are not experimental validation. |
| Community pathways | `CONTRIBUTING.md`, issue templates, `SUPPORT.md`, `GOVERNANCE.md` | Present. | Confirm public access and route new user feedback into a traceable issue or report. |

## JOSS paper

JOSS currently asks for a 750–1750-word Markdown paper with Summary, Statement
of need, State of the field, Software design, Research impact statement, AI
usage disclosure, author and affiliation metadata, key references, and
financial-support acknowledgement. It should discuss software rather than
present new scientific results or duplicate API documentation.

| Paper item | Repository evidence | Current assessment | Evidence or action still required |
|---|---|---|---|
| Summary and Statement of need | `paper/paper.md` | Drafted. | Read for non-specialist clarity and match claims to the submitted software. |
| State of the field | `paper/paper.md`, `paper/paper.bib`, `docs/COMPARISON.md` | Related tools and build-versus-contribute rationale are present. | Verify primary references, full venue names, and all relevant research/software citations. |
| Software design | `paper/paper.md`, `docs/ARCHITECTURE.md` | Architecture is described. | Explain key trade-offs and why they matter for this research workflow. |
| Research impact statement | Analytic benchmark, author report, evidence ledger | Author reports published use; representative source records are pending. The synthetic 45-check benchmark is reproducibility evidence, not evidence of research use or impact. | Cite the reported research papers or another auditable use record and keep each claim specific. Do not rely solely on future potential. |
| AI usage disclosure | `paper/paper.md`, `AUTHORS.md` | A disclosure exists for earlier development. | Update exact tool/model versions, where they were used, assistance scope, and verification methods for all work included in the submission; the submitting author must confirm complete human review. |
| Authors, affiliations, and funding | Paper metadata, `AUTHORS.md`, `CITATION.cff` | The user confirmed the currently listed author's name, ORCID, and affiliation. | Confirm completeness and consent of the author list; list every financial-support source and sponsor role, or state the author-confirmed absence of such support. |
| Rendered paper | `paper/paper.pdf`, Open Journals workflow run for commit `a09ee1b` [#36242597087](https://github.com/D-sudoasd/DiffractScout/actions/runs/36242597087) | The official workflow built the manuscript at commit `a09ee1b`. Four-page rendering and source/artifact identity, references, and text layer were checked. | The submitting author must review the final manuscript and set its date to the actual submission date before submission. |

## Project-specific scientific evidence gates

The local readiness tool is intentionally stricter than the JOSS checklist. It
requires a versioned, hashed real research-use case and public, pre-toleranced
diffraction and elasticity comparison reports. The current PR contains
regenerated synthetic comparison receipts, but the evidence-ledger hashes and
immutable source commit must be synchronized to the final public report before
those local report gates are counted as complete. The hashed real research-use
case and external-engagement records remain empty. These checks are project
quality controls, not additional JOSS checklist boxes. A calculation against
another software implementation may support a numerical-comparison report;
it does not establish experimental validity, research impact, or external
adoption.

## Final gate commands

```bash
python scripts/check_release.py
python scripts/joss_readiness.py --stage release --strict
python scripts/joss_readiness.py --stage submission --strict --as-of YYYY-MM-DD
python scripts/joss_readiness.py --stage publication --strict --as-of YYYY-MM-DD
```

Run release and submission checks on the exact clean source selected for
submission. The publication-stage check applies after successful review, when
the final tagged release and archive DOI can be matched to the citation and
review records.
