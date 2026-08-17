# JOSS reviewer-checklist evidence matrix

This matrix maps the current JOSS reviewer checklist to repository evidence.
It is a project-side acceptance aid, not a claim that JOSS has approved the
submission. Public URLs and human confirmations must be recorded before the
submission-stage gate can pass.

## General, development, and functionality

| Reviewer item | Repository evidence | Current state | Submission evidence still required |
|---|---|---|---|
| Repository and OSI license | Public GitHub repository; `LICENSE`; `NOTICE.md` | Available | Recheck the exact submission commit |
| Contribution and authorship | `AUTHORS.md`; Git history; `CITATION.cff` | Drafted | Human-confirm author list, order, contributions, and consent |
| Scope and significance | README; paper Statement of need; comparison document | Documented | Link the completed real multiphase case and its research decision |
| Sustained open development | GitHub commits, issues, pull requests, releases | Clock started 2026-08-12 | Show genuine activity distributed through at least 2027-02-12 |
| Collaborative effort | Contribution routes and research-use issue form | Routes available | Public external installation, review, issue, or contribution |
| Installation | `pyproject.toml`; README; wheel CI job | Automated in CI | Retain clean-wheel run URL for the submission commit |
| Functionality | CLI/API/GUI tests; demo and bundle verifier | Automated offline | Reviewer-style clean install and public real-material workflow |
| Performance claims | No speed or scaling claim in the paper | Not applicable | Do not add a performance claim without a reproducible benchmark |

## Documentation and verification

| Reviewer item | Repository evidence | Current state | Submission evidence still required |
|---|---|---|---|
| Statement of need | README; paper | Available | Audit against completed research-use evidence |
| Dependencies and installation | `pyproject.toml`; README | Available | Verify wheel on supported Python and operating systems |
| Example usage | Offline demo; examples; GUI guide | Available | Add completed multiphase case without restricted inputs |
| Functionality/API documentation | `docs/API.md`; `docs/GUI.md`; scientific contracts | Available | Review every public interface changed after v0.4.0 |
| Automated tests | `tests/`; CI; analytic benchmark | Available | Full CI green on the selected submission commit |
| Contribution, issue, and support paths | `CONTRIBUTING.md`; issue forms; `SUPPORT.md` | Available | Confirm links work without special access |
| Independent diffraction validation | Validation template and registry | Pending | Public comparison with predeclared tolerances |
| Independent elasticity validation | Validation template and registry | Pending | Public tensor, basis, directions, and comparison |

## Software paper

| Reviewer item | Repository evidence | Current state | Submission evidence still required |
|---|---|---|---|
| Summary | `paper/paper.md` | Drafted for non-specialists | Final author read-through |
| Statement of need | `paper/paper.md` | Drafted | Connect to the completed real workflow |
| State of the field | Paper and `docs/COMPARISON.md` | Drafted | Final citation and build-vs-contribute audit |
| Software design | Paper; architecture and scientific-contract docs | Drafted | Confirm it describes the submitted version |
| Research impact statement | Analytic benchmark and evidence ledger | Incomplete | Replace pending language with only traceable real-use evidence |
| AI usage disclosure | Paper and `AUTHORS.md` | Drafted | Human author confirms every disclosed scope and verification step |
| References | `paper/paper.bib`; draft workflow | Drafted | EditorialBot reference check and final venue-name audit |
| Rendered paper | `paper/paper.pdf`; official draft workflow | Local baseline available | Record successful official Open Journals build URL and inspect every page |

## Stage commands

```bash
# Create the current-source local acceptance receipt, then verify it.
python scripts/check_release.py
python scripts/joss_readiness.py --stage release --strict

# Run this only as a submission candidate gate.
python scripts/joss_readiness.py --stage submission --strict --as-of YYYY-MM-DD

# Run after review, final tag, and immutable software archive DOI exist.
python scripts/joss_readiness.py --stage publication --strict --as-of YYYY-MM-DD
```

The evidence ledger must remain incomplete rather than recording inferred,
private, prospective, or duplicated evidence.
